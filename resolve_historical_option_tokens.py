"""Resolve historical NIFTY option token mappings from local evidence.

The script only reads cached candle filenames plus trade-data/log files. It
matches exact numeric tokens, deduplicates mirrored files, ranks candidate
symbols using date/expiry consistency, and emits a compact report. It never
imports app.py or executes orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


TOKEN_FILE_RE = re.compile(r"NFO_(\d+).*?(\d{8})\.json$", re.I)
SYMBOL_RE = re.compile(r"\b(NIFTY(\d{2}[A-Z]{3}\d{2})(\d{4,6})(CE|PE))\b", re.I)
DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")

OUTPUT_DIR = Path("data/ml_models")


def parse_date(value: str) -> Optional[str]:
    match = DATE_RE.search(value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def parse_expiry(symbol: str) -> Optional[str]:
    match = SYMBOL_RE.fullmatch(symbol.upper())
    if not match:
        return None
    try:
        return datetime.strptime(match.group(2), "%d%b%y").date().isoformat()
    except Exception:
        return None


def canonical_source_key(path: Path) -> str:
    # Main cache, owner mirror, and dated backups of the same file count once.
    return path.name


def iter_text_files(roots: Iterable[Path]) -> Iterable[Path]:
    allowed = {".csv", ".json", ".jsonl", ".log", ".txt"}
    seen: Set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            lower = str(path).lower()
            if "real_option_candles" in lower or "openapiscripmaster" in lower:
                continue
            try:
                if path.stat().st_size > 12 * 1024 * 1024:
                    continue
            except Exception:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield path


def collect_cached_tokens(
    roots: Iterable[Path],
    date_from: str,
    date_to: str,
) -> Dict[str, Set[str]]:
    token_dates: Dict[str, Set[str]] = defaultdict(set)
    seen_pairs: Set[Tuple[str, str]] = set()

    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.json"):
            match = TOKEN_FILE_RE.search(path.name)
            if not match:
                continue
            token, compact_date = match.groups()
            date_value = f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}"
            if not (date_from <= date_value <= date_to):
                continue
            pair = (token, date_value)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            token_dates[token].add(date_value)

    return token_dates


def exact_token_pattern(tokens: Iterable[str]) -> re.Pattern[str]:
    ordered = sorted(set(tokens), key=len, reverse=True)
    return re.compile(r"(?<!\d)(" + "|".join(map(re.escape, ordered)) + r")(?!\d)")


def scan_evidence(
    token_dates: Dict[str, Set[str]],
    roots: Iterable[Path],
) -> Dict[Tuple[str, str], Dict[str, object]]:
    evidence: Dict[Tuple[str, str], Dict[str, object]] = defaultdict(
        lambda: {
            "occurrences": 0,
            "source_keys": set(),
            "primary_source_keys": set(),
            "source_dates": set(),
        }
    )
    token_pattern = exact_token_pattern(token_dates)

    for path in iter_text_files(roots):
        source_key = canonical_source_key(path)
        is_primary = str(path).startswith("data/") and "backup" not in str(path).lower()
        file_date = parse_date(path.name)

        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    token_hits = set(token_pattern.findall(line))
                    if not token_hits:
                        continue
                    symbol_hits = {m.group(1).upper() for m in SYMBOL_RE.finditer(line)}
                    if not symbol_hits:
                        continue
                    line_date = parse_date(line) or file_date
                    for token in token_hits:
                        for symbol in symbol_hits:
                            item = evidence[(token, symbol)]
                            item["occurrences"] = int(item["occurrences"]) + 1
                            item["source_keys"].add(source_key)
                            if is_primary:
                                item["primary_source_keys"].add(source_key)
                            if line_date:
                                item["source_dates"].add(line_date)
        except Exception:
            continue

    return evidence


def score_candidate(
    token: str,
    symbol: str,
    item: Dict[str, object],
    candle_dates: Set[str],
) -> Dict[str, object]:
    expiry = parse_expiry(symbol)
    valid_dates = []
    day_diffs = []
    if expiry:
        expiry_date = datetime.fromisoformat(expiry).date()
        for date_value in sorted(candle_dates):
            candle_date = datetime.fromisoformat(date_value).date()
            diff = (expiry_date - candle_date).days
            if 0 <= diff <= 45:
                valid_dates.append(date_value)
                day_diffs.append(diff)

    source_keys = set(item["source_keys"])
    primary_source_keys = set(item["primary_source_keys"])
    occurrences = int(item["occurrences"])
    date_valid = bool(valid_dates)

    score = 0
    score += 30 if date_valid else -30
    score += min(len(source_keys), 5) * 5
    score += min(len(primary_source_keys), 3) * 7
    score += min(occurrences, 20)
    if day_diffs:
        score += max(0, 12 - min(day_diffs))

    return {
        "token": token,
        "symbol": symbol,
        "expiry": expiry,
        "score": score,
        "date_valid": date_valid,
        "valid_candle_dates": valid_dates,
        "min_days_to_expiry": min(day_diffs) if day_diffs else None,
        "occurrences": occurrences,
        "unique_sources": len(source_keys),
        "primary_sources": len(primary_source_keys),
        "source_dates": sorted(set(item["source_dates"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", default="2026-05-13")
    parser.add_argument("--date-to", default="2026-05-19")
    args = parser.parse_args()

    candle_roots = [
        Path("data/angel_cache/real_option_candles"),
        Path("users/owner/data/angel_cache/real_option_candles"),
    ]
    search_roots = [
        Path("data/trade_data"),
        Path("users/owner/data/trade_data"),
        Path("logs"),
    ]

    token_dates = collect_cached_tokens(candle_roots, args.date_from, args.date_to)
    if not token_dates:
        raise SystemExit("No cached option tokens found in requested date range")

    evidence = scan_evidence(token_dates, search_roots)
    by_token: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for (token, symbol), item in evidence.items():
        by_token[token].append(
            score_candidate(token, symbol, item, token_dates[token])
        )

    resolved = 0
    conflicts = 0
    no_evidence = 0
    report_rows: List[Dict[str, object]] = []

    print("=== COMPACT HISTORICAL TOKEN RESOLUTION ===")
    print("cached_tokens =", len(token_dates))
    print("date_from =", args.date_from)
    print("date_to =", args.date_to)
    print()

    for token in sorted(token_dates, key=int):
        candidates = sorted(
            by_token.get(token, []),
            key=lambda x: (int(x["score"]), int(x["primary_sources"]), int(x["occurrences"])),
            reverse=True,
        )
        top = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None

        if not top or not bool(top["date_valid"]):
            status = "NO_EVIDENCE"
            no_evidence += 1
        elif second and bool(second["date_valid"]) and int(top["score"]) - int(second["score"]) < 10:
            status = "CONFLICT"
            conflicts += 1
        else:
            status = "RESOLVED"
            resolved += 1

        row = {
            "token": token,
            "candle_dates": sorted(token_dates[token]),
            "status": status,
            "top_candidates": candidates[:3],
        }
        report_rows.append(row)

        top_text = "NONE"
        if top:
            top_text = (
                f"{top['symbol']} score={top['score']} "
                f"sources={top['unique_sources']} hits={top['occurrences']}"
            )
        print(
            token,
            "| dates=", ",".join(sorted(token_dates[token])),
            "|", status,
            "|", top_text,
        )
        if status == "CONFLICT":
            for candidate in candidates[:3]:
                print(
                    "   ", candidate["symbol"],
                    "score=", candidate["score"],
                    "valid=", candidate["date_valid"],
                    "sources=", candidate["unique_sources"],
                    "hits=", candidate["occurrences"],
                )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "historical_option_token_resolution.json"
    csv_path = OUTPUT_DIR / "historical_option_token_resolution.csv"
    json_path.write_text(json.dumps(report_rows, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "token",
            "candle_dates",
            "status",
            "top_symbol",
            "top_score",
            "top_expiry",
            "top_sources",
            "top_occurrences",
        ])
        for row in report_rows:
            top = row["top_candidates"][0] if row["top_candidates"] else {}
            writer.writerow([
                row["token"],
                ",".join(row["candle_dates"]),
                row["status"],
                top.get("symbol", ""),
                top.get("score", ""),
                top.get("expiry", ""),
                top.get("unique_sources", ""),
                top.get("occurrences", ""),
            ])

    print()
    print("resolved =", resolved)
    print("conflicts =", conflicts)
    print("no_evidence =", no_evidence)
    print("json =", json_path)
    print("csv =", csv_path)
    print("orders = UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
