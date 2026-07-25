import importlib.util
import json
import os
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from jsonschema import ValidationError


MODULE_PATH = pathlib.Path(__file__).with_name("hermes_operations_audit.py")
SPEC = importlib.util.spec_from_file_location("hermes_operations_audit", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ContractValidationTests(unittest.TestCase):
    def test_schema_rejects_surface_without_expected_profile(self):
        contract = {
            "$schema": "schema.json",
            "schema_version": 1,
            "freshness": {"max_age_seconds": 900},
            "surfaces": [
                {
                    "id": "discord",
                    "purpose": "safe remote entry",
                    "source_of_truth": ["home/modules/ai/hermes.nix"],
                    "unit": {"name": "hermes-discord.service", "scope": "user"},
                    "platform": "discord",
                    "default_profile": "default",
                    "forbidden_toolsets": ["terminal"],
                }
            ],
        }
        schema = {
            "type": "object",
            "properties": {
                "surfaces": {
                    "type": "array",
                    "items": {"type": "object", "required": ["expected_profile"]},
                }
            },
        }

        with self.assertRaises(ValidationError):
            audit.validate_contract(contract, schema)

    def test_rejects_duplicate_surface_ids(self):
        surface = {
            "id": "discord",
            "purpose": "safe remote entry",
            "source_of_truth": ["home/modules/ai/hermes.nix"],
            "unit": {"name": "hermes-discord.service", "scope": "user"},
            "platform": "discord",
            "expected_profile": "discord-safe",
            "default_profile": "default",
            "forbidden_toolsets": ["terminal"],
        }
        contract = {
            "$schema": "schema.json",
            "schema_version": 1,
            "freshness": {"max_age_seconds": 900},
            "surfaces": [surface, dict(surface)],
        }

        with self.assertRaisesRegex(ValueError, "duplicate surface id: discord"):
            audit.validate_contract(contract, {})


class ToolsetParsingTests(unittest.TestCase):
    def test_extracts_only_enabled_builtin_toolset_names(self):
        output = """Built-in toolsets (discord):
  ✓ enabled  web  Web Search
  ✓ enabled  terminal  Terminal
  ✗ disabled  video  Video
  ✓ enabled  code_execution  Code Execution

MCP servers:
  knowledge  all tools enabled
"""

        self.assertEqual(
            audit.parse_enabled_toolsets(output),
            ["code_execution", "terminal", "web"],
        )

    def test_rejects_unrecognized_or_empty_toolset_output(self):
        for output in ("", "Built-in toolsets (discord):\n  format changed"):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, "toolset status"):
                    audit.parse_enabled_toolsets(output)

    def test_requires_status_for_every_contracted_forbidden_toolset(self):
        output = """Built-in toolsets (discord):
  ✓ enabled  web  Web Search
  ✗ disabled  terminal  Terminal
"""

        with self.assertRaisesRegex(ValueError, "missing toolset status: file"):
            audit.parse_enabled_toolsets(
                output,
                required_toolsets={"file", "terminal"},
            )


class ProfileDetectionTests(unittest.TestCase):
    def test_explicit_profile_argument_takes_precedence(self):
        profile = audit.profile_from_process(
            ["hermes", "gateway", "run", "--profile", "discord-safe"],
            {"HERMES_PROFILE": "other"},
            "default",
        )

        self.assertEqual(profile, "discord-safe")

    def test_short_profile_argument_is_recognized(self):
        profile = audit.profile_from_process(
            ["hermes", "-p", "discord-safe", "gateway", "run"],
            {},
            "default",
        )

        self.assertEqual(profile, "discord-safe")

    def test_uses_profile_environment_when_argument_is_absent(self):
        profile = audit.profile_from_process(
            ["hermes", "gateway", "run"],
            {"HERMES_PROFILE": "discord-safe"},
            "default",
        )

        self.assertEqual(profile, "discord-safe")

    def test_uses_declared_default_when_no_override_exists(self):
        profile = audit.profile_from_process(
            ["hermes", "gateway", "run", "--replace"],
            {},
            "default",
        )

        self.assertEqual(profile, "default")


