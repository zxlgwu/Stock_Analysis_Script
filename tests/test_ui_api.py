"""Offline tests for the local read API. They never start a real weekly job."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from stock_agent.core.models import PriceStats, ScoreRecord, Security, StoredArticle
from stock_agent.db.repository import Database
from stock_agent.ui.jobs import JobManager, WEEKLY_NOTE
from stock_agent.ui.models import parse_ollama_list
from stock_agent.ui.server import AppState, create_server

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\x02\x00\x00\x00\x00IEND\xaeB`\x82"
)
_OLLAMA = """\
NAME                       ID              SIZE      MODIFIED
nomic-embed-text:latest    0a109f422b47    274 MB    2 hours ago
qwen2.5:3b                 357c53fb659c    1.9 GB    2 months ago
qwen2.5vl:3b               fb90415cde1e    3.2 GB    2 months ago
qwen2.5:latest             845dbda0ea48    4.7 GB    2 months ago
"""
_SECRET = "smtp-secret-should-not-appear"
_CLUSTER = "aaaaaaaaaaaaaaaa"


class _App:
    def __init__(self, tmp_path: Path, runner):
        db_path = tmp_path / "stock_agent.db"
        _seed(Database(db_path))
        charts = tmp_path / "charts"
        (charts / "2026-11-06").mkdir(parents=True)
        (charts / "2026-11-06" / "AAPL.png").write_bytes(_PNG)
        settings = tmp_path / "settings.yaml"
        settings.write_text(Path("config/settings.yaml").read_text())
        self.settings = settings
        self.state = AppState(
            database_path=db_path,
            settings_path=settings,
            charts_dir=charts,
            jobs=JobManager(runner=runner),
            list_models=lambda: parse_ollama_list(_OLLAMA),
        )
        self.httpd = create_server(self.state, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.state.jobs.close()
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path: str) -> tuple[int, bytes, str]:
        last_error: Exception | None = None
        for _ in range(20):
            try:
                with urllib.request.urlopen(self.base + path, timeout=5) as response:
                    return response.status, response.read(), response.headers.get("Content-Type", "")
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError as exc:
                last_error = exc
                time.sleep(0.05)
        assert last_error is not None
        raise last_error

    def get_json(self, path: str) -> dict:
        status, body, _content_type = self.get(path)
        assert status == 200
        return json.loads(body.decode())

    def post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())


def _forbid(kind: str) -> None:
    raise AssertionError(f"tests must not start a {kind} job")


def _seed(db: Database) -> None:
    when = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)
    week = date(2026, 11, 6)
    db.upsert_companies(
        [
            Security("AAPL", "NASDAQ", "Apple", sector="Technology", industry="Phones"),
            Security("MSFT", "NASDAQ", "Microsoft", sector="Technology", industry="Software"),
        ],
        week,
    )
    db.upsert_articles(
        [
            StoredArticle(
                id="a1",
                source="rss",
                url="https://news.example.com/aapl",
                title="Apple raises services guidance",
                body="Services growth stays firm.",
                published_at=when,
                fetched_at=when,
                content_hash="abc",
                cluster_id=_CLUSTER,
            )
        ]
    )
    db.upsert_cluster(_CLUSTER, "a1", when, 1, event_summary="Services guidance moved higher.")
    db.save_materiality(_CLUSTER, True, "company", "Services guidance", "ollama/qwen2.5:3b", "v")
    db.replace_channels(
        _CLUSTER,
        [("Apple", "company", 1, "direct", "positive", "Services revenue rises", "AAPL", "m", "v")],
    )
    db.save_impacts(
        [
            (
                _CLUSTER,
                "AAPL",
                "direct",
                "positive",
                "Services",
                4.0,
                "mid",
                0.8,
                "no",
                "Services can compound.",
                "ollama/qwen2.5:3b",
                "v",
                when.isoformat(),
            )
        ]
    )
    db.upsert_scores(
        [
            ScoreRecord(week, "AAPL", 1, 1, 2, 4, 0.5, 0.2, 0.1, 0.1, 1.2),
            ScoreRecord(week, "MSFT", 0.4, 0.2, 1, 0.5, 0.4, 0.2, 0.1, 0.1, 0.8),
        ]
    )
    db.replace_recommendations(
        week,
        [
            (week.isoformat(), "AAPL", "long", 1, "Services can compound.", "Guidance could be cut."),
            (week.isoformat(), "MSFT", "mid", 1, "Cloud demand holds.", "Spending could slow."),
        ],
    )
    db.upsert_price_stats(
        [
            PriceStats(
                ticker="AAPL",
                week_ending=week,
                ret_1y=0.10,
                ret_3y=0.20,
                ret_5y=None,
                cagr=0.12,
                rel_spy_1y=0.04,
                rel_spy_3y=None,
                rel_spy_5y=None,
                rel_sector_1y=None,
                rel_sector_3y=None,
                rel_sector_5y=None,
                max_drawdown=-0.25,
                max_dd_start=None,
                max_dd_end=None,
                current_drawdown=-0.05,
                vol_1y=0.18,
                vol_full=0.22,
                ma_convergence=None,
            )
        ]
    )
    db.close()


def test_read_api_serves_stories_ideas_company_and_chart(tmp_path: Path):
    app = _App(tmp_path, _forbid)
    try:
        status, page, content_type = app.get("/")
        text = page.decode()
        assert status == 200 and "text/html" in content_type
        for label in ("This week", "Ideas", "Company", "Run", "Settings"):
            assert label in text
        assert WEEKLY_NOTE in text
        assert 'class="process-window"' in text
        assert 'id="run-now"' in text
        assert "ollama/nomic-embed-text" in text
        assert "all-MiniLM-L6-v2" in text
        assert "The SMTP password stays in .env." in text

        week = app.get_json("/api/week")
        assert week["week_ending"] == "2026-11-06"
        assert week["stories"][0]["title"] == "Apple raises services guidance"
        assert week["stories"][0]["effect_count"] == 1

        story = app.get_json(f"/api/story?id={_CLUSTER}")
        assert story["steps"][0]["label"] == "Direct"
        assert story["steps"][0]["tickers"] == ["AAPL"]
        assert story["effects"][0]["estimated_impact"] == "+4.0%"
        assert story["effects"][0]["source_url"] == "https://news.example.com/aapl"

        ideas = app.get_json("/api/ideas")
        assert ideas["long"][0]["thesis"] == "Services can compound."
        assert ideas["long"][0]["chart_url"] == "/charts/2026-11-06/AAPL.png"
        assert ideas["mid"][0]["ticker"] == "MSFT"
        assert ideas["mid"][0]["chart_url"] is None
        assert ideas["risk"] == []

        matches = app.get_json("/api/companies?q=Apple")
        assert matches["companies"][0]["ticker"] == "AAPL"
        company = app.get_json("/api/company?ticker=AAPL")
        assert company["name"] == "Apple"
        assert {"label": "1-year return", "value": "+10.0%"} in company["price_lines"]
        assert company["impacts"][0]["reasoning"] == "Services can compound."

        status, png, content_type = app.get("/charts/2026-11-06/AAPL.png")
        assert status == 200 and content_type.startswith("image/png") and png.startswith(b"\x89PNG")
        try:
            app.get("/charts/2026-11-06/..%2F..%2Fsecret.png")
            raise AssertionError("a chart path outside the charts folder should be refused")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        try:
            app.get("/api/company?ticker=ZZZZ")
            raise AssertionError("an unknown ticker should be refused")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        app.close()


def test_settings_hide_the_smtp_password_and_keep_the_embed_role(tmp_path: Path, monkeypatch):
    app = _App(tmp_path, _forbid)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "reports@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", _SECRET)
    try:
        original = app.settings.read_text()
        embed = next(line for line in original.splitlines() if line.strip().startswith("embed:"))
        payload = app.get_json("/api/settings")
        encoded = json.dumps(payload)
        assert _SECRET not in encoded
        assert "smtp_password" not in encoded.lower()
        assert payload["email_configured"] is True
        assert payload["recipients"] == ["zxlnwpu@gmail.com"]
        too_large = next(item for item in payload["models"] if item["name"] == "qwen2.5:latest")
        assert too_large["kind"] == "too_large" and too_large["selectable"] is False
        assert "8 GB" in too_large["note"]
        default = next(item for item in payload["models"] if item["name"] == "qwen2.5:3b")
        assert default["selectable"] is True and default["model"] == "ollama/qwen2.5:3b"
        embed_model = next(item for item in payload["models"] if item["name"] == "nomic-embed-text:latest")
        assert embed_model["kind"] == "embed" and embed_model["selectable"] is False
        assert payload["embed"]["settings_model"] == "all-MiniLM-L6-v2"
        assert payload["embed"]["industry_model"] == "ollama/nomic-embed-text"

        refused, body = app.post("/api/settings", {"smtp_password": _SECRET, "top_n": 4})
        assert refused == 400
        assert _SECRET not in body["error"]
        assert app.settings.read_text() == original

        refused, body = app.post("/api/settings", {"analysis_model": "ollama/qwen2.5:latest", "top_n": 4})
        assert refused == 400
        assert "too large" in body["error"]
        assert app.settings.read_text() == original

        saved_code, saved = app.post(
            "/api/settings",
            {
                "analysis_model": "ollama/qwen2.5:3b",
                "max_stories_per_week": 12,
                "fetch_article_text": False,
                "top_n": 7,
                "news_sources": ["finnhub", "sec_edgar_8k", "rss"],
                "recipients": ["reports@example.com"],
            },
        )
        assert saved_code == 200
        assert saved["top_n"] == 7
        assert saved["fetch_article_text"] is False
        assert saved["news_sources"] == ["finnhub", "sec_edgar_8k", "rss"]
        assert _SECRET not in json.dumps(saved)
        updated = app.settings.read_text()
        assert _SECRET not in updated
        assert next(line for line in updated.splitlines() if line.strip().startswith("embed:")) == embed
        assert 'model: "ollama/qwen2.5:3b"' in updated
        assert "gdelt" not in updated
        assert "max_stories_per_week: 12" in updated
        assert "fetch_article_text: false" in updated
        assert "top_n: 7" in updated

        monkeypatch.delenv("SMTP_PASSWORD")
        assert app.get_json("/api/settings")["email_configured"] is False
    finally:
        app.close()


def test_job_stream_shows_mapping_lines_and_refuses_a_second_job(tmp_path: Path):
    release = threading.Event()
    calls: list[str] = []

    def runner(kind: str) -> None:
        calls.append(kind)
        print(f"Mapping {kind} headline")
        release.wait(5)

    app = _App(tmp_path, runner)
    found = bytearray()
    try:
        reader = threading.Thread(target=_read_until, args=(app, found), daemon=True)
        reader.start()
        status, payload = app.post("/api/run/weekly")
        assert status == 202 and payload["status"] == "running"
        busy, busy_body = app.post("/api/run/collect")
        assert busy == 409
        assert busy_body["error"] == "A job is already running."
        reader.join(5)
        assert not reader.is_alive()
        assert b"Mapping weekly headline" in found
        release.set()
        assert app.state.jobs.wait(3)
        snap = app.get_json("/api/run")
        assert snap["status"] == "finished"
        assert calls == ["weekly"]
        assert any(line.startswith("Mapping ") for line in snap["lines"])
        assert WEEKLY_NOTE == snap["weekly_note"]
    finally:
        release.set()
        app.close()


def test_cursor_model_can_be_saved_and_answers_without_editing(tmp_path: Path):
    from types import SimpleNamespace

    from stock_agent.llm.base import Message
    from stock_agent.llm.cursor_provider import CursorAuthError, CursorProvider, cursor_model_choices
    from stock_agent.ui.models import parse_ollama_list
    from stock_agent.ui.settings_io import save_settings

    choices = cursor_model_choices(
        [
            SimpleNamespace(id="composer-2.5", display_name="Composer 2.5", description="Default Cursor model."),
            SimpleNamespace(id="auto", display_name="Auto", description="Cursor picks the model."),
        ]
    )
    assert [item["model"] for item in choices] == ["cursor/composer-2.5", "cursor/auto"]
    assert all(item["selectable"] and item["group"] == "Cursor" for item in choices)

    path = tmp_path / "settings.yaml"
    path.write_text(Path("config/settings.yaml").read_text())
    saved = save_settings(
        path,
        {"analysis_model": "cursor/composer-2.5"},
        parse_ollama_list(_OLLAMA) + choices,
    )
    assert saved["analysis_model"] == "cursor/composer-2.5"
    text = path.read_text()
    assert "provider: cursor, model: \"composer-2.5\"" in text
    assert "embed:" in text and "all-MiniLM-L6-v2" in text

    seen = {}

    def prompt(body: str, model: str, api_key: str):
        seen["body"] = body
        seen["model"] = model
        seen["key"] = api_key
        return SimpleNamespace(
            status="finished",
            result='{"relevant": true}',
            usage=SimpleNamespace(input_tokens=3, output_tokens=4),
        )

    result = CursorProvider(prompt=prompt, api_key="cursor_test").complete(
        [Message("system", "Return JSON."), Message("user", "Headline: Jetty")],
        model="composer-2.5",
    )
    assert result.text == '{"relevant": true}'
    assert result.provider == "cursor"
    assert seen["model"] == "composer-2.5"
    assert seen["key"] == "cursor_test"
    assert "Do not edit files" in seen["body"]
    assert "Headline: Jetty" in seen["body"]

    try:
        CursorProvider(prompt=prompt, api_key="").complete([Message("user", "Hi")], model="auto")
    except CursorAuthError as exc:
        assert exc.is_retryable is False
    else:
        raise AssertionError("A missing Cursor key should stop the call.")


def _read_until(app: _App, found: bytearray) -> None:
    port = app.httpd.server_address[1]
    sock = None
    for _ in range(20):
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            break
        except ConnectionRefusedError:
            time.sleep(0.05)
    assert sock is not None
    with sock:
        sock.sendall(b"GET /api/run/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        sock.settimeout(1)
        while b"Mapping weekly headline" not in found:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return
            found.extend(chunk)
