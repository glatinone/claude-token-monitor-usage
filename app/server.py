"""
server.py – Minimal local HTTP server (127.0.0.1:9988).
---------------------------------------------------------
Endpoints:
  POST /api/usage  – Browser extension pushes usage data here.
  GET  /api/usage  – Anyone can poll current cached usage (JSON).
  OPTIONS *        – CORS preflight.

All requests are restricted to localhost only.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    storage_manager  = None
    update_callback  = None
    _latest: dict    = {}   # class-level cache for GET

    # ── Silence default request logging ───────────────────────────────────
    def log_message(self, fmt, *args):
        logger.debug(fmt % args)

    # ── CORS ──────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",          "https://claude.ai")
        self.send_header("Access-Control-Allow-Methods",         "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",         "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age",               "86400")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── GET /api/usage ────────────────────────────────────────────────────
    def do_GET(self):
        if self.path != "/api/usage":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(_Handler._latest or {}).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── POST /api/usage ───────────────────────────────────────────────────
    def do_POST(self):
        if self.path != "/api/usage":
            self.send_response(404)
            self.end_headers()
            return

        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)

        try:
            data = json.loads(raw_body)

            # Accept both old schema (remaining/limit) and new (used_count/limit)
            percentage = float(data.get("percentage", 0.0))
            limit      = float(data.get("limit", 0.0))
            reset_at   = data.get("reset_at", "")
            org_name   = data.get("org_name", "")

            # Derive remaining for StorageManager (legacy compat)
            # percentage is now remaining percentage (100 = fresh, 0 = exhausted)
            if "remaining" in data:
                remaining = float(data["remaining"])
            elif "used_count" in data:
                remaining = limit - float(data["used_count"])
            else:
                remaining = max(0.0, limit * (percentage / 100.0))

            # Persist via storage
            if _Handler.storage_manager:
                web_stats = _Handler.storage_manager.update_web_usage(
                    remaining, limit, percentage, reset_at
                )
                web_stats["org_name"] = org_name
            else:
                web_stats = data

            # Cache for GET endpoint
            _Handler._latest = data

            # Notify widget
            if _Handler.update_callback:
                _Handler.update_callback(web_stats=web_stats)

            resp = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        except Exception as e:
            logger.warning(f"POST /api/usage error: {e}")
            err = json.dumps({"status": "error", "message": str(e)}).encode()
            self.send_response(400)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)


def start_server(host: str, port: int, storage_manager, update_callback) -> HTTPServer:
    """Start the local HTTP server in a background daemon thread."""
    _Handler.storage_manager = storage_manager
    _Handler.update_callback = update_callback

    srv = HTTPServer((host, port), _Handler)
    t   = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    logger.info(f"Local API server listening on http://{host}:{port}")
    return srv