class SurfaceEvaluationTests(unittest.TestCase):
    def test_reports_profile_and_forbidden_toolset_drift(self):
        surface = {
            "id": "discord",
            "purpose": "safe remote entry",
            "source_of_truth": ["home/modules/ai/hermes.nix"],
            "expected_profile": "discord-safe",
            "forbidden_toolsets": ["terminal", "file", "cronjob"],
        }
        observed = {
            "unit_state": "active (running)",
            "profile": "default",
            "enabled_toolsets": ["file", "terminal", "web"],
        }

        result = audit.evaluate_surface(surface, observed)

        self.assertEqual(result["status"], "drift")
        self.assertEqual(
            [finding["rule_id"] for finding in result["findings"]],
            ["HERMES-SURFACE-01", "HERMES-CAP-02"],
        )
        self.assertEqual(
            result["findings"][1]["evidence"],
            ["forbidden enabled toolsets: file, terminal"],
        )

    def test_reports_unobserved_without_inventing_profile_drift(self):
        surface = {
            "id": "discord",
            "purpose": "safe remote entry",
            "source_of_truth": ["home/modules/ai/hermes.nix"],
            "expected_profile": "discord-safe",
            "forbidden_toolsets": ["terminal"],
        }

        result = audit.evaluate_surface(
            surface,
            {"unit_state": None, "profile": None, "enabled_toolsets": []},
        )

        self.assertEqual(result["status"], "unobserved")
        self.assertEqual(
            [finding["rule_id"] for finding in result["findings"]],
            ["HERMES-GW-01"],
        )


class LiveProbeTests(unittest.TestCase):
    def test_probes_unit_process_and_effective_profile_toolsets(self):
        commands = []

        def run_command(command):
            commands.append(command)
            if command[0] == "systemctl":
                return "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42\n"
            return "  ✓ enabled  web  Web\n  ✓ enabled  terminal  Terminal\n"

        def read_process(pid):
            self.assertEqual(pid, 42)
            return ["hermes", "gateway", "run", "--replace"], {}

        observed = audit.probe_surface(
            {
                "unit": {"name": "hermes-discord.service", "scope": "user"},
                "platform": "discord",
                "default_profile": "default",
                "forbidden_toolsets": ["terminal"],
            },
            run_command=run_command,
            read_process=read_process,
        )

        self.assertEqual(
            observed,
            {
                "unit_state": "active (running)",
                "profile": "default",
                "enabled_toolsets": ["terminal", "web"],
            },
        )
        self.assertEqual(
            commands[1],
            ["hermes", "--profile", "default", "tools", "list", "--platform", "discord"],
        )

    def test_probe_failure_becomes_unobserved(self):
        def fail(_command):
            raise OSError("systemd unavailable")

        observed = audit.probe_surface(
            {
                "unit": {"name": "hermes-discord.service", "scope": "user"},
                "platform": "discord",
                "default_profile": "default",
            },
            run_command=fail,
        )

        self.assertEqual(
            observed,
            {"unit_state": None, "profile": None, "enabled_toolsets": []},
        )


