"""Persistent, non-blocking counterfactual monitor for OKAI AI decisions.

The monitor never changes strategy signals or orders. It records what the AI
said, observes later NIFTY prices, and estimates whether following the AI would
have helped or hurt in spot points over 5, 15 and 30 minute horizons.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


HORIZONS_MINUTES = (5, 15, 30)
PRIMARY_HORIZON_MINUTES = 15
DEFAULT_MIN_CONFIDENCE = 75
DEFAULT_MIN_RECORD_SPACING_SECONDS = 300
MAX_COMPLETED_RECORDS = 500


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"CE", "CALL", "CALL_BUY", "BULL", "BULLISH", "UP", "LONG_CE"}:
        return "CE"
    if text in {"PE", "PUT", "PUT_BUY", "BEAR", "BEARISH", "DOWN", "SHORT", "LONG_PE"}:
        return "PE"
    if text in {"NO_TRADE", "NO TRADE", "WAIT", "HOLD", "SKIP"}:
        return "NO_TRADE"
    return "WAIT"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: Optional[dt.datetime] = None) -> str:
    return (value or _utc_now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _first(mapping: Mapping[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        try:
            value = mapping.get(name)
        except Exception:
            continue
        if value is not None and value != "":
            return value
    return default


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(temporary), str(path))


class ShadowOutcomeMonitor:
    """Thread-safe shadow journal and counterfactual outcome evaluator."""

    def __init__(self, root: Optional[str] = None) -> None:
        base = root or os.getenv("OKAI_AI_SHADOW_DIR", "data/ai_shadow")
        self.root = Path(base)
        self.state_path = self.root / "state.json"
        self.summary_path = self.root / "summary.json"
        self.journal_path = self.root / "decisions.jsonl"
        self.lock = threading.RLock()
        self.pending: List[Dict[str, Any]] = []
        self.completed: List[Dict[str, Any]] = []
        self.last_recorded_at: Optional[dt.datetime] = None
        self.last_record_key = ""
        self.min_confidence = int(
            _number(os.getenv("OKAI_AI_SHADOW_MIN_CONFIDENCE"), DEFAULT_MIN_CONFIDENCE)
        )
        self.min_spacing_seconds = int(
            _number(
                os.getenv("OKAI_AI_SHADOW_MIN_SPACING_SECONDS"),
                DEFAULT_MIN_RECORD_SPACING_SECONDS,
            )
        )
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.pending = list(payload.get("pending") or [])
            self.completed = list(payload.get("completed") or [])[-MAX_COMPLETED_RECORDS:]
            self.last_record_key = str(payload.get("last_record_key") or "")
            self.last_recorded_at = _parse_iso(payload.get("last_recorded_at"))
        except Exception:
            self.pending = []
            self.completed = []

    def _persist(self) -> None:
        state = {
            "version": "OKAI-AI-SHADOW-MONITOR-V1",
            "updated_at": _iso(),
            "last_record_key": self.last_record_key,
            "last_recorded_at": _iso(self.last_recorded_at) if self.last_recorded_at else None,
            "pending": self.pending,
            "completed": self.completed[-MAX_COMPLETED_RECORDS:],
        }
        try:
            _atomic_json(self.state_path, state)
            _atomic_json(self.summary_path, self.summary())
        except Exception:
            pass

    def _append_journal(self, event: str, record: Mapping[str, Any]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            row = {"event": event, "written_at": _iso(), **dict(record)}
            with self.journal_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception:
            pass

    @staticmethod
    def _relation(strategy_signal: str, ai_decision: str) -> str:
        if strategy_signal in {"CE", "PE"}:
            if ai_decision == strategy_signal:
                return "AGREE"
            if ai_decision == "NO_TRADE":
                return "AI_WOULD_BLOCK"
            if ai_decision in {"CE", "PE"}:
                return "AI_OPPOSITE"
        if ai_decision in {"CE", "PE"}:
            return "AI_ONLY"
        return "OBSERVE"

    @staticmethod
    def _signed_points(decision: str, entry: float, exit_price: float) -> float:
        raw = exit_price - entry
        return raw if decision == "CE" else -raw if decision == "PE" else 0.0

    @staticmethod
    def _threshold(entry_price: float, horizon_minutes: int) -> float:
        base = max(4.0, abs(entry_price) * 0.00018)
        scale = {5: 0.8, 15: 1.0, 30: 1.25}.get(horizon_minutes, 1.0)
        return round(base * scale, 2)

    def register_decision(self, snapshot: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
        with self.lock:
            now = _utc_now()
            price = _number(snapshot.get("price"), 0.0)
            ai_decision = _direction(result.get("decision"))
            confidence = int(_number(result.get("confidence"), 0))
            strategy_signal = _direction(
                _first(snapshot, ("signal_direction", "signal", "side"), "WAIT")
            )
            market_open = bool(snapshot.get("market_open", True))
            success = bool(result.get("success", True))

            if not success or not market_open or price <= 0:
                return False
            if ai_decision not in {"CE", "PE", "NO_TRADE"}:
                return False
            if ai_decision in {"CE", "PE"} and confidence < self.min_confidence:
                return False
            if ai_decision == "NO_TRADE" and strategy_signal not in {"CE", "PE"}:
                return False

            relation = self._relation(strategy_signal, ai_decision)
            key = "%s|%s|%s|%s" % (
                ai_decision,
                strategy_signal,
                int(price / 5.0),
                relation,
            )
            elapsed = (
                (now - self.last_recorded_at).total_seconds()
                if self.last_recorded_at is not None
                else 10**9
            )
            if key == self.last_record_key and elapsed < self.min_spacing_seconds:
                return False

            record = {
                "id": uuid.uuid4().hex[:16],
                "created_at": _iso(now),
                "symbol": str(snapshot.get("symbol") or "NIFTY"),
                "entry_spot": round(price, 2),
                "ai_decision": ai_decision,
                "ai_confidence": confidence,
                "ai_probabilities": dict(result.get("probabilities") or {}),
                "ai_reasons": [str(item)[:120] for item in (result.get("reasons") or [])[:8]],
                "model_version": str(result.get("model_version") or "unknown"),
                "strategy_signal": strategy_signal,
                "strategy_score": round(_number(snapshot.get("strategy_score"), 0.0), 2),
                "strategy_min_score": round(_number(snapshot.get("min_strategy_score"), 0.0), 2),
                "strategy_trade_allowed": bool(snapshot.get("server_trade_allowed", False)),
                "relation": relation,
                "market_regime": str(snapshot.get("market_regime") or ""),
                "adx": round(_number(snapshot.get("adx"), 0.0), 2),
                "volume_ratio": round(_number(snapshot.get("volume_ratio"), 0.0), 3),
                "mfe_spot_points": 0.0,
                "mae_spot_points": 0.0,
                "outcomes": {},
                "complete": False,
                "order_execution": False,
                "mode": "SHADOW_ONLY",
            }
            self.pending.append(record)
            self.last_record_key = key
            self.last_recorded_at = now
            self._append_journal("DECISION_CREATED", record)
            self._persist()
            return True

    def observe(self, payload: Mapping[str, Any]) -> None:
        with self.lock:
            price = _number(
                _first(payload, ("price", "nifty", "nifty_price", "spot_price", "ltp", "close"), 0),
                0,
            )
            if price <= 0 or not self.pending:
                return
            now = _utc_now()
            changed = False
            newly_completed: List[Dict[str, Any]] = []

            for record in self.pending:
                created = _parse_iso(record.get("created_at"))
                if created is None:
                    continue
                entry = _number(record.get("entry_spot"), 0.0)
                ai_decision = str(record.get("ai_decision") or "NO_TRADE")
                strategy_signal = str(record.get("strategy_signal") or "WAIT")
                elapsed_seconds = max(0.0, (now - created).total_seconds())

                ai_points = self._signed_points(ai_decision, entry, price)
                if ai_decision in {"CE", "PE"}:
                    record["mfe_spot_points"] = round(
                        max(_number(record.get("mfe_spot_points"), 0.0), ai_points), 2
                    )
                    record["mae_spot_points"] = round(
                        min(_number(record.get("mae_spot_points"), 0.0), ai_points), 2
                    )

                outcomes = record.setdefault("outcomes", {})
                for horizon in HORIZONS_MINUTES:
                    key = "%sm" % horizon
                    if key in outcomes or elapsed_seconds < horizon * 60:
                        continue
                    threshold = self._threshold(entry, horizon)
                    spot_change = round(price - entry, 2)
                    strategy_points = self._signed_points(strategy_signal, entry, price)
                    if ai_decision in {"CE", "PE"}:
                        outcome = "WIN" if ai_points >= threshold else "LOSS" if ai_points <= -threshold else "FLAT"
                    else:
                        outcome = "CORRECT_SKIP" if abs(spot_change) < threshold else "MISSED_MOVE"

                    counterfactual = "OBSERVE"
                    benefit_points = 0.0
                    relation = str(record.get("relation") or "OBSERVE")
                    if relation == "AI_WOULD_BLOCK":
                        if strategy_points <= -threshold:
                            counterfactual = "AI_BLOCK_WOULD_HELP"
                            benefit_points = abs(strategy_points)
                        elif strategy_points >= threshold:
                            counterfactual = "AI_BLOCK_WOULD_HURT"
                            benefit_points = -abs(strategy_points)
                        else:
                            counterfactual = "AI_BLOCK_NEUTRAL"
                    elif relation == "AI_OPPOSITE":
                        difference = ai_points - strategy_points
                        counterfactual = "AI_OPPOSITE_BETTER" if difference > threshold else "AI_OPPOSITE_WORSE" if difference < -threshold else "AI_OPPOSITE_NEUTRAL"
                        benefit_points = difference
                    elif relation == "AGREE":
                        counterfactual = "AI_AGREEMENT_WIN" if ai_points >= threshold else "AI_AGREEMENT_LOSS" if ai_points <= -threshold else "AI_AGREEMENT_FLAT"

                    outcomes[key] = {
                        "evaluated_at": _iso(now),
                        "exit_spot": round(price, 2),
                        "spot_change": spot_change,
                        "ai_signed_spot_points": round(ai_points, 2),
                        "strategy_signed_spot_points": round(strategy_points, 2),
                        "noise_threshold_points": threshold,
                        "outcome": outcome,
                        "counterfactual": counterfactual,
                        "estimated_ai_benefit_spot_points": round(benefit_points, 2),
                    }
                    self._append_journal("HORIZON_EVALUATED", {"id": record.get("id"), "horizon": key, **outcomes[key]})
                    changed = True

                if all("%sm" % horizon in outcomes for horizon in HORIZONS_MINUTES):
                    record["complete"] = True
                    record["completed_at"] = _iso(now)
                    newly_completed.append(record)

            if newly_completed:
                completed_ids = {item.get("id") for item in newly_completed}
                self.pending = [item for item in self.pending if item.get("id") not in completed_ids]
                self.completed.extend(newly_completed)
                self.completed = self.completed[-MAX_COMPLETED_RECORDS:]
                changed = True

            if changed:
                self._persist()

    def summary(self) -> Dict[str, Any]:
        with self.lock:
            records = self.completed + self.pending
            evaluated = []
            for record in records:
                outcome = (record.get("outcomes") or {}).get("%sm" % PRIMARY_HORIZON_MINUTES)
                if outcome:
                    evaluated.append((record, outcome))

            directional = [(r, o) for r, o in evaluated if r.get("ai_decision") in {"CE", "PE"}]
            wins = sum(1 for _, outcome in directional if outcome.get("outcome") == "WIN")
            losses = sum(1 for _, outcome in directional if outcome.get("outcome") == "LOSS")
            flats = sum(1 for _, outcome in directional if outcome.get("outcome") == "FLAT")
            decided = wins + losses
            hit_rate = round((wins / decided) * 100.0, 2) if decided else None
            net_points = round(sum(_number(outcome.get("ai_signed_spot_points"), 0.0) for _, outcome in directional), 2)

            block_help = [o for r, o in evaluated if r.get("relation") == "AI_WOULD_BLOCK" and o.get("counterfactual") == "AI_BLOCK_WOULD_HELP"]
            block_hurt = [o for r, o in evaluated if r.get("relation") == "AI_WOULD_BLOCK" and o.get("counterfactual") == "AI_BLOCK_WOULD_HURT"]
            estimated_benefit = round(sum(_number(o.get("estimated_ai_benefit_spot_points"), 0.0) for _, o in evaluated), 2)

            recent = []
            for record in sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:10]:
                recent.append({
                    "id": record.get("id"),
                    "created_at": record.get("created_at"),
                    "ai_decision": record.get("ai_decision"),
                    "ai_confidence": record.get("ai_confidence"),
                    "strategy_signal": record.get("strategy_signal"),
                    "relation": record.get("relation"),
                    "entry_spot": record.get("entry_spot"),
                    "outcome_15m": (record.get("outcomes") or {}).get("15m"),
                })

            return {
                "version": "OKAI-AI-SHADOW-MONITOR-V1",
                "mode": "MONITOR_ONLY",
                "trade_blocking": False,
                "order_execution": False,
                "metric_unit": "NIFTY_SPOT_POINTS_NOT_OPTION_PNL",
                "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
                "minimum_ai_confidence": self.min_confidence,
                "pending_decisions": len(self.pending),
                "evaluated_15m": len(evaluated),
                "directional_evaluated_15m": len(directional),
                "wins_15m": wins,
                "losses_15m": losses,
                "flat_15m": flats,
                "directional_hit_rate_percent_15m": hit_rate,
                "net_ai_signed_spot_points_15m": net_points,
                "ai_block_would_help_count_15m": len(block_help),
                "ai_block_would_hurt_count_15m": len(block_hurt),
                "estimated_ai_benefit_spot_points_15m": estimated_benefit,
                "recent": recent,
                "updated_at": _iso(),
            }

    def status(self) -> Dict[str, Any]:
        return self.summary()
