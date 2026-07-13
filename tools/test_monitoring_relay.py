#!/usr/bin/env python3
"""Behavior tests for the homelab monitoring relay."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("monitoring_relay.py")
SPEC = importlib.util.spec_from_file_location("monitoring_relay", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


class NormalizeAlertTests(unittest.TestCase):
    def test_allows_only_known_gatus_alert_fields(self):
        normalized = relay.normalize_gatus_alert(
            {
                "event_type": "TRIGGERED",
                "service": "paperless",
                "description": "HTTP health check failed",
                "errors": "[STATUS] == 200: false",
                "url": "http://192.168.11.9:8010/",
                "untrusted": "ignore me",
            }
        )

        self.assertEqual(
            normalized,
            {
                "event_type": "monitoring_incident",
                "state": "triggered",
                "source": "gatus",
                "service": "paperless",
                "description": "HTTP health check failed",
                "errors": "[STATUS] == 200: false",
                "url": "http://192.168.11.9:8010/",
            },
        )

    def test_rejects_unknown_service_and_invalid_state(self):
        with self.assertRaisesRegex(ValueError, "service"):
            relay.normalize_gatus_alert(
                {
                    "event_type": "TRIGGERED",
                    "service": "shell-command",
                    "description": "bad",
                    "errors": "bad",
                    "url": "http://example.invalid",
                }
            )

        with self.assertRaisesRegex(ValueError, "event_type"):
            relay.normalize_gatus_alert(
                {
                    "event_type": "arbitrary",
                    "service": "ntfy",
                    "description": "bad",
                    "errors": "bad",
                    "url": "http://example.invalid",
                }
            )

    def test_truncates_large_gatus_error_before_forwarding(self):
        normalized = relay.normalize_gatus_alert(
            {
                "event_type": "TRIGGERED",
                "service": "ntfy",
                "description": "HTTP health check failed",
                "errors": "x" * 10_000,
                "url": "http://192.168.11.9:8080/v1/health",
            }
        )

        self.assertEqual(len(normalized["errors"]), 2_048)
        self.assertTrue(normalized["errors"].endswith("…"))


class HermesRequestTests(unittest.TestCase):
    def test_signs_canonical_payload_using_webhook_v2(self):
        body, headers = relay.build_hermes_request(
            {
                "event_type": "monitoring_incident",
                "state": "triggered",
                "source": "gatus",
                "service": "ntfy",
                "description": "HTTP health check failed",
                "errors": "status 503",
                "url": "http://192.168.11.9:8080/v1/health",
            },
            secret="test-secret",
            timestamp=1_700_000_000,
        )

        self.assertEqual(json.loads(body), {"event_type": "monitoring_incident", "state": "triggered", "source": "gatus", "service": "ntfy", "description": "HTTP health check failed", "errors": "status 503", "url": "http://192.168.11.9:8080/v1/health"})
        expected = hmac.new(
            b"test-secret",
            b"1700000000." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers["X-Webhook-Signature-V2"], expected)
        self.assertEqual(headers["X-Webhook-Timestamp"], "1700000000")
        self.assertEqual(headers["Content-Type"], "application/json")


if __name__ == "__main__":
    unittest.main()
