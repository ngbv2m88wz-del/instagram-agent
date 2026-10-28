"""Анализ публикаций: вовлечённость, форматы, время публикации, подписи."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
FORMAT_NAMES = {"REELS": "Reels", "CAROUSEL_ALBUM": "Карусель", "IMAGE": "Фото", "VIDEO": "Видео"}
HASHTAG_RE = re.compile(r"#[\wЀ-ӿ]+")
MIN_GROUP = 3  # меньше публикаций в группе — вывод ненадёжен


@dataclass
class Post:
    id: str
    permalink: str
    format: str
    published: datetime
    caption: str
    likes: int
    comments: int
    saved: int
    shares: int
    reach: int | None
    views: int | None

    @property
    def interactions(self) -> int:
        return self.likes + self.comments + self.saved + self.shares

    @property
    def hashtags(self) -> list[str]:
        return [tag.lower() for tag in HASHTAG_RE.findall(self.caption)]

    def engagement(self, followers: int | None) -> float | None:
        """Вовлечённость, %: взаимодействия к охвату, а без охвата — к подписчикам."""
        base = self.reach or followers
        return 100 * self.interactions / base if base else None


def _format(item: dict[str, Any]) -> str:
    if item.get("media_product_type") == "REELS":
        return "REELS"
    return item.get("media_type", "IMAGE")


def parse_posts(media: list[dict[str, Any]], tz: ZoneInfo) -> list[Post]:
    posts = []
    for item in media:
        if item.get("media_product_type") == "STORY":
            continue
        insights = item.get("insights") or {}
        published = datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
        posts.append(Post(
            id=item["id"],
            permalink=item.get("permalink", ""),
            format=_format(item),
            published=published,
            caption=item.get("caption") or "",
            likes=insights.get("likes", item.get("like_count")) or 0,
            comments=insights.get("comments", item.get("comments_count")) or 0,
            saved=insights.get("saved") or 0,
            shares=insights.get("shares") or 0,
            reach=insights.get("reach"),
            views=insights.get("views"),
        ))
    return sorted(posts, key=lambda p: p.published)


def _group_stats(groups: dict[Any, list[Post]], followers: int | None) -> list[dict[str, Any]]:
    rows = []
    for key, items in groups.items():
        rates = [r for p in items if (r := p.engagement(followers)) is not None]
        reaches = [p.reach for p in items if p.reach is not None]
        rows.append({
            "key": key,
            "count": len(items),
            "engagement": median(rates) if rates else None,
            "reach": median(reaches) if reaches else None,
            "interactions": median(p.interactions for p in items),
        })
    return rows


def _best(rows: list[dict[str, Any]], metric: str = "engagement") -> dict[str, Any] | None:
    reliable = [r for r in rows if r["count"] >= MIN_GROUP and r[metric] is not None]
    return max(reliable, key=lambda r: r[metric]) if reliable else None


def _caption_bucket(post: Post) -> str:
    length = len(post.caption)
    if length < 100:
        return "короткая (<100)"
    if length < 500:
        return "средняя (100–500)"
    return "длинная (500+)"


def analyze(media: list[dict[str, Any]], profile: dict[str, Any] | None = None, tz: str = "UTC") -> dict[str, Any]:
    zone = ZoneInfo(tz)
    posts = parse_posts(media, zone)
    followers = (profile or {}).get("followers_count")
    if not posts:
        return {"posts": [], "followers": followers, "tz": tz}

    def by(key) -> list[dict[str, Any]]:
        groups: dict[Any, list[Post]] = defaultdict(list)
        for p in posts:
            groups[key(p)].append(p)
        return _group_stats(groups, followers)

    rated = [p for p in posts if p.engagement(followers) is not None]
    rated.sort(key=lambda p: p.engagement(followers), reverse=True)

    days = max((posts[-1].published - posts[0].published).days, 1)

    hashtag_posts: dict[str, list[Post]] = defaultdict(list)
    for p in posts:
        for tag in set(p.hashtags):
            hashtag_posts[tag].append(p)
    tags = sorted(_group_stats(hashtag_posts, followers), key=lambda r: r["count"], reverse=True)

    return {
        "tz": tz,
        "followers": followers,
        "username": (profile or {}).get("username"),
        "posts": posts,
        "period": (posts[0].published, posts[-1].published),
        "per_week": len(posts) / days * 7,
        "has_insights": any(p.reach is not None for p in posts),
        "engagement_median": median(p.engagement(followers) for p in rated) if rated else None,
        "totals": {
            "likes": sum(p.likes for p in posts),
            "comments": sum(p.comments for p in posts),
            "saved": sum(p.saved for p in posts),
            "shares": sum(p.shares for p in posts),
        },
        "formats": by(lambda p: p.format),
        "weekdays": sorted(by(lambda p: p.published.weekday()), key=lambda r: r["key"]),
        "hours": sorted(by(lambda p: p.published.hour // 3 * 3), key=lambda r: r["key"]),
        "captions": by(_caption_bucket),
        "hashtag_count": by(lambda p: min(len(p.hashtags), 10) // 5),
        "hashtags": tags[:15],
        "top": rated[:5],
        "bottom": rated[max(5, len(rated) - 3):][::-1],
        "trend": _trend(posts, followers),
    }


def _trend(posts: list[Post], followers: int | None) -> tuple[float, float] | None:
    """Медианная вовлечённость первой и второй половины периода."""
    rates = [r for p in posts if (r := p.engagement(followers)) is not None]
    if len(rates) < 2 * MIN_GROUP:
        return None
    half = len(rates) // 2
    return median(rates[:half]), median(rates[half:])


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}%"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}".replace(",", " ")


def _table(rows: list[dict[str, Any]], title: str, label) -> list[str]:
    lines = [f"| {title} | Постов | Вовлечённость (медиана) | Охват (медиана) | Взаимодействия (медиана) |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {label(r['key'])} | {r['count']} | {_pct(r['engagement'])} | "
                     f"{_num(r['reach'])} | {_num(r['interactions'])} |")
    return lines


def _post_line(p: Post, followers: int | None) -> str:
    caption = " ".join(p.caption.split())[:70] or "без подписи"
    return (f"- [{p.published:%d.%m.%Y}]({p.permalink}) · {FORMAT_NAMES.get(p.format, p.format)} · "
            f"{_pct(p.engagement(followers))} · ❤ {p.likes} 💬 {p.comments} 🔖 {p.saved} ↗ {p.shares} — {caption}")


def insights_summary(result: dict[str, Any]) -> list[str]:
    """Короткие выводы на основе групп, где хватает данных."""
    notes = []
    if fmt := _best(result["formats"]):
        notes.append(f"Лучший формат по вовлечённости — **{FORMAT_NAMES.get(fmt['key'], fmt['key'])}** "
                     f"({_pct(fmt['engagement'])}, постов: {fmt['count']}).")
    if fmt := _best(result["formats"], "reach"):
        notes.append(f"Больше всего охвата дают **{FORMAT_NAMES.get(fmt['key'], fmt['key'])}** "
                     f"(медиана {_num(fmt['reach'])}).")
    if day := _best(result["weekdays"]):
        notes.append(f"Самый удачный день — **{WEEKDAYS[day['key']]}** ({_pct(day['engagement'])}).")
    if hour := _best(result["hours"]):
        notes.append(f"Лучшее время публикации — **{hour['key']:02d}:00–{hour['key'] + 3:02d}:00** "
                     f"({result['tz']}, {_pct(hour['engagement'])}).")
    if cap := _best(result["captions"]):
        notes.append(f"Лучше работают подписи: **{cap['key']}**.")
    if trend := result["trend"]:
        before, after = trend
        if before and abs(after - before) / before >= 0.15:
            direction = "выросла" if after > before else "снизилась"
            notes.append(f"Вовлечённость во второй половине периода {direction}: {_pct(before)} → {_pct(after)}.")
        else:
            notes.append(f"Вовлечённость стабильна: {_pct(before)} → {_pct(after)}.")
    totals = result["totals"]
    if totals["likes"] and totals["saved"] / totals["likes"] >= 0.1:
        notes.append("Много сохранений относительно лайков — полезный контент заходит, его стоит делать больше.")
    if result["per_week"] < 2:
        notes.append(f"Публикаций мало ({result['per_week']:.1f} в неделю) — регулярность поможет охватам.")
    if not result["has_insights"]:
        notes.append("Нет данных об охвате: вовлечённость считается от подписчиков. "
                     "Выгрузите посты с `--insights` для точного анализа.")
    return notes


def render_report(result: dict[str, Any]) -> str:
    posts: list[Post] = result["posts"]
    if not posts:
        return "# Анализ публикаций\n\nНет публикаций для анализа.\n"

    followers = result["followers"]
    start, end = result["period"]
    totals = result["totals"]
    title = f"@{result['username']}" if result.get("username") else "аккаунта"
    hashtag_groups = {0: "0–4", 1: "5–9", 2: "10+"}

    lines = [
        f"# Анализ публикаций {title}",
        "",
        f"Период: {start:%d.%m.%Y} — {end:%d.%m.%Y} · постов: {len(posts)} · "
        f"{result['per_week']:.1f} в неделю · подписчиков: {_num(followers)}",
        "",
        f"Медианная вовлечённость: **{_pct(result['engagement_median'])}** "
        f"({'взаимодействия / охват' if result['has_insights'] else 'взаимодействия / подписчики'})",
        "",
        f"Всего: ❤ {_num(totals['likes'])} · 💬 {_num(totals['comments'])} · "
        f"🔖 {_num(totals['saved'])} · ↗ {_num(totals['shares'])}",
        "",
        "## Выводы",
        "",
        *[f"- {note}" for note in insights_summary(result)],
        "",
        f"_Выводы делаются только по группам от {MIN_GROUP} постов._",
        "",
        "## Лучшие посты",
        "",
        *[_post_line(p, followers) for p in result["top"]],
        "",
    ]
    if result["bottom"]:
        lines += ["## Слабые посты", "", *[_post_line(p, followers) for p in result["bottom"]], ""]

    lines += ["## Форматы", "", *_table(result["formats"], "Формат", lambda k: FORMAT_NAMES.get(k, k)), ""]
    lines += ["## Дни недели", "", *_table(result["weekdays"], "День", lambda k: WEEKDAYS[k]), ""]
    lines += [f"## Время публикации ({result['tz']})", "",
              *_table(result["hours"], "Время", lambda k: f"{k:02d}–{k + 3:02d}"), ""]
    lines += ["## Длина подписи", "", *_table(result["captions"], "Подпись", str), ""]
    lines += ["## Количество хэштегов", "",
              *_table(sorted(result["hashtag_count"], key=lambda r: r["key"]), "Хэштегов", hashtag_groups.get), ""]
    if result["hashtags"]:
        lines += ["## Частые хэштеги", "", *_table(result["hashtags"], "Хэштег", str), ""]
    return "\n".join(lines)
