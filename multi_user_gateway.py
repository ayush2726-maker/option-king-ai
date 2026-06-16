#!/usr/bin/env python3
"""
Option King AI multi-user gateway.

This file intentionally does not share the old bot globals between users.
Each user runs as an isolated worker process inside users/<user_id>/ with
its own app.py, config.json, data folder, Angel session, capital and position.
The gateway only authenticates and proxies requests to the matching worker.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_APP = os.path.join(APP_DIR, "app.py")
ROOT_CONFIG = os.path.join(APP_DIR, "config.json")
ROOT_EXAMPLE_CONFIG = os.path.join(APP_DIR, "config.example.json")
GATEWAY_CONFIG = os.path.join(APP_DIR, "multi_user_config.json")
USERS_DIR = os.path.join(APP_DIR, "users")
REGISTRY_PATH = os.path.join(USERS_DIR, "users.json")
USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,40}$")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_GATEWAY_PORT = 8765
DEFAULT_WORKER_PORT = 18765
PROXY_TIMEOUT_SECONDS = 90


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"{now_text()} | {message}", flush=True)


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        backup = f"{path}.bad_{int(time.time())}"
        try:
            shutil.copy2(path, backup)
        except Exception:
            pass
        log(f"Invalid JSON at {path}: {exc}; backup {backup}")
        return default


def save_json_atomic(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    os.replace(temp_path, path)


def sanitize_user_id(user_id: str) -> str:
    user_id = (user_id or "").strip()
    if not USER_ID_RE.match(user_id):
        raise ValueError("user_id must be 2-40 chars: letters, numbers, underscore or dash")
    return user_id


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def read_base_config() -> dict[str, Any]:
    if os.path.exists(ROOT_CONFIG):
        return load_json(ROOT_CONFIG, {})
    return load_json(ROOT_EXAMPLE_CONFIG, {})


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", int(port))) != 0


def local_lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def ensure_gateway_config() -> dict[str, Any]:
    cfg = load_json(GATEWAY_CONFIG, {})
    changed = False
    if not cfg.get("host"):
        cfg["host"] = DEFAULT_HOST
        changed = True
    if not cfg.get("port"):
        cfg["port"] = DEFAULT_GATEWAY_PORT
        changed = True
    if changed:
        save_json_atomic(GATEWAY_CONFIG, cfg)
    return cfg


class UserRegistry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        os.makedirs(USERS_DIR, exist_ok=True)
        self.data = self._load_or_create()

    def _load_or_create(self) -> dict[str, Any]:
        data = load_json(REGISTRY_PATH, {})
        if not data.get("admin_token"):
            data["admin_token"] = secrets.token_urlsafe(24)
        if "users" not in data or not isinstance(data["users"], list):
            data["users"] = []

        if not data["users"]:
            owner_config = read_base_config()
            owner_token = owner_config.get("api_auth_token") or "optionking-local"
            data["users"].append(
                {
                    "user_id": "owner",
                    "name": "Owner",
                    "token": owner_token,
                    "port": DEFAULT_WORKER_PORT,
                    "enabled": True,
                    "created_at": now_text(),
                }
            )
            save_json_atomic(REGISTRY_PATH, data)
            log("Created owner user from root config.json")
            log(f"Gateway admin token: {data['admin_token']}")
        else:
            save_json_atomic(REGISTRY_PATH, data)
        return data

    def save(self) -> None:
        with self.lock:
            save_json_atomic(REGISTRY_PATH, self.data)

    def admin_token(self) -> str:
        return str(os.environ.get("OPTIONKING_ADMIN_TOKEN") or self.data.get("admin_token") or "")

    def users(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(user) for user in self.data.get("users", [])]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        user_id = sanitize_user_id(user_id)
        with self.lock:
            for user in self.data.get("users", []):
                if user.get("user_id") == user_id:
                    return dict(user)
        return None

    def find_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.lock:
            for user in self.data.get("users", []):
                if user.get("enabled", True) and secrets.compare_digest(str(user.get("token", "")), token):
                    return dict(user)
        return None

    def next_port(self) -> int:
        used = {int(user.get("port", 0)) for user in self.data.get("users", []) if user.get("port")}
        port = DEFAULT_WORKER_PORT
        while port in used or not is_port_free(port):
            port += 1
        return port

    def upsert_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        user_id = sanitize_user_id(str(user_data.get("user_id") or ""))
        token = str(user_data.get("token") or "").strip()
        if len(token) < 8:
            raise ValueError("token must be at least 8 characters")

        with self.lock:
            existing = None
            for user in self.data.get("users", []):
                if user.get("user_id") == user_id:
                    existing = user
                    break

            if existing is None:
                existing = {
                    "user_id": user_id,
                    "created_at": now_text(),
                    "port": self.next_port(),
                }
                self.data.setdefault("users", []).append(existing)

            existing["name"] = str(user_data.get("name") or existing.get("name") or user_id)
            existing["token"] = token
            existing["enabled"] = bool(user_data.get("enabled", True))
            if user_data.get("port"):
                existing["port"] = int(user_data["port"])
            existing["updated_at"] = now_text()
            self.save()
            return dict(existing)


class WorkerManager:
    def __init__(self, registry: UserRegistry) -> None:
        self.registry = registry
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen[Any]] = {}

    def user_dir(self, user_id: str) -> str:
        return os.path.join(USERS_DIR, sanitize_user_id(user_id))

    def worker_app_path(self, user_id: str) -> str:
        return os.path.join(self.user_dir(user_id), "app.py")

    def worker_config_path(self, user_id: str) -> str:
        return os.path.join(self.user_dir(user_id), "config.json")

    def worker_log_path(self, user_id: str) -> str:
        return os.path.join(self.user_dir(user_id), "worker.log")

    def ensure_user_files(self, user: dict[str, Any]) -> None:
        user_id = sanitize_user_id(str(user["user_id"]))
        user_dir = self.user_dir(user_id)
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(os.path.join(user_dir, "data"), exist_ok=True)

        dst_app = self.worker_app_path(user_id)
        should_copy = not os.path.exists(dst_app)
        if os.path.exists(dst_app) and os.path.exists(ROOT_APP):
            should_copy = os.path.getmtime(ROOT_APP) > os.path.getmtime(dst_app) or os.path.getsize(ROOT_APP) != os.path.getsize(dst_app)
        if should_copy:
            shutil.copy2(ROOT_APP, dst_app)

        cfg_path = self.worker_config_path(user_id)
        if not os.path.exists(cfg_path):
            if user_id == "owner" and os.path.exists(ROOT_CONFIG):
                cfg = read_base_config()
                root_data = os.path.join(APP_DIR, "data")
                user_data = os.path.join(user_dir, "data")
                if os.path.exists(root_data) and not os.listdir(user_data):
                    try:
                        shutil.copytree(root_data, user_data, dirs_exist_ok=True)
                        log("Owner data copied into isolated user folder")
                    except Exception as exc:
                        log(f"Owner data copy skipped: {exc}")
            else:
                cfg = load_json(ROOT_EXAMPLE_CONFIG, {})
            cfg["api_auth_token"] = user["token"]
            cfg["host"] = "127.0.0.1"
            cfg["port"] = int(user["port"])
            save_json_atomic(cfg_path, cfg)
        else:
            cfg = load_json(cfg_path, {})
            changed = False
            for key, value in {
                "api_auth_token": user["token"],
                "host": "127.0.0.1",
                "port": int(user["port"]),
            }.items():
                if cfg.get(key) != value:
                    cfg[key] = value
                    changed = True
            if changed:
                save_json_atomic(cfg_path, cfg)

    def update_user_config(self, user: dict[str, Any], values: dict[str, Any]) -> None:
        self.ensure_user_files(user)
        cfg_path = self.worker_config_path(str(user["user_id"]))
        cfg = load_json(cfg_path, {})
        allowed = {
            "api_key",
            "client_id",
            "password",
            "totp_secret",
            "telegram_token",
            "chat_id",
            "capital",
            "auto_start_bot",
            "market_timezone",
            "market_holidays",
        }
        for key in allowed:
            if key in values and values[key] is not None:
                cfg[key] = values[key]
        cfg["api_auth_token"] = user["token"]
        cfg["host"] = "127.0.0.1"
        cfg["port"] = int(user["port"])
        save_json_atomic(cfg_path, cfg)

    def is_running(self, user_id: str) -> bool:
        proc = self.processes.get(user_id)
        return bool(proc and proc.poll() is None)

    def start_worker(self, user: dict[str, Any]) -> None:
        user_id = sanitize_user_id(str(user["user_id"]))
        if not user.get("enabled", True):
            return
        with self.lock:
            if self.is_running(user_id):
                return
            self.ensure_user_files(user)
            log_path = self.worker_log_path(user_id)
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"\n\n--- worker start {now_text()} ---\n")
            log_file.flush()
            proc = subprocess.Popen(
                [sys.executable, self.worker_app_path(user_id)],
                cwd=self.user_dir(user_id),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            self.processes[user_id] = proc
            log(f"Worker {user_id} started on 127.0.0.1:{user['port']}")

    def stop_worker(self, user_id: str) -> None:
        user_id = sanitize_user_id(user_id)
        with self.lock:
            proc = self.processes.get(user_id)
            if not proc or proc.poll() is not None:
                return
            try:
                if os.name == "nt":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            log(f"Worker {user_id} stopped")

    def restart_worker(self, user: dict[str, Any]) -> None:
        self.stop_worker(str(user["user_id"]))
        self.start_worker(user)

    def start_enabled_workers(self) -> None:
        for user in self.registry.users():
            if user.get("enabled", True):
                self.start_worker(user)

    def worker_url(self, user: dict[str, Any], path: str) -> str:
        return f"http://127.0.0.1:{int(user['port'])}{path}"


REGISTRY: UserRegistry | None = None
WORKERS: WorkerManager | None = None


def get_registry() -> UserRegistry:
    if REGISTRY is None:
        raise RuntimeError("registry not initialized")
    return REGISTRY


def get_workers() -> WorkerManager:
    if WORKERS is None:
        raise RuntimeError("worker manager not initialized")
    return WORKERS


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "OptionKingMultiUserGateway/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def get_user_from_token(self) -> dict[str, Any] | None:
        token = self.headers.get("X-Api-Token") or self.headers.get("Authorization", "").replace("Bearer ", "")
        return get_registry().find_by_token(token.strip())

    def check_admin(self) -> bool:
        token = self.headers.get("X-Admin-Token") or self.headers.get("X-Api-Token") or ""
        return secrets.compare_digest(token, get_registry().admin_token())

    def do_GET(self) -> None:
        if self.path.startswith("/admin"):
            self.handle_admin_get()
            return
        if self.path in {"/gateway/status", "/multi-user/status"}:
            self.send_json({"ok": True, "gateway": self.gateway_status(public=True)})
            return
        self.proxy_to_worker("GET")

    def do_POST(self) -> None:
        if self.path.startswith("/admin"):
            self.handle_admin_post()
            return
        self.proxy_to_worker("POST")

    def gateway_status(self, public: bool = False) -> dict[str, Any]:
        users = []
        for user in get_registry().users():
            users.append(
                {
                    "user_id": user.get("user_id"),
                    "name": user.get("name"),
                    "enabled": user.get("enabled", True),
                    "port": user.get("port"),
                    "running": get_workers().is_running(str(user.get("user_id"))),
                    "token": mask_token(str(user.get("token", ""))) if not public else None,
                }
            )
        return {
            "app": "Option King AI Multi-User Gateway",
            "time": now_text(),
            "users": users,
            "admin_token": mask_token(get_registry().admin_token()) if not public else None,
        }

    def handle_admin_get(self) -> None:
        if not self.check_admin():
            self.send_json({"ok": False, "error": "admin token required"}, 401)
            return
        if self.path in {"/admin/users", "/admin/status"}:
            self.send_json({"ok": True, "data": self.gateway_status(public=False)})
            return
        self.send_json({"ok": False, "error": "unknown admin endpoint"}, 404)

    def handle_admin_post(self) -> None:
        if not self.check_admin():
            self.send_json({"ok": False, "error": "admin token required"}, 401)
            return
        body = self.read_body()
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except Exception as exc:
            self.send_json({"ok": False, "error": f"invalid JSON: {exc}"}, 400)
            return

        if self.path == "/admin/users":
            try:
                user = get_registry().upsert_user(payload)
                get_workers().update_user_config(user, payload)
                get_workers().restart_worker(user)
                self.send_json(
                    {
                        "ok": True,
                        "data": {
                            "user_id": user["user_id"],
                            "name": user.get("name"),
                            "port": user.get("port"),
                            "enabled": user.get("enabled", True),
                            "token": mask_token(str(user.get("token", ""))),
                        },
                    }
                )
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        match = re.match(r"^/admin/users/([A-Za-z0-9_-]{2,40})/(restart|stop)$", self.path)
        if match:
            user_id, action = match.groups()
            user = get_registry().get_user(user_id)
            if not user:
                self.send_json({"ok": False, "error": "user not found"}, 404)
                return
            if action == "restart":
                get_workers().restart_worker(user)
            else:
                get_workers().stop_worker(user_id)
            self.send_json({"ok": True, "data": {"user_id": user_id, "action": action}})
            return

        self.send_json({"ok": False, "error": "unknown admin endpoint"}, 404)

    def proxy_to_worker(self, method: str) -> None:
        user = self.get_user_from_token()
        if not user:
            self.send_json({"ok": False, "error": "unauthorized user token"}, 401)
            return

        workers = get_workers()
        workers.start_worker(user)
        url = workers.worker_url(user, self.path)
        body = self.read_body() if method == "POST" else None
        headers = {
            "X-Api-Token": str(user["token"]),
            "Content-Type": self.headers.get("Content-Type") or "application/json",
        }
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=PROXY_TIMEOUT_SECONDS) as response:
                response_body = response.read()
                status = int(response.getcode())
                content_type = response.headers.get("Content-Type") or "application/json"
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            status = int(exc.code)
            content_type = exc.headers.get("Content-Type") or "application/json"
        except Exception as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": f"worker {user['user_id']} not reachable: {exc}",
                    "user_id": user["user_id"],
                },
                503,
            )
            return

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("X-OptionKing-User", str(user["user_id"]))
        self.end_headers()
        try:
            self.wfile.write(response_body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def init_globals() -> tuple[UserRegistry, WorkerManager]:
    global REGISTRY, WORKERS
    ensure_gateway_config()
    REGISTRY = UserRegistry()
    WORKERS = WorkerManager(REGISTRY)
    return REGISTRY, WORKERS


def prompt(default: str = "", label: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def add_user_interactive() -> None:
    registry, workers = init_globals()
    print("Option King AI multi-user creator")
    user_id = sanitize_user_id(prompt(label="User ID, e.g. friend1"))
    existing = registry.get_user(user_id) or {}
    token_default = str(existing.get("token") or secrets.token_urlsafe(18))
    payload: dict[str, Any] = {
        "user_id": user_id,
        "name": prompt(str(existing.get("name") or user_id), "Display name"),
        "token": prompt(token_default, "Mobile app token"),
        "api_key": prompt(label="Angel API Key"),
        "client_id": prompt(label="Angel Client ID"),
        "password": getpass.getpass("Angel Password: ").strip(),
        "totp_secret": prompt(label="Angel TOTP Secret"),
        "telegram_token": prompt(label="Telegram token optional"),
        "chat_id": prompt(label="Telegram chat id optional"),
        "enabled": True,
    }
    capital_text = prompt("20000", "Capital")
    try:
        payload["capital"] = float(capital_text)
    except ValueError:
        payload["capital"] = 20000

    user = registry.upsert_user(payload)
    workers.update_user_config(user, payload)
    print("\nUser saved OK")
    print(f"User ID: {user['user_id']}")
    print(f"Token: {payload['token']}")
    print("Mobile app URL: http://SERVER_PHONE_IP:8765")
    print("Start/restart gateway with: bash termux_start.sh")


def list_users() -> None:
    registry, workers = init_globals()
    for user in registry.users():
        print(
            f"{user.get('user_id')} | {user.get('name')} | port {user.get('port')} | "
            f"enabled={user.get('enabled', True)} | running={workers.is_running(str(user.get('user_id')))} | "
            f"token={mask_token(str(user.get('token', '')))}"
        )
    print(f"Admin token: {registry.admin_token()}")


def run_server() -> None:
    registry, workers = init_globals()
    cfg = ensure_gateway_config()
    workers.start_enabled_workers()

    host = str(cfg.get("host") or DEFAULT_HOST)
    port = int(cfg.get("port") or DEFAULT_GATEWAY_PORT)
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), GatewayHandler)

    print("Option King AI multi-user gateway starting...")
    print("Gateway URL:")
    print(f"  http://127.0.0.1:{port}")
    print("Same WiFi URL:")
    for ip in local_lan_ips():
        print(f"  http://{ip}:{port}")
    print(f"Admin token: {registry.admin_token()}")
    print("Users:")
    for user in registry.users():
        print(f"  {user.get('user_id')} -> worker 127.0.0.1:{user.get('port')} token {mask_token(str(user.get('token', '')))}")
    log(f"Multi-user gateway started: http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Option King AI multi-user gateway")
    parser.add_argument("--add-user", action="store_true", help="create or update one user interactively")
    parser.add_argument("--list-users", action="store_true", help="list users and admin token")
    args = parser.parse_args()

    if args.add_user:
        add_user_interactive()
        return
    if args.list_users:
        list_users()
        return
    run_server()


if __name__ == "__main__":
    main()
