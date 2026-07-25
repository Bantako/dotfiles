#!/usr/bin/env python3
"""Audit Hermes entry surfaces against a schema-validated operations contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

TOOLSET_STATUS_PATTERN = re.compile(
    r"^\s*(?:✓|✗)\s+(enabled|disabled)\s+([a-z][a-z0-9_]*)\b"
)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "docs" / "hermes-operations-contract.json"
DEFAULT_CONTRACT_SCHEMA = (
    ROOT / "docs" / "schema" / "hermes-operations-contract.schema.json"
)
DEFAULT_REPORT_SCHEMA = (
    ROOT / "docs" / "schema" / "hermes-operations-audit.schema.json"
)
DEFAULT_RESULT = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    / "hermes-operations"
    / "audit-result.json"
)


def validate_contract(contract: dict, schema: dict) -> None:
    """Validate a contract against its JSON Schema."""
    Draft202012Validator(schema).validate(contract)
    seen: set[str] = set()
    for surface in contract.get("surfaces", []):
        surface_id = surface["id"]
        if surface_id in seen:
            raise ValueError(f"duplicate surface id: {surface_id}")
        seen.add(surface_id)


def parse_enabled_toolsets(
    output: str,
    required_toolsets: set[str] | None = None,
) -> list[str]:
    """Extract enabled built-in toolset names from Hermes' human CLI output."""
    enabled: set[str] = set()
    recognized: set[str] = set()
    for line in _strip_ansi(output).splitlines():
        match = TOOLSET_STATUS_PATTERN.match(line)
        if not match:
            continue
        status, toolset = match.groups()
        recognized.add(toolset)
        if status == "enabled":
            enabled.add(toolset)
    if not recognized:
        raise ValueError("no recognizable toolset status lines")
    missing = sorted(set(required_toolsets or ()) - recognized)
    if missing:
        raise ValueError(f"missing toolset status: {', '.join(missing)}")
    return sorted(enabled)


def profile_from_process(
    argv: list[str], environment: dict[str, str], default_profile: str
) -> str:
    """Resolve Hermes' effective profile without retaining the raw environment."""
    for index, argument in enumerate(argv):
        if argument in {"--profile", "-p"} and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--profile="):
            return argument.split("=", 1)[1]
    return environment.get("HERMES_PROFILE") or default_profile


def evaluate_surface(surface: dict, observed: dict) -> dict:
    """Compare one allowlisted observation with its declared contract."""
    surface_id = surface["id"]
    findings = []
    expected_profile = surface["expected_profile"]
    observed_profile = observed.get("profile")
    unit_state = observed.get("unit_state")
    if unit_state is None:
        findings.append(
            {
                "rule_id": "HERMES-GW-01",
                "severity": "high",
                "surface_id": surface_id,
                "message": "Gateway surface could not be observed",
                "evidence": ["unit state: unobserved"],
            }
        )
    elif observed_profile != expected_profile:
        findings.append(
            {
                "rule_id": "HERMES-SURFACE-01",
                "severity": "high",
                "surface_id": surface_id,
                "message": "Observed profile does not match the contracted profile",
                "evidence": [
                    f"expected profile: {expected_profile}",
                    f"observed profile: {observed_profile or 'unobserved'}",
                ],
            }
        )

    forbidden = (
        []
        if unit_state is None
        else sorted(
            set(surface["forbidden_toolsets"])
            & set(observed.get("enabled_toolsets", []))
        )
    )
    if forbidden:
        findings.append(
            {
                "rule_id": "HERMES-CAP-02",
                "severity": "high",
                "surface_id": surface_id,
                "message": "Forbidden toolsets are enabled for this surface",
                "evidence": [f"forbidden enabled toolsets: {', '.join(forbidden)}"],
            }
        )

    return {
        "id": surface_id,
        "purpose": surface["purpose"],
        "status": (
            "unobserved" if unit_state is None else "drift" if findings else "healthy"
        ),
        "source_of_truth": list(surface["source_of_truth"]),
        "expected": {
            "profile": expected_profile,
            "forbidden_toolsets": sorted(surface["forbidden_toolsets"]),
        },
        "observed": {
            "unit_state": unit_state,
            "profile": observed_profile,
            "enabled_toolsets": sorted(observed.get("enabled_toolsets", [])),
        },
        "findings": findings,
    }


def run_command(command: list[str]) -> str:
    """Run a read-only probe and return its stdout."""
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    ).stdout


def read_process(pid: int) -> tuple[list[str], dict[str, str]]:
    """Read argv and only the profile selector from a live process."""
    process_dir = Path("/proc") / str(pid)
    argv = [
        item.decode(errors="replace")
        for item in (process_dir / "cmdline").read_bytes().split(b"\0")
        if item
    ]
    environment = {}
    for item in (process_dir / "environ").read_bytes().split(b"\0"):
        if item.startswith(b"HERMES_PROFILE="):
            environment["HERMES_PROFILE"] = item.split(b"=", 1)[1].decode(
                errors="replace"
            )
            break
    return argv, environment


