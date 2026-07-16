#!/usr/bin/env python3
"""Hermetic behavior tests for the Transit MCP server.

These tests never touch the network and never fabricate external Transit API
data: the one path-construction test intercepts the internal request helper to
capture the URL that *would* be issued, and every other test exercises pure
validation/normalization logic that returns before any request is attempted.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "home"
    / "modules"
    / "ai"
    / "transit-mcp-server.py"
)


def _install_fake_mcp() -> None:
    """Stub `mcp.server.fastmcp.FastMCP` so the module imports without the
    real dependency and without registering a live server. `tool()` becomes an
    identity decorator, leaving the tool functions callable as plain functions.
    """

    class _FakeFastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def run(self, *args, **kwargs):  # pragma: no cover - never called here
            raise AssertionError("run() must not be invoked in tests")

    mcp_pkg = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
    mcp_fastmcp.FastMCP = _FakeFastMCP
    sys.modules.setdefault("mcp", mcp_pkg)
    sys.modules.setdefault("mcp.server", mcp_server)
    sys.modules.setdefault("mcp.server.fastmcp", mcp_fastmcp)


def _load_module():
    _install_fake_mcp()
    spec = importlib.util.spec_from_file_location("transit_mcp_server", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transit = _load_module()


class DeparturesPathTests(unittest.TestCase):
    def test_station_id_is_percent_encoded_in_path(self):
        captured = {}

        def fake_api_request(path, parameters):
            captured["path"] = path
            captured["parameters"] = parameters
            return {"stationId": "odpt:JR/1", "date": None, "timezone": None, "departures": []}

        original = transit._api_request
        transit._api_request = fake_api_request
        try:
            result = transit.transit_departures("odpt:JR/1?a", limit=3)
        finally:
            transit._api_request = original

        # ':' '/' and '?' must be encoded so they cannot inject extra path
        # segments or a query string against the Transit API host.
        self.assertEqual(captured["path"], "/stations/odpt%3AJR%2F1%3Fa/departures")
        self.assertFalse(result["writes_performed"])

    def test_empty_station_id_is_rejected_before_any_request(self):
        sentinel = "the request helper must not run for invalid input"

        def fail_api_request(path, parameters):  # pragma: no cover - must not run
            raise AssertionError(sentinel)

        original = transit._api_request
        transit._api_request = fail_api_request
        try:
            result = transit.transit_departures("   ")
        finally:
            transit._api_request = original

        self.assertIn("error", result)


class ValidationTests(unittest.TestCase):
    def test_search_places_rejects_empty_query(self):
        result = transit.transit_search_places("")
        self.assertIn("error", result)

    def test_plan_rejects_unknown_search_type(self):
        result = transit.transit_plan("A", "B", search_type="sideways")
        self.assertIn("error", result)

    def test_plan_rejects_unknown_strategy(self):
        result = transit.transit_plan("A", "B", strategy="teleport")
        self.assertIn("error", result)


class HelperTests(unittest.TestCase):
    def test_text_collapses_whitespace_and_enforces_length(self):
        self.assertEqual(transit._text("  Tokyo   Station ", "q"), "Tokyo Station")
        self.assertIsNone(transit._text("   ", "q"))
        self.assertIsNone(transit._text("x" * 201, "q"))

    def test_limit_clamps_to_bounds(self):
        self.assertEqual(transit._limit(0), 1)
        self.assertEqual(transit._limit(99), transit.MAX_LIMIT)
        self.assertEqual(transit._limit(99, maximum=5), 5)


if __name__ == "__main__":
    unittest.main()
