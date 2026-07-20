#!/usr/bin/env python3
"""Expose Noctalia lock state to local automation clients."""

from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    noctalia: Path

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.respond(200, {"ok": True})
            return
        if self.path != "/state":
            self.respond(404, {"error": "not found"})
            return

        result = subprocess.run(
            [str(self.noctalia), "ipc", "call", "state", "all"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.respond(503, {"error": "noctalia IPC failed"})
            return

        try:
            state = json.loads(result.stdout)
            locked = bool(state["state"]["lockScreenActive"])
        except (KeyError, TypeError, json.JSONDecodeError):
            self.respond(503, {"error": "invalid noctalia state"})
            return

        self.respond(200, {"lockScreenActive": locked})

    def log_message(self, format: str, *args: object) -> None:
        return

    def respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--noctalia", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18765, type=int)
    args = parser.parse_args()

    Handler.noctalia = args.noctalia
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