class ReportTests(unittest.TestCase):
    def test_builds_schema_valid_drift_report(self):
        contract = {
            "schema_version": 1,
            "freshness": {"max_age_seconds": 900},
            "surfaces": [
                {
                    "id": "discord",
                    "purpose": "safe remote entry",
                    "source_of_truth": ["home/modules/ai/hermes.nix"],
                    "expected_profile": "discord-safe",
                    "forbidden_toolsets": ["terminal"],
                }
            ],
        }
        report = audit.build_report(
            contract,
            {
                "discord": {
                    "unit_state": "active (running)",
                    "profile": "default",
                    "enabled_toolsets": ["terminal", "web"],
                }
            },
            "2026-07-25T12:00:00+00:00",
        )
        schema = json.loads(
            (
                MODULE_PATH.parent.parent
                / "docs/schema/hermes-operations-audit.schema.json"
            ).read_text()
        )

        audit.validate_report(report, schema)
        self.assertEqual(report["overall_status"], "drift")
        self.assertEqual(report["summary"]["drift"], 1)
        self.assertEqual(report["summary"]["high"], 2)
        self.assertEqual(report["freshness"]["status"], "fresh")

    def test_rejects_semantically_inconsistent_report(self):
        contract = {
            "freshness": {"max_age_seconds": 900},
            "surfaces": [
                {
                    "id": "discord",
                    "purpose": "safe remote entry",
                    "source_of_truth": ["home/modules/ai/hermes.nix"],
                    "expected_profile": "discord-safe",
                    "forbidden_toolsets": ["terminal"],
                }
            ],
        }
        report = audit.build_report(
            contract,
            {
                "discord": {
                    "unit_state": "active (running)",
                    "profile": "default",
                    "enabled_toolsets": ["terminal"],
                }
            },
            "2026-07-25T12:00:00+00:00",
        )
        schema = json.loads(
            (
                MODULE_PATH.parent.parent
                / "docs/schema/hermes-operations-audit.schema.json"
            ).read_text()
        )
        inconsistent_reports = []
        for mutate in (
            lambda value: value["summary"].__setitem__("high", 0),
            lambda value: value.__setitem__("findings", []),
            lambda value: value["surfaces"][0].__setitem__("status", "healthy"),
        ):
            value = json.loads(json.dumps(report))
            mutate(value)
            inconsistent_reports.append(value)

        for value in inconsistent_reports:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "inconsistent audit report"):
                    audit.validate_report(value, schema)

    def test_marks_report_stale_at_read_time_without_mutating_source(self):
        report = {
            "observed_at": "2026-07-25T12:00:00+00:00",
            "overall_status": "drift",
            "freshness": {
                "status": "fresh",
                "age_seconds": 0,
                "max_age_seconds": 900,
            },
        }

        decorated = audit.decorate_freshness(
            report,
            datetime(2026, 7, 25, 12, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(decorated["overall_status"], "stale")
        self.assertEqual(decorated["freshness"], {
            "status": "stale",
            "age_seconds": 1200,
            "max_age_seconds": 900,
        })
        self.assertEqual(report["freshness"]["status"], "fresh")

    def test_marks_future_observation_stale(self):
        report = {
            "observed_at": "2026-07-25T12:05:00+00:00",
            "overall_status": "healthy",
            "freshness": {
                "status": "fresh",
                "age_seconds": 0,
                "max_age_seconds": 900,
            },
        }

        decorated = audit.decorate_freshness(
            report,
            datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(decorated["overall_status"], "stale")
        self.assertEqual(decorated["freshness"], {
            "status": "stale",
            "age_seconds": 0,
            "max_age_seconds": 900,
        })

    def test_marks_subsecond_future_observation_stale(self):
        report = {
            "observed_at": "2026-07-25T12:00:00.500000+00:00",
            "overall_status": "healthy",
            "freshness": {
                "status": "fresh",
                "age_seconds": 0,
                "max_age_seconds": 900,
            },
        }

        decorated = audit.decorate_freshness(
            report,
            datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(decorated["overall_status"], "stale")

    def test_writes_private_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "audit-result.json"

            audit.write_json_atomic(output, {"status": "drift"})

            self.assertEqual(json.loads(output.read_text()), {"status": "drift"})
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)

    def test_audit_once_validates_and_writes_live_report(self):
        root = MODULE_PATH.parent.parent
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "audit-result.json"

            report = audit.audit_once(
                contract_path=root / "docs/hermes-operations-contract.json",
                contract_schema_path=root
                / "docs/schema/hermes-operations-contract.schema.json",
                report_schema_path=root
                / "docs/schema/hermes-operations-audit.schema.json",
                output_path=output,
                probe=lambda _surface: {
                    "unit_state": "active (running)",
                    "profile": "default",
                    "enabled_toolsets": ["terminal", "web"],
                },
                now=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(report["overall_status"], "drift")
            self.assertEqual(json.loads(output.read_text()), report)

    def test_api_reader_recomputes_and_validates_freshness(self):
        root = MODULE_PATH.parent.parent
        contract = {
            "freshness": {"max_age_seconds": 900},
            "surfaces": [
                {
                    "id": "discord",
                    "purpose": "safe remote entry",
                    "source_of_truth": ["home/modules/ai/hermes.nix"],
                    "expected_profile": "discord-safe",
                    "forbidden_toolsets": [],
                }
            ],
        }
        report = audit.build_report(
            contract,
            {
                "discord": {
                    "unit_state": "active (running)",
                    "profile": "discord-safe",
                    "enabled_toolsets": ["web"],
                }
            },
            "2026-07-25T12:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            result_path = pathlib.Path(directory) / "audit-result.json"
            result_path.write_text(json.dumps(report))

            decorated = audit.read_report_for_api(
                result_path,
                root / "docs/schema/hermes-operations-audit.schema.json",
                datetime(2026, 7, 25, 12, 20, tzinfo=timezone.utc),
            )

        self.assertEqual(decorated["overall_status"], "stale")
        self.assertEqual(decorated["freshness"]["age_seconds"], 1200)


class ApiServerTests(unittest.TestCase):
    def test_serves_only_schema_valid_audit_json(self):
        root = MODULE_PATH.parent.parent
        report = audit.build_report(
            {
                "freshness": {"max_age_seconds": 900},
                "surfaces": [
                    {
                        "id": "discord",
                        "purpose": "safe remote entry",
                        "source_of_truth": ["home/modules/ai/hermes.nix"],
                        "expected_profile": "discord-safe",
                        "forbidden_toolsets": [],
                    }
                ],
            },
            {
                "discord": {
                    "unit_state": "active (running)",
                    "profile": "discord-safe",
                    "enabled_toolsets": ["web"],
                }
            },
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with tempfile.TemporaryDirectory() as directory:
            result_path = pathlib.Path(directory) / "audit-result.json"
            result_path.write_text(json.dumps(report))
            handler = audit.make_api_handler(
                result_path,
                root / "docs/schema/hermes-operations-audit.schema.json",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/audit",
                    timeout=5,
                ) as response:
                    payload = json.load(response)
                    cache_control = response.headers["Cache-Control"]
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(cache_control, "no-store")

    def test_schema_invalid_report_returns_service_unavailable(self):
        root = MODULE_PATH.parent.parent
        with tempfile.TemporaryDirectory() as directory:
            result_path = pathlib.Path(directory) / "audit-result.json"
            result_path.write_text(json.dumps({"schema_version": 1}))
            handler = audit.make_api_handler(
                result_path,
                root / "docs/schema/hermes-operations-audit.schema.json",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/audit",
                        timeout=5,
                    )
                caught.exception.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(caught.exception.code, 503)


class CliTests(unittest.TestCase):
    def test_audit_exit_status_distinguishes_gate_from_periodic_publish(self):
        with patch.object(
            audit,
            "audit_once",
            return_value={
                "overall_status": "drift",
                "summary": {"high": 1, "medium": 0},
            },
        ):
            gate_status = audit.main(["audit"])
            periodic_status = audit.main(["audit", "--allow-drift"])

        self.assertEqual(gate_status, 1)
        self.assertEqual(periodic_status, 0)


class HomeManagerContractTests(unittest.TestCase):
    def test_module_wires_private_periodic_audit_and_loopback_dashboard(self):
        root = MODULE_PATH.parent.parent
        module = (root / "home/modules/ai/hermes-operations-dashboard.nix").read_text()
        glance = (root / "home/modules/ai/hermes-operations-glance.yml").read_text()
        home = (root / "home/home.nix").read_text()

        for fragment in (
            'StateDirectory = "hermes-operations";',
            'StateDirectoryMode = "0700";',
            'OnCalendar = "*:0/5";',
            "--allow-drift",
            "--host 127.0.0.1 --port 8791",
            'Restart = "always";',
        ):
            self.assertIn(fragment, module)
        self.assertIn("http://127.0.0.1:8791/api/audit", glance)
        self.assertIn("host: 127.0.0.1", glance)
        self.assertIn("port: 8790", glance)
        self.assertNotIn("docker.sock", module + glance)
        self.assertIn("./modules/ai/hermes-operations-dashboard.nix", home)

    def test_audit_unit_can_read_the_gateway_process_environment(self):
        root = MODULE_PATH.parent.parent
        module = (root / "home/modules/ai/hermes-operations-dashboard.nix").read_text()
        audit_service = module[
            module.index("systemd.user.services.hermes-operations-audit =") :
            module.index("systemd.user.timers.hermes-operations-audit =")
        ]

        self.assertNotIn("PrivateTmp = true;", audit_service)

    def test_nixos_exposes_glance_only_through_tailscale_serve(self):
        root = MODULE_PATH.parent.parent
        networking = (root / "nixos/modules/system/networking.nix").read_text()

        self.assertIn("hermes-operations-tailscale-serve = {", networking)
        self.assertIn("ExecStartPre = waitForTailscaled;", networking)
        self.assertIn(
            "tailscale serve --bg --yes --https=8450 http://127.0.0.1:8790",
            networking,
        )
        self.assertIn("tailscale serve --yes --https=8450 off", networking)


if __name__ == "__main__":
    unittest.main()
