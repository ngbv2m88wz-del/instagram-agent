"""Командная строка: выгрузка данных аккаунта в data/."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .analysis import analyze, render_report
from .config import load_settings
from .graph_api import GraphAPIError, InstagramGraphClient
from .recommend import RecommendationError, get_recommendations


def _save(data: Any, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if isinstance(data, str):
        path = out_dir / f"{name}-{stamp}.md"
        path.write_text(data, encoding="utf-8")
    else:
        path = out_dir / f"{name}-{stamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _latest(out_dir: Path, name: str) -> Path | None:
    files = sorted(out_dir.glob(f"{name}-*.json"))
    return files[-1] if files else None


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def run_analyze(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.fetch:
        client = InstagramGraphClient(load_settings())
        profile = client.get_profile()
        media = cmd_media(client, argparse.Namespace(limit=args.limit, insights=True))
        _save(profile, args.out, "profile")
        _save(media, args.out, "media")
    else:
        media_path = args.file or _latest(args.out, "media")
        if not media_path:
            raise RuntimeError(f"В {args.out}/ нет выгрузки media-*.json: запустите `media --insights` или `analyze --fetch`")
        profile_path = _latest(args.out, "profile")
        media = _load(media_path)
        profile = _load(profile_path) if profile_path else None
        print(f"Публикации: {media_path}" + (f", профиль: {profile_path}" if profile_path else ""))
    result = analyze(media, profile, tz=args.tz)
    return render_report(result), result


def run_recommend(args: argparse.Namespace) -> str:
    report, result = run_analyze(args)
    _save(report, args.out, "report")
    print("Claude готовит рекомендации, это может занять пару минут…")
    return get_recommendations(report, result, goal=args.goal)


def _timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise argparse.ArgumentTypeError(f"неизвестный часовой пояс: {name}")
    return name


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
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

    analyze_cmd = sub.add_parser("analyze", help="анализ публикаций, отчёт в Markdown")
    recommend_cmd = sub.add_parser("recommend", help="анализ и рекомендации по контенту от Claude")
    recommend_cmd.add_argument("--goal", default=os.getenv("INSTAGRAM_GOAL") or None, help="цель аккаунта, например «больше заявок на консультации»")
    for cmd in (analyze_cmd, recommend_cmd):
        cmd.add_argument("--file", type=Path, help="выгрузка media-*.json (по умолчанию последняя в data/)")
        cmd.add_argument("--fetch", action="store_true", help="сначала выгрузить свежие данные из API")
        cmd.add_argument("--limit", type=int, default=100, help="сколько постов выгружать с --fetch")
        cmd.add_argument("--tz", type=_timezone, default=os.getenv("INSTAGRAM_TIMEZONE") or "UTC",
                         help="часовой пояс для анализа времени, например Europe/Moscow")

    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            data = run_analyze(args)[0]
        elif args.command == "recommend":
            data = run_recommend(args)
        else:
            data = args.func(InstagramGraphClient(load_settings()), args)
    except (RuntimeError, GraphAPIError, RecommendationError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    names = {"analyze": "report", "recommend": "recommendations"}
    data_name = names.get(args.command, args.command)
    if isinstance(data, str):
        print(data)
    path = _save(data, args.out, data_name)
    print(f"Сохранено: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
