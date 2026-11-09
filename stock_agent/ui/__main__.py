"""Open the Stock Agent window, or serve the page on this Mac.

Quitting the window stops this server. It does not stop Ollama.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from dotenv import load_dotenv

from stock_agent.core.config import PROJECT_ROOT, Settings
from stock_agent.ui.jobs import JobManager
from stock_agent.ui.models import installed_models
from stock_agent.ui.server import AppState, StockServer, create_server


class LinkApi:
    """Lets the page open a source article in the system browser."""

    def open_link(self, url: str) -> None:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Open the Stock Agent window.")
    parser.add_argument("--serve-only", action="store_true", help="Serve the local page without opening a window")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    load_dotenv(PROJECT_ROOT / ".env")
    state = _state()
    httpd = _bind(state, args.port)
    thread = threading.Thread(target=httpd.serve_forever, name="stock-agent-http", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        if args.serve_only:
            print(f"Stock Agent is available at {url}", flush=True)
            _wait(thread)
            return
        try:
            import webview
        except ImportError:
            print("pywebview is not installed, so the native window did not open.")
            print(f"Stock Agent is available at {url}", flush=True)
            _wait(thread)
            return
        _open_window(webview, url)
    finally:
        state.jobs.close()
        httpd.shutdown()
        httpd.server_close()


def _state() -> AppState:
    settings = Settings.load()
    return AppState(
        database_path=settings.database_path,
        settings_path=settings.root / "config" / "settings.yaml",
        charts_dir=settings.root / "output" / "charts",
        jobs=JobManager(),
        list_models=installed_models,
    )


def _bind(state: AppState, port: int) -> StockServer:
    last_error: OSError | None = None
    for candidate in range(port, port + 20):
        try:
            return create_server(state, port=candidate)
        except OSError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _wait(thread: threading.Thread) -> None:
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        return


def _open_window(webview, url: str) -> None:
    attempts = [
        {"width": 1180, "height": 820, "min_size": (860, 640), "text_select": True, "js_api": LinkApi()},
        {"width": 1180, "height": 820, "min_size": (860, 640), "js_api": LinkApi()},
        {"width": 1180, "height": 820, "js_api": LinkApi()},
        {"width": 1180, "height": 820},
    ]
    last_error: TypeError | None = None
    for kwargs in attempts:
        try:
            webview.create_window("Stock Agent", url, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue
        webview.start()
        return
    if last_error is not None:
        raise last_error


if __name__ == "__main__":
    main()
