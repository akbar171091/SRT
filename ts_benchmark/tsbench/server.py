"""Local web server for the benchmark front end (standard library only).

Listens on the loopback address only: the term sheets are confidential and nothing here is meant
to be reachable from another machine, or from another web page open in the same browser.

Routes
    GET  /                       the front end
    GET  /api/dataset            every term sheet record, derived figures and preset peer statistics
    GET  /api/benchmark?ids=a,b  peer statistics for a chosen set of deals
    POST /api/refresh            re-scan the folder and rebuild
    GET  /pdf/<deal id>          the source PDF (so a quote can be opened at its page)
    GET  /export/<name>.csv      CSV extracts; ?group=<preset> or ?ids=a,b selects the peer group
    GET  /export/report.html     the front end as one self-contained file
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import benchmark, dataset, exports
from .config import STATIC_DIR

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
# The page is one file with inline script and style; it loads nothing else and may only call this server.
_PAGE_POLICY = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class App:
    """The folder being benchmarked and the dataset built from it."""

    def __init__(self, docs_dir: Path, use_cache: bool = True, use_verified: bool = True):
        self.docs_dir = Path(docs_dir)
        self.use_cache = use_cache
        self.use_verified = use_verified
        self._lock = threading.Lock()
        self.data: dict | None = None

    def build(self, progress=None) -> dict:
        with self._lock:
            self.data = dataset.build(self.docs_dir, self.use_cache, self.use_verified, progress)
            for d in self.data["deals"]:
                d["pdf_url"] = f"/pdf/{d['id']}"
            return self.data

    def get(self) -> dict:
        # An empty result is not kept: the folder may only have been empty for a moment, and a page
        # reload must be able to pick the term sheets up again.
        if self.data is None or not self.data["deals"]:
            return self.build()
        return self.data


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TSBench"

        def log_message(self, fmt, *args):  # keep the console quiet; errors still go to stderr
            pass

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            headers = {
                "Content-Type": ctype,
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Referrer-Policy": "no-referrer",
                **(extra or {}),
            }
            for value in headers.values():
                value.encode("latin-1")  # a header that cannot be sent fails here, before any part of the response is written
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str):
            try:
                self._json({"error": message}, status)
            except ConnectionError:
                pass  # the browser has already gone

        def _target(self):
            """The parsed request target, or None (after answering 400) when it is not a valid URL."""
            try:
                return urlparse(self.path)
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "Bad request")
                return None

        def _allowed(self, path: str) -> bool:
            """Refuse anything that does not come from this machine's own copy of the page.

            A foreign Host header means a web page is reaching the server through DNS rebinding. A
            Sec-Fetch-Site header other than same-origin means another site (or another local app) is
            making the request: it may link to the front page, and nothing else.
            """
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in _LOCAL_HOSTS:
                self._error(HTTPStatus.FORBIDDEN, "This server only answers on localhost.")
                return False
            site = (self.headers.get("Sec-Fetch-Site") or "").lower()
            if site in ("", "same-origin", "none"):
                return True
            followed_link = (self.command in ("GET", "HEAD") and path in ("/", "/index.html")
                             and self.headers.get("Sec-Fetch-Mode") == "navigate" and self.headers.get("Sec-Fetch-Dest") == "document")
            if not followed_link:
                self._error(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
            return followed_link

        def _bench(self, data: dict, query: dict) -> dict | None:
            """The peer group named in an export link: chosen deals, a preset, or None for all term sheets."""
            known = {d["id"] for d in data["deals"]}
            ids = [i for i in query.get("ids", [""])[0].split(",") if i in known]
            if ids:
                return benchmark.custom(data["deals"], ids)
            return data["benchmarks"].get(query.get("group", [""])[0])

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = self._target()
            if url is None or not self._allowed(url.path):
                return
            path = unquote(url.path)
            try:
                if path in ("/", "/index.html"):
                    self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8",
                               {"Content-Security-Policy": _PAGE_POLICY})
                elif path == "/api/dataset":
                    self._json(exports.public(app.get()))
                elif path == "/api/benchmark":
                    data = app.get()
                    known = {d["id"] for d in data["deals"]}
                    ids = [i for i in parse_qs(url.query).get("ids", [""])[0].split(",") if i in known]
                    self._json(benchmark.benchmark(data["deals"], ids))
                elif path.startswith("/pdf/"):
                    self._pdf(path[len("/pdf/"):])
                elif path == "/export/report.html":
                    body = exports.static_html(app.get()).encode("utf-8")
                    self._send(200, body, "text/html; charset=utf-8", {"Content-Disposition": 'attachment; filename="term_sheet_benchmark.html"'})
                elif path.startswith("/export/") and path[len("/export/"):] in exports.CSV_EXPORTS:
                    name = path[len("/export/"):]
                    data = app.get()
                    body = exports.CSV_EXPORTS[name](data, self._bench(data, parse_qs(url.query))).encode("utf-8")
                    self._send(200, body, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{name}"'})
                else:
                    self._error(HTTPStatus.NOT_FOUND, "Not found")
            except ConnectionError:
                pass  # the tab was closed while the response was being written
            except Exception as exc:  # report the failure to the page instead of dropping the connection
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        def do_POST(self):
            url = self._target()
            if url is None or not self._allowed(url.path):
                return
            if url.path != "/api/refresh":
                self._error(HTTPStatus.NOT_FOUND, "Not found")
                return
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{self.headers.get('Host')}":
                self._error(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
                return
            try:
                self._json(exports.public(app.build()))
            except ConnectionError:
                pass
            except Exception as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        def _pdf(self, deal_id: str):
            # Only files the scan found are served, looked up by id: the request never supplies a path.
            deal = next((d for d in app.get()["deals"] if d["id"] == deal_id), None)
            if deal is None:
                self._error(HTTPStatus.NOT_FOUND, "Unknown term sheet")
                return
            path = Path(deal["path"])
            if not path.is_file():
                self._error(HTTPStatus.NOT_FOUND, "The PDF is no longer in the folder")
                return
            # headers are Latin-1 at best: an ASCII stand-in, plus the real name in its percent-encoded form
            plain = "".join(c if c.isascii() and (c.isalnum() or c in " ._-") else "_" for c in path.name)
            self._send(200, path.read_bytes(), "application/pdf",
                       {"Content-Disposition": f"inline; filename=\"{plain}\"; filename*=UTF-8''{quote(path.name)}"})

    return Handler


class _Server(ThreadingHTTPServer):
    # http.server asks for SO_REUSEADDR. On Windows that lets a second process bind a port that is already
    # being served, and the browser then reaches whichever copy started first. Bind exclusively there, so
    # that a second copy of the tool moves on to the next port instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(app: App, port: int) -> ThreadingHTTPServer:
    """Bind the first free port at or after ``port`` on the loopback interface."""
    last: OSError | None = None
    for candidate in range(port, port + 20):
        try:
            return _Server(("127.0.0.1", candidate), make_handler(app))
        except OSError as exc:
            last = exc
    raise OSError(f"No free port between {port} and {port + 19}: {last}")
