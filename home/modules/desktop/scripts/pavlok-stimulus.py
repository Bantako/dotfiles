#!/usr/bin/env python3
"""Send a Pavlok stimulus using the ser7 sops-nix secret."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.pavlok.com/api/v5"
DEFAULT_SECRET = Path("/run/secrets/pavlok_api_key")


def load_authorization(secret_path: Path) -> str:
    try:
        raw = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise SystemExit(f"Missing Pavlok secret: {secret_path}")
    except PermissionError:
        raise SystemExit(f"Pavlok secret is not readable: {secret_path}")

    if not raw:
        raise SystemExit(f"Pavlok secret is empty: {secret_path}")

    if raw.startswith("Bearer "):
        return raw
    return f"Bearer {raw}"


def request(method: str, path: str, auth: str, body: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {
        "accept": "application/json",
        "Authorization": auth,
    }

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"

    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def summarize_error(text: str) -> str:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return text[:200]

    if isinstance(obj, dict):
        for key in ("errors", "detail", "message"):
            if key in obj:
                return f"{key}={obj[key]!r}"
        return f"keys={sorted(obj.keys())}"
    return type(obj).__name__


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a Pavlok stimulus")
    parser.add_argument(
        "--type",
        choices=("vibe", "beep", "zap"),
        default="vibe",
        help="Stimulus type. zap requires --allow-zap.",
    )
    parser.add_argument(
        "--value",
        type=int,
        default=10,
        help="Stimulus value, 1-100. Defaults to 10.",
    )
    parser.add_argument(
        "--reason",
        default="ser7-pavlok-stimulus",
        help="Local log label only; Pavlok API v5 stimulus body is kept minimal.",
    )
    parser.add_argument(
        "--secret",
        type=Path,
        default=DEFAULT_SECRET,
        help=f"Path to Authorization secret. Defaults to {DEFAULT_SECRET}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate arguments and secret readability without sending stimulus.",
    )
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Skip GET /user/ before sending. Not recommended for timers.",
    )
    parser.add_argument(
        "--allow-zap",
        action="store_true",
        help="Required when --type zap is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not 1 <= args.value <= 100:
        print("ERROR: --value must be between 1 and 100", file=sys.stderr)
        return 2

    if args.type == "zap" and not args.allow_zap:
        print("ERROR: --type zap requires --allow-zap", file=sys.stderr)
        return 2

    auth = load_authorization(args.secret)

    if args.dry_run:
        print(
            f"dry-run: would send {args.type}({args.value}) "
            f"reason={args.reason!r} using secret={args.secret}"
        )
        return 0

    if not args.skip_auth_check:
        status, text = request("GET", "/user/", auth)
        if status != 200:
            print(f"ERROR: auth check failed status={status} {summarize_error(text)}", file=sys.stderr)
            return 1

    body = {
        "stimulus": {
            "stimulusType": args.type,
            "stimulusValue": args.value,
        }
    }
    status, text = request("POST", "/stimulus/send", auth, body)
    if status != 200:
        print(f"ERROR: stimulus failed status={status} {summarize_error(text)}", file=sys.stderr)
        return 1

    print(f"sent: {args.type}({args.value}) reason={args.reason!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
