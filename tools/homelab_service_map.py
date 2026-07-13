#!/usr/bin/env python3
"""Generate a current homelab service map from the NAS and ser7 systemd."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "docs" / "homelab-service-map.json"
DEFAULT_OUTPUT = ROOT / "docs" / "homelab-service-map.md"


def parse_compose_inventory(output: str) -> dict[str, list[str]]:
    """Group Docker inspect label output by Compose project."""
    projects: dict[str, list[str]] = defaultdict(list)
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        labels = dict(
            field.split("=", 1)
            for field in fields[1:]
            if "=" in field
        )
        project = labels.get("project")
        service = labels.get("service")
        if not project or not service or project == "<no value>" or service == "<no value>":
            continue
        projects[project].append(service)
    return {project: sorted(services) for project, services in sorted(projects.items())}


def parse_docker_inspect(output: str) -> dict[str, list[str]]:
    """Group Docker inspect JSON by Compose project."""
    projects: dict[str, list[str]] = defaultdict(list)
    for item in json.loads(output):
        labels = item.get("Config", {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if project and service:
            projects[project].append(service)
    return {project: sorted(services) for project, services in sorted(projects.items())}


def run(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout


def probe_nas() -> tuple[dict[str, list[str]], str | None]:
    command = [
        "ssh",
        "nas",
        "docker inspect $(docker ps -q)",
    ]
    try:
        return parse_docker_inspect(run(command)), None
    except (OSError, subprocess.CalledProcessError) as error:
        return {}, str(error)


def probe_systemd(units: dict[str, dict[str, str]]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for unit, metadata in units.items():
        scope = metadata.get("scope", "system")
        command = ["systemctl"]
        if scope == "user":
            command.append("--user")
        command.extend(["show", unit, "-p", "ActiveState", "-p", "SubState", "--value"])
        try:
            active, sub = run(command).splitlines()[:2]
            observed[unit] = f"{active} ({sub})"
        except (OSError, subprocess.CalledProcessError, ValueError):
            observed[unit] = "未観測"
    return observed


def render_markdown(
    manifest: dict,
    observed_nas: dict[str, list[str]],
    observed_ser7: dict[str, str],
    generated_at: str,
) -> str:
    lines = [
        "# Homelab サービスマップ",
        "",
        "> このファイルは `tools/homelab_service_map.py` が生成する現在の運用地図。",
        "> 目的・責務・変更時の確認は `docs/homelab-service-map.json` で管理し、稼働状態は生成時に取得する。",
        "",
        f"- 生成日時: {generated_at}",
        "- 状態の意味: `稼働` は今回の観測結果、`未観測` は停止ではなく取得できなかった状態を表す。",
        "",
    ]

    nas_by_layer: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for project, metadata in manifest.get("nas", {}).items():
        nas_by_layer[metadata["layer"]].append((project, metadata))

    lines.extend(["## NAS Docker", ""])
    for layer in manifest.get("nas_layers", sorted(nas_by_layer)):
        entries = nas_by_layer.get(layer, [])
        if not entries:
            continue
        lines.extend([f"### {layer}", "", "| プロジェクト | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |", "|---|---|---|---|---|---|"])
        for project, metadata in sorted(entries):
            services = observed_nas.get(project)
            state = f"稼働: {', '.join(services)}" if services else "未観測"
            lines.append(
                "| {project} | {state} | {purpose} | {source} | {observe} | {change_check} |".format(
                    project=project,
                    state=state,
                    **metadata,
                )
            )
        lines.append("")

    lines.extend(["## ser7 の自動化・判断層", "", "| Unit | 現在の状態 | 目的 | 管理場所 | 観測 | 変更時に確認 |", "|---|---|---|---|---|---|"])
    for unit, metadata in manifest.get("ser7", {}).items():
        lines.append(
            "| {unit} | {state} | {purpose} | {source} | {observe} | {change_check} |".format(
                unit=unit,
                state=observed_ser7.get(unit, "未観測"),
                **metadata,
            )
        )

    lines.extend(
        [
            "",
            "## 更新ルール",
            "",
            "1. NAS Composeやser7のunitを追加・削除・役割変更したら、まず `docs/homelab-service-map.json` の目的・責務・確認項目を更新する。",
            "2. その後 `python3 tools/homelab_service_map.py` を実行し、観測結果をこのファイルへ反映する。",
            "3. 生成結果の差分を読み、意図しない停止・未観測・責務の重複がないか確認する。",
            "4. 秘密値、API token、`.env` の内容はこの地図へ書かない。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-live", action="store_true", help="render metadata without probing hosts")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    if args.skip_live:
        observed_nas: dict[str, list[str]] = {}
        observed_ser7: dict[str, str] = {}
    else:
        observed_nas, nas_error = probe_nas()
        observed_ser7 = probe_systemd(manifest.get("ser7", {}))
        if nas_error:
            print(f"warning: NAS inventory unavailable: {nas_error}")

    generated_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    args.output.write_text(render_markdown(manifest, observed_nas, observed_ser7, generated_at).rstrip() + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
