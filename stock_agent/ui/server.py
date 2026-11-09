"""Local HTTP server for the stock agent window. Binds to this machine only."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from stock_agent.db.repository import Database
from stock_agent.ui.jobs import JobManager
from stock_agent.ui.models import installed_models
from stock_agent.ui.queries import (
    chart_file,
    company_payload,
    ideas_payload,
    search_companies,
    story_payload,
    week_payload,
)
from stock_agent.ui.settings_io import SettingsError, public_settings, save_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_FILES = {"index.html": "text/html; charset=utf-8", "app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}


@dataclass
class AppState:
    database_path: Path
    settings_path: Path
    charts_dir: Path
    jobs: JobManager
    list_models: Callable[[], list[dict]] = installed_models


class StockServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_server(state: AppState, host: str = "127.0.0.1", port: int = 8765) -> StockServer:
    handler = _handler_class(state)
    return StockServer((host, port), handler)


def _handler_class(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, fmt: str, *args) -> None:
            return

        def _dispatch(self, method: str) -> None:
            self._responded = False
            try:
                _route(self, state, method)
            except SettingsError as exc:
                _send_json(self, 400, {"error": str(exc)})
            except Exception:
                traceback.print_exc()
                if not self._responded:
                    _send_json(self, 500, {"error": "The local server hit an unexpected problem."})

    return Handler


def _route(handler: BaseHTTPRequestHandler, state: AppState, method: str) -> None:
    parsed = urlparse(handler.path)
    path = unquote(parsed.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = parse_qs(parsed.query)

    if method == "GET" and path in {"", "/"}:
        _send_static(handler, "index.html")
        return
    if method == "GET" and path.lstrip("/") in _STATIC_FILES:
        _send_static(handler, path.lstrip("/"))
        return
    if method == "GET" and path.startswith("/charts/"):
        _send_chart(handler, state, path)
        return
    if method == "GET" and path == "/api/week":
        _send_json(handler, 200, _read(state, week_payload))
        return
    if method == "GET" and path == "/api/story":
        story = _read(state, lambda db: story_payload(db, _first(query, "id")))
        if story is None:
            _send_json(handler, 404, {"error": "That story is not in the analyzed set."})
            return
        _send_json(handler, 200, story)
        return
    if method == "GET" and path == "/api/ideas":
        _send_json(handler, 200, _read(state, lambda db: ideas_payload(db, state.charts_dir)))
        return
    if method == "GET" and path == "/api/companies":
        _send_json(handler, 200, {"companies": _read(state, lambda db: search_companies(db, _first(query, "q")))})
        return
    if method == "GET" and path == "/api/company":
        company = _read(state, lambda db: company_payload(db, state.charts_dir, _first(query, "ticker")))
        if company is None:
            _send_json(handler, 404, {"error": "No company matches that ticker."})
            return
        _send_json(handler, 200, company)
        return
    if method == "GET" and path == "/api/run":
        _send_json(handler, 200, state.jobs.snapshot())
        return
    if method == "GET" and path == "/api/run/stream":
        _stream(handler, state)
        return
    if method == "GET" and path == "/api/settings":
        _send_json(handler, 200, public_settings(state.settings_path, state.list_models()))
        return
    if method == "POST" and path == "/api/run/collect":
        code, payload = state.jobs.start("collect")
        _send_json(handler, code, payload)
        return
    if method == "POST" and path == "/api/run/weekly":
        code, payload = state.jobs.start("weekly")
        _send_json(handler, code, payload)
        return
    if method == "POST" and path == "/api/settings":
        if state.jobs.snapshot()["status"] == "running":
            _send_json(handler, 409, {"error": "Settings save stays off while a job is running."})
            return
        saved = save_settings(state.settings_path, _read_json(handler), state.list_models())
        _send_json(handler, 200, saved)
        return
    if path.startswith("/api/"):
        _send_json(handler, 404, {"error": "That page is not part of Stock Agent."})
        return
    _send_text(handler, 404, "That page is not part of Stock Agent.")


def _read(state: AppState, fn):
    db = Database(state.database_path)
    try:
        return fn(db)
    finally:
        db.close()


def _send_chart(handler: BaseHTTPRequestHandler, state: AppState, path: str) -> None:
    parts = path.split("/")
    if len(parts) != 4:
        _send_text(handler, 404, "That chart is not available.")
        return
    _, _charts, week, filename = parts
    file_path = chart_file(state.charts_dir, week, filename)
    if file_path is None:
        _send_text(handler, 404, "That chart is not available.")
        return
    _send_bytes(handler, 200, file_path.read_bytes(), "image/png")


def _stream(handler: BaseHTTPRequestHandler, state: AppState) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    handler._responded = True  # type: ignore[attr-defined]
    handler.close_connection = True
    cursor = 0
    generation: int | None = None
    last_id = handler.headers.get("Last-Event-ID")
    if last_id and last_id.isdigit():
        cursor = int(last_id)
    timeout = 0.0
    try:
        while not state.jobs.stopped.is_set():
            lines, payload = state.jobs.wait_from(cursor, timeout, generation)
            timeout = 15.0
            status = {key: payload[key] for key in ("job", "status", "weekly_note", "generation")}
            _chunk(handler, _event("status", status))
            generation = payload["generation"]
            for index, line in lines:
                _chunk(handler, _event("line", {"line": line}, event_id=index))
                cursor = index
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
        return


def _event(name: str, payload: dict, event_id: int | None = None) -> bytes:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {name}")
    parts.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    parts.append("")
    parts.append("")
    return "\n".join(parts).encode()


def _chunk(handler: BaseHTTPRequestHandler, payload: bytes) -> None:
    handler.wfile.write(f"{len(payload):X}\r\n".encode())
    handler.wfile.write(payload)
    handler.wfile.write(b"\r\n")
    handler.wfile.flush()


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > 100_000:
        raise SettingsError("That settings update is too large.")
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode())
    except json.JSONDecodeError as exc:
        raise SettingsError("Send the settings as JSON.") from exc
    if not isinstance(payload, dict):
        raise SettingsError("Send the settings as JSON.")
    return payload


def _send_json(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    _send_bytes(handler, code, body, "application/json; charset=utf-8")


def _send_text(handler: BaseHTTPRequestHandler, code: int, text: str) -> None:
    _send_bytes(handler, code, text.encode(), "text/plain; charset=utf-8")


def _send_static(handler: BaseHTTPRequestHandler, name: str) -> None:
    if name not in _STATIC_FILES:
        _send_text(handler, 404, "That page is not part of Stock Agent.")
        return
    path = (STATIC_DIR / name).resolve()
    if path.parent != STATIC_DIR.resolve() or not path.is_file():
        _send_text(handler, 404, "That page is not part of Stock Agent.")
        return
    _send_bytes(handler, 200, path.read_bytes(), _STATIC_FILES[name])


def _first(query: dict, key: str) -> str:
    values = query.get(key) or []
    return values[0] if values else ""


def _send_bytes(handler: BaseHTTPRequestHandler, code: int, body: bytes, content_type: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler._responded = True  # type: ignore[attr-defined]
    if handler.command != "HEAD":
        handler.wfile.write(body)