def _probe_surface(
    surface: dict,
    *,
    run_command=run_command,
    read_process=read_process,
) -> dict:
    """Observe one gateway surface without returning raw process data."""
    unit = surface["unit"]
    command = ["systemctl"]
    if unit["scope"] == "user":
        command.append("--user")
    command.extend(
        [
            "show",
            unit["name"],
            "-p",
            "LoadState",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "--no-pager",
        ]
    )
    properties = dict(
        line.split("=", 1) for line in run_command(command).splitlines() if "=" in line
    )
    if properties.get("LoadState") != "loaded" or properties.get("ActiveState") != "active":
        return {"unit_state": None, "profile": None, "enabled_toolsets": []}

    pid = int(properties["MainPID"])
    if pid <= 0:
        return {"unit_state": None, "profile": None, "enabled_toolsets": []}
    argv, environment = read_process(pid)
    profile = profile_from_process(argv, environment, surface["default_profile"])
    tools_output = run_command(
        [
            "hermes",
            "--profile",
            profile,
            "tools",
            "list",
            "--platform",
            surface["platform"],
        ]
    )
    # Hermes 0.19 reloads this same profile config before every gateway turn and
    # includes enabled_toolsets in its AIAgent cache signature. A config change
    # therefore replaces the cached tool schema before the next turn.
    return {
        "unit_state": f"{properties['ActiveState']} ({properties['SubState']})",
        "profile": profile,
        "enabled_toolsets": parse_enabled_toolsets(
            tools_output,
            required_toolsets=set(surface["forbidden_toolsets"]),
        ),
    }


def probe_surface(
    surface: dict,
    *,
    run_command=run_command,
    read_process=read_process,
) -> dict:
    """Fail closed when any read-only observation step is unavailable."""
    try:
        return _probe_surface(
            surface,
            run_command=run_command,
            read_process=read_process,
        )
    except (KeyError, OSError, ValueError, subprocess.SubprocessError):
        return {"unit_state": None, "profile": None, "enabled_toolsets": []}


def build_report(contract: dict, observations: dict[str, dict], observed_at: str) -> dict:
    """Build one deterministic report from contract-ordered observations."""
    surfaces = [
        evaluate_surface(surface, observations[surface["id"]])
        for surface in contract["surfaces"]
    ]
    findings = [finding for surface in surfaces for finding in surface["findings"]]
    summary = {
        "healthy": sum(surface["status"] == "healthy" for surface in surfaces),
        "drift": sum(surface["status"] == "drift" for surface in surfaces),
        "unobserved": sum(surface["status"] == "unobserved" for surface in surfaces),
        "high": sum(finding["severity"] == "high" for finding in findings),
        "medium": sum(finding["severity"] == "medium" for finding in findings),
    }
    overall_status = (
        "drift"
        if summary["drift"]
        else "unobserved"
        if summary["unobserved"]
        else "healthy"
    )
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "overall_status": overall_status,
        "freshness": {
            "status": "fresh",
            "age_seconds": 0,
            "max_age_seconds": contract["freshness"]["max_age_seconds"],
        },
        "summary": summary,
        "surfaces": surfaces,
        "findings": findings,
    }


def validate_report(report: dict, schema: dict) -> None:
    """Validate report structure and cross-field semantic consistency."""
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)

    def reject(reason: str) -> None:
        raise ValueError(f"inconsistent audit report: {reason}")

    surfaces = report["surfaces"]
    if not surfaces:
        reject("no surfaces")
    surface_ids = [surface["id"] for surface in surfaces]
    if len(surface_ids) != len(set(surface_ids)):
        reject("duplicate surface id")

    flattened_findings = []
    for surface in surfaces:
        findings = surface["findings"]
        if any(finding["surface_id"] != surface["id"] for finding in findings):
            reject(f"finding assigned to wrong surface: {surface['id']}")
        expected_status = (
            "healthy"
            if not findings
            else "unobserved"
            if any(finding["rule_id"] == "HERMES-GW-01" for finding in findings)
            else "drift"
        )
        if surface["status"] != expected_status:
            reject(f"surface status: {surface['id']}")
        flattened_findings.extend(findings)

    if report["findings"] != flattened_findings:
        reject("root findings do not match surface findings")

    expected_summary = {
        "healthy": sum(surface["status"] == "healthy" for surface in surfaces),
        "drift": sum(surface["status"] == "drift" for surface in surfaces),
        "unobserved": sum(surface["status"] == "unobserved" for surface in surfaces),
        "high": sum(finding["severity"] == "high" for finding in flattened_findings),
        "medium": sum(finding["severity"] == "medium" for finding in flattened_findings),
    }
    if report["summary"] != expected_summary:
        reject("summary counts")

    freshness = report["freshness"]
    if (
        freshness["status"] == "fresh"
        and freshness["age_seconds"] > freshness["max_age_seconds"]
    ):
        reject("freshness age")
    expected_overall = (
        "stale"
        if freshness["status"] == "stale"
        else "drift"
        if expected_summary["drift"]
        else "unobserved"
        if expected_summary["unobserved"]
        else "healthy"
    )
    if report["overall_status"] != expected_overall:
        reject("overall status")


