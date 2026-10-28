"""Командная строка: выгрузка данных аккаунта в data/."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_settings
from .graph_api import GraphAPIError, InstagramGraphClient


def _save(data: Any, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{name}-{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def cmd_profile(client: InstagramGraphClient, args: argparse.Namespace) -> Any:
    return client.get_profile()


def cmd_media(client: InstagramGraphClient, args: argparse.Namespace) -> Any:
    media = list(client.iter_media(limit=args.limit))
    if args.insights:
        for item in media:
            try:
                item["insights"] = client.get_media_insights(item)
            except GraphAPIError as exc:
                item["insights_error"] = exc.message
    return media


def cmd_stories(client: InstagramGraphClient, args: argparse.Namespace) -> Any:
    stories = client.get_stories()
    for item in stories:
        try:
            item["insights"] = client.get_media_insights(item)
        except GraphAPIError as exc:
            item["insights_error"] = exc.message
    return stories


def cmd_insights(client: InstagramGraphClient, args: argparse.Namespace) -> Any:
    until = int(time.time())
    since = until - args.days * 86400
    return {"since": since, "until": until, "metrics": client.get_account_insights(since, until)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="instagram-agent", description="Выгрузка данных Instagram")
    parser.add_argument("--out", type=Path, default=Path("data"), help="папка для JSON (по умолчанию data/)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile", help="профиль аккаунта").set_defaults(func=cmd_profile)

    media = sub.add_parser("media", help="публикации и Reels")
    media.add_argument("--limit", type=int, default=50)
    media.add_argument("--insights", action="store_true", help="добавить статистику каждой публикации")
    media.set_defaults(func=cmd_media)

    sub.add_parser("stories", help="активные сторис со статистикой").set_defaults(func=cmd_stories)

    insights = sub.add_parser("insights", help="статистика аккаунта за период")
    insights.add_argument("--days", type=int, default=28, choices=range(1, 31), metavar="1-30")
    insights.set_defaults(func=cmd_insights)

    args = parser.parse_args(argv)
    try:
        client = InstagramGraphClient(load_settings())
        data = args.func(client, args)
    except (RuntimeError, GraphAPIError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    path = _save(data, args.out, args.command)
    print(f"Сохранено: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
