"""Minimal static web server for the sample shop application.

Serves sample_app/public at http://localhost:3000 using only Python standard library.
Supports SAMPLE_BUGS=on|off via environment variable, runtime endpoint, or query parameter.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUBLIC_DIR = Path(__file__).resolve().parent / "public"


def get_bugs_setting() -> str:
    """Return 'on' or 'off' based on environment variable."""
    val = os.environ.get("SAMPLE_BUGS", "on").strip().lower()
    return "on" if val in ("on", "true", "1", "yes") else "off"


class SampleAppRequestHandler(SimpleHTTPRequestHandler):
    """Custom HTTP request handler serving static files and dynamic config."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def end_headers(self) -> None:
        """Add CORS and cache-control headers."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        """Route GET requests, injecting dynamic config when requested."""
        clean_path = self.path.split("?")[0]

        if clean_path in ("/api/config", "/config.json"):
            bugs_mode = get_bugs_setting()
            payload = json.dumps({"sample_bugs": bugs_mode}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if clean_path == "/config.js":
            bugs_mode = get_bugs_setting()
            payload = f'window.SERVER_SAMPLE_BUGS = "{bugs_mode}";\n'.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # Default root redirects or serves index.html
        if clean_path == "/" or clean_path == "":
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self) -> None:
        """Allow runtime toggle via POST /api/toggle-bugs."""
        clean_path = self.path.split("?")[0]
        if clean_path == "/api/toggle-bugs":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError:
                data = {}

            if "sample_bugs" in data:
                new_state = "on" if str(data["sample_bugs"]).lower() in ("on", "true", "1") else "off"
                os.environ["SAMPLE_BUGS"] = new_state
            else:
                current = get_bugs_setting()
                os.environ["SAMPLE_BUGS"] = "off" if current == "on" else "on"

            bugs_mode = get_bugs_setting()
            payload = json.dumps({"sample_bugs": bugs_mode}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def run_server(port: int = 3000) -> None:
    """Run the sample HTTP server on the specified port."""
    if not PUBLIC_DIR.exists():
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, SampleAppRequestHandler)
    print(f"Sample App running at http://localhost:{port}/ (SAMPLE_BUGS={get_bugs_setting()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down sample app server.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample Shop App Static Server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 3000)), help="Port to listen on")
    args = parser.parse_args()
    run_server(args.port)
