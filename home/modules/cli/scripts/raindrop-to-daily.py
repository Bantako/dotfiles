#!/usr/bin/env python3
"""Raindropの最近のブックマークをObsidianのDailyノートに追記する。

使い方:
    raindrop-to-daily [--days N]

オプション:
    --days N    何日前までを対象にするか (デフォルト: 3)

環境変数:
    RAINDROP_TOKEN  Raindrop.io APIトークン (必須)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import urllib.request

VAULT = Path.home() / "Obsidian/main-vault/01-Daily"
BASE_URL = "https://api.raindrop.io/rest/v1"


def fetch_recent(token: str, days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    page = 0

    while True:
        url = (
            f"{BASE_URL}/raindrops/0"
            f"?sort=-created&perpage=50&page={page}"
        )
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        batch = data.get("items", [])
        if not batch:
            break

        for item in batch:
            created_str = item.get("created", "")
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if created_dt < since:
                return items
            items.append(
                {
                    "title": item.get("title", "(no title)"),
                    "url": item.get("link", ""),
                    "note": item.get("note", "").strip(),
                    "tags": item.get("tags", []),
                    "created": created_dt.astimezone().strftime("%m/%d %H:%M"),
                }
            )
        page += 1

    return items


def daily_path(date: datetime) -> Path:
    return VAULT / f"{date.year}" / f"{date.year}-{date.month:02}" / f"{date.strftime('%Y-%m-%d')}.md"


def format_items(items: list[dict]) -> str:
    lines = ["\n## Raindrop\n"]
    for item in items:
        line = f"- [{item['title']}]({item['url']})"
        if item["note"]:
            line += f" — {item['note']}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3, metavar="N")
    args = parser.parse_args()

    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        print("エラー: RAINDROP_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    items = fetch_recent(token, args.days)
    if not items:
        print(f"直近{args.days}日間のブックマークはありません")
        return

    today = datetime.now()
    path = daily_path(today)

    if not path.exists():
        print(f"Dailyノートが見つかりません: {path}", file=sys.stderr)
        sys.exit(1)

    with path.open("a", encoding="utf-8") as f:
        f.write(format_items(items))

    print(f"{len(items)}件を追記しました → {path}")


if __name__ == "__main__":
    main()
