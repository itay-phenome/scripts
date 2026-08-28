"""Tiny SPA-fallback HTTP server for the mock PhenomeOne app."""
from __future__ import annotations

import http.server
import threading
import time
from pathlib import Path

MOCK_DIR = Path(__file__).resolve().parent / "mock_app"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(MOCK_DIR), **kw)

    def do_GET(self):                         # noqa: N802 - stdlib naming
        # A deliberately slow data endpoint: `/slow-data?ms=900`. Real SPAs
        # change route, fetch, and render when the response lands; the DOM is
        # perfectly quiet in between, which is exactly the window `wait_stable`
        # must not mistake for "settled".
        if self.path.startswith("/slow-data"):
            ms = 900
            if "ms=" in self.path:
                try:
                    ms = max(0, min(5000, int(self.path.split("ms=", 1)[1].split("&")[0])))
                except ValueError:
                    pass
            time.sleep(ms / 1000)
            body = b'{"rows": ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]}'
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                # The point of a slow endpoint is that a test may navigate away
                # while it is still in flight. A dead client is the expected
                # ending here, not a server error worth a traceback.
                pass
            return
        return super().do_GET()

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
