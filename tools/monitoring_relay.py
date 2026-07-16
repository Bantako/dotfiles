#!/usr/bin/env python3
"""Authenticate Gatus alerts and forward normalized incidents to Hermes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 65_536
ALLOWED_SERVICES = frozenset(
    name.strip()
    for name in os.environ.get(
        "MONITOR_ALLOWED_SERVICES", "paperless,immich,radicale,miniflux,ntfy"
    ).split(",")
    if name.strip()
)


def _required_text(payload: dict[str, Any], key: str, limit: int = 1_024) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(key)
    return value.strip()


def _optional_truncated_text(payload: dict[str, Any], key: str, limit: int) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(key)
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def normalize_gatus_alert(payload: dict[str, Any]) -> dict[str, str]:
    """Allowlist Gatus fields before they become an agent-facing event."""
    raw_state = _required_text(payload, "event_type", 32).upper()
    states = {"TRIGGERED": "triggered", "RESOLVED": "resolved"}
    if raw_state not in states:
        raise ValueError("event_type")

    service = _required_text(payload, "service", 64)
    if service not in ALLOWED_SERVICES:
        raise ValueError("service")

    return {
        "event_type": "monitoring_incident",
        "state": states[raw_state],
        "source": "gatus",
        "service": service,
        "description": _required_text(payload, "description"),
        "errors": _optional_truncated_text(payload, "errors", 2_048),
        "url": _required_text(payload, "url"),
    }


def build_hermes_request(
    payload: dict[str, str], *, secret: str, timestamp: int | None = None
) -> tuple[bytes, dict[str, str]]:
    """Build Hermes generic webhook V2 headers over canonical JSON bytes."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signed_content = str(timestamp).encode("ascii") + b"." + body
    signature = hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Webhook-Signature-V2": signature,
        "X-Webhook-Timestamp": str(timestamp),
        "X-Request-ID": hashlib.sha256(body).hexdigest()[:32],
    }


class MonitoringRelayHandler(BaseHTTPRequestHandler):
    server_version = "HermesMonitoringRelay/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # Keep service logs limited to request metadata; never write secrets or bodies.
        print("%s - %s" % (self.address_string(), format % args), flush=True)

    def _respond(self, status: int, message: str) -> None:
        body = json.dumps({"status": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, "ok")
        else:
            self._respond(404, "not_found")

    def do_POST(self) -> None:
        if self.path != "/gatus":
            self._respond(404, "not_found")
            return

        expected_token = os.environ["MONITOR_RELAY_TOKEN"]
        if not hmac.compare_digest(self.headers.get("X-Monitor-Token", ""), expected_token):
            self._respond(401, "unauthorized")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, "invalid_content_length")
            return
        if not 0 < content_length <= MAX_BODY_BYTES:
            self._respond(413, "payload_too_large")
            return

        try:
            parsed = json.loads(self.rfile.read(content_length))
            if not isinstance(parsed, dict):
                raise ValueError("payload")
            incident = normalize_gatus_alert(parsed)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._respond(400, f"invalid_{error}")
            return

        body, headers = build_hermes_request(
            incident, secret=os.environ["HERMES_WEBHOOK_SECRET"]
        )
        request = Request(os.environ["HERMES_WEBHOOK_URL"], data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError):
            self._respond(502, "hermes_unavailable")
            return
        self._respond(202, "forwarded")


def main() -> None:
    host = os.environ.get("MONITOR_RELAY_HOST", "0.0.0.0")
    port = int(os.environ.get("MONITOR_RELAY_PORT", "8643"))
    required = ("MONITOR_RELAY_TOKEN", "HERMES_WEBHOOK_SECRET", "HERMES_WEBHOOK_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing required environment: {', '.join(missing)}")
    ThreadingHTTPServer((host, port), MonitoringRelayHandler).serve_forever()


if __name__ == "__main__":
    main()