def decorate_freshness(report: dict, now: datetime) -> dict:
    """Recompute freshness at read time without changing the stored report."""
    decorated = deepcopy(report)
    observed_at = datetime.fromisoformat(decorated["observed_at"].replace("Z", "+00:00"))
    raw_age_seconds = (now - observed_at).total_seconds()
    age_seconds = max(0, int(raw_age_seconds))
    max_age_seconds = int(decorated["freshness"]["max_age_seconds"])
    stale = raw_age_seconds < 0 or age_seconds > max_age_seconds
    decorated["freshness"] = {
        "status": "stale" if stale else "fresh",
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
    }
    if stale:
        decorated["overall_status"] = "stale"
    return decorated


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write private JSON without exposing a partially written report."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_json(path: Path) -> dict:
    """Load a JSON object from a trusted declarative path."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _strip_ansi(value: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub("", value)


def audit_once(
    *,
    contract_path: Path,
    contract_schema_path: Path,
    report_schema_path: Path,
    output_path: Path,
    probe=probe_surface,
    now: datetime | None = None,
) -> dict:
    """Validate, observe, evaluate, validate output, and atomically publish."""
    contract = load_json(contract_path)
    validate_contract(contract, load_json(contract_schema_path))
    observations = {
        surface["id"]: probe(surface) for surface in contract["surfaces"]
    }
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )
    report = build_report(contract, observations, observed_at)
    validate_report(report, load_json(report_schema_path))
    write_json_atomic(output_path, report)
    return report


def read_report_for_api(
    result_path: Path,
    report_schema_path: Path,
    now: datetime | None = None,
) -> dict:
    """Read a stored report, recompute freshness, and validate the response."""
    report_schema = load_json(report_schema_path)
    stored_report = load_json(result_path)
    validate_report(stored_report, report_schema)
    report = decorate_freshness(stored_report, now or datetime.now(timezone.utc))
    validate_report(report, report_schema)
    return report


def make_api_handler(result_path: Path, report_schema_path: Path):
    """Create a narrow handler that exposes only health and audit JSON."""

    class AuditApiHandler(BaseHTTPRequestHandler):
        def send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path not in {"/api/audit", "/health"}:
                self.send_json(404, {"error": "not found"})
                return
            try:
                report = read_report_for_api(result_path, report_schema_path)
            except (OSError, ValueError, TypeError, KeyError, ValidationError):
                self.send_json(503, {"error": "audit report unavailable"})
                return
            if path == "/health":
                self.send_json(
                    200,
                    {
                        "status": "ok",
                        "audit_status": report["overall_status"],
                        "freshness": report["freshness"]["status"],
                    },
                )
                return
            self.send_json(200, report)

        def log_message(self, format: str, *args) -> None:
            return

    return AuditApiHandler


def serve_api(
    *,
    result_path: Path,
    report_schema_path: Path,
    host: str,
    port: int,
) -> None:
    """Serve the narrow read-only API until terminated."""
    handler = make_api_handler(result_path, report_schema_path)
    with ThreadingHTTPServer((host, port), handler) as server:
        server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    audit_parser.add_argument(
        "--contract-schema", type=Path, default=DEFAULT_CONTRACT_SCHEMA
    )
    audit_parser.add_argument(
        "--report-schema", type=Path, default=DEFAULT_REPORT_SCHEMA
    )
    audit_parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    audit_parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="publish findings but return success for a periodic timer",
    )

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    serve_parser.add_argument(
        "--report-schema", type=Path, default=DEFAULT_REPORT_SCHEMA
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8791)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            serve_api(
                result_path=args.result,
                report_schema_path=args.report_schema,
                host=args.host,
                port=args.port,
            )
            return 0

        report = audit_once(
            contract_path=args.contract,
            contract_schema_path=args.contract_schema,
            report_schema_path=args.report_schema,
            output_path=args.output,
        )
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2

    print(
        f"wrote {args.output}: status={report['overall_status']} "
        f"high={report['summary'].get('high', 0)} "
        f"medium={report['summary'].get('medium', 0)}"
    )
    if report["overall_status"] != "healthy" and not args.allow_drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
