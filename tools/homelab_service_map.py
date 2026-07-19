#!/usr/bin/env python3
"""Generate a current homelab service map from the NAS and ser7 systemd."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "docs" / "homelab-service-map.json"
DEFAULT_OUTPUT = ROOT / "docs" / "homelab-service-map.md"


def validate_manifest(manifest: dict) -> None:
    """Validate the metadata required to render the service map."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")

    common_fields = ("purpose", "source", "observe", "change_check")
    for section in ("nas", "ser7"):
        entries = manifest.get(section)
        if not isinstance(entries, dict):
            raise ValueError(f"manifest.{section} must be a JSON object")
        required_fields = ("layer", *common_fields) if section == "nas" else common_fields
        for name, metadata in entries.items():
            if not isinstance(metadata, dict):
                raise ValueError(f"manifest.{section}.{name} must be a JSON object")
            for field in required_fields:
                value = metadata.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"missing or empty manifest field: {section}.{name}.{field}")


def parse_docker_inspect(output: str) -> dict[str, list[tuple[str, str]]]:
    """Group Docker inspect JSON by Compose project."""
    projects: dict[str, list[tuple[str, str]]] = defaultdict(list)
    payload = json.loads(output)
    if not isinstance(payload, list):
        raise ValueError("Docker inspect output must be a JSON array")
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Docker inspect items must be JSON objects")
        labels = item.get("Config", {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if project and service:
            state = item.get("State", {}).get("Status", "unknown")
            projects[project].append((service, state))
    return {project: sorted(services) for project, services in sorted(projects.items())}


def run(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout


def probe_nas() -> tuple[dict[str, list[tuple[str, str]]], str | None]:
    command = [
        "ssh",
        "nas",
        "ids=$(docker ps -aq); if [ -n \"$ids\" ]; then docker inspect $ids; else printf '[]'; fi",
    ]
    try:
        return parse_docker_inspect(run(command)), None
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        return {}, str(error)


def probe_systemd(units: dict[str, dict[str, str]]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for unit, metadata in units.items():
        scope = metadata.get("scope", "system")
        command = ["systemctl"]
        if scope == "user":
            command.append("--user")
        command.extend(
            ["show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "LoadState"]
        )
        try:
            properties = dict(
                line.split("=", 1) for line in run(command).splitlines() if "=" in line
            )
            active = properties["ActiveState"]
            sub = properties["SubState"]
            load_state = properties["LoadState"]
            observed[unit] = (
                "未観測（unit不存在）"
                if load_state == "not-found"
                else f"{active} ({sub})"
            )
        except (KeyError, OSError, subprocess.CalledProcessError, ValueError):
            observed[unit] = "未観測"
    return observed


def render_markdown(
    manifest: dict,
    observed_nas: dict[str, list[tuple[str, str]]],
    observed_ser7: dict[str, str],
    generated_at: str,
    nas_error: str | None = None,
) -> str:
    lines = [
        "# Homelab サービスマップ",
        "",
        "> このファイルは `tools/homelab_service_map.py` が生成する現在の運用地図。",
        "> 目的・責務・変更時の確認は `docs/homelab-service-map.json` で管理し、稼働状態は生成時に取得する。",
        "",
        f"- 生成日時: {generated_at}",
        "- 状態の意味: `稼働` / `停止` は今回のDocker観測結果。`未観測` は停止ではなく取得できなかった状態。`未観測（unit不存在）` はmanifestにあるsystemd unitが存在しない状態を表す。",
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
            state = format_container_state(services) if services else "未観測"
            lines.append(
                "| {project} | {state} | {purpose} | {source} | {observe} | {change_check} |".format(
                    project=project,
                    state=state,
                    **metadata,
                )
            )
        lines.append("")

    unregistered = sorted(set(observed_nas) - set(manifest.get("nas", {})))
    if unregistered:
        lines.extend(
            [
                "## 未登録のNAS Composeプロジェクト",
                "",
                "> manifestに未登録のCompose projectを観測した。役割を確認して `docs/homelab-service-map.json` へ登録するか、不要な残骸なら削除判断をする。",
                "",
                "| プロジェクト | 現在の状態 |",
                "|---|---|",
            ]
        )
        for project in unregistered:
            lines.append(f"| {project} | {format_container_state(observed_nas[project])} |")
        lines.append("")

    if nas_error:
        lines.extend(
            [
                "## NAS Docker観測の取得失敗",
                "",
                "> 今回のNAS Docker inventoryは取得できなかった。NAS上の停止・稼働とは区別する。",
                "",
                f"- エラー: `{nas_error}`",
                "",
            ]
        )

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


def format_container_state(services: list[tuple[str, str]]) -> str:
    """Render Docker's State.Status without treating a stopped container as missing."""
    by_state: dict[str, list[str]] = defaultdict(list)
    for service, state in services:
        by_state[state].append(service)

    labels = {"running": "稼働", "exited": "停止"}
    parts = []
    for state, names in sorted(by_state.items()):
        label = labels.get(state, f"状態={state}")
        parts.append(f"{label}: {', '.join(sorted(names))}")
    return "; ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-live", action="store_true", help="render metadata without probing hosts")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    if args.skip_live:
        observed_nas: dict[str, list[tuple[str, str]]] = {}
        observed_ser7: dict[str, str] = {}
        nas_error = None
    else:
        observed_nas, nas_error = probe_nas()
        observed_ser7 = probe_systemd(manifest.get("ser7", {}))
        if nas_error:
            print(f"warning: NAS inventory unavailable: {nas_error}", file=sys.stderr)

    generated_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    args.output.write_text(
        render_markdown(manifest, observed_nas, observed_ser7, generated_at, nas_error).rstrip() + "\n"
    )
    print(f"wrote {args.output}")
    unregistered = sorted(set(observed_nas) - set(manifest.get("nas", {})))
    if unregistered:
        print(
            f"warning: unregistered NAS Compose projects: {', '.join(unregistered)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
