"""Tiny SPA-fallback HTTP server for the mock PhenomeOne app."""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

MOCK_DIR = Path(__file__).resolve().parent / "mock_app"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(MOCK_DIR), **kw)

    def send_head(self):                      # SPA fallback: unknown path -> index.html
        path = self.translate_path(self.path)
        if not Path(path).is_file():
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *_a):               # keep the test output clean
        pass


class MockServer:
    def __init__(self, port: int = 0) -> None:
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/app/"
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "MockServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    with MockServer(8765) as s:
        print("serving", s.url)
        input("press Enter to stop...")
