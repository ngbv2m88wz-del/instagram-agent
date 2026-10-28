"""Telegram-бот: отчёты и рекомендации по команде и по расписанию."""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from .analysis import FORMAT_NAMES, insights_summary
from .cli import _save, run_analyze
from .config import load_settings
from .graph_api import GraphAPIError, InstagramGraphClient
from .recommend import RecommendationError, get_recommendations

log = logging.getLogger("instagram_agent.bot")

MESSAGE_LIMIT = 4096
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
HELP = (
    "Команды:\n"
    "/report — отчёт по последним постам\n"
    "/recommend [цель] — рекомендации от Claude, например: /recommend больше заявок\n"
    "/profile — профиль и подписчики\n"
    "/help — эта справка"
)


class TelegramAPI:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.session = session or requests.Session()

    def call(self, method: str, http_timeout: float = 30, files: dict | None = None, **params: Any) -> Any:
        response = self.session.post(f"{self.base}/{method}", data=params, files=files, timeout=http_timeout)
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram {method}: {payload.get('description')}")
        return payload["result"]

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            try:
                self.call("sendMessage", chat_id=chat_id, text=chunk, parse_mode="HTML",
                          disable_web_page_preview="true")
            except RuntimeError as exc:
                if "parse" not in str(exc).lower():
                    raise
                # Разметка сломалась (например, тег разрезан между частями) — шлём без неё.
                plain = html.unescape(re.sub(r"<[^>]+>", "", chunk))
                self.call("sendMessage", chat_id=chat_id, text=plain, disable_web_page_preview="true")

    def send_document(self, chat_id: int, path: Path, caption: str = "") -> None:
        with path.open("rb") as f:
            self.call("sendDocument", http_timeout=60, files={"document": (path.name, f)},
                      chat_id=chat_id, caption=caption)

    def typing(self, chat_id: int) -> None:
        try:
            self.call("sendChatAction", chat_id=chat_id, action="typing")
        except (RuntimeError, requests.RequestException):
            pass


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Режет текст по строкам, чтобы каждая часть влезла в сообщение Telegram."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)
    return chunks


def markdown_to_html(text: str) -> str:
    """Упрощённо переводит Markdown от Claude в HTML, который понимает Telegram."""
    lines = []
    for line in html.escape(text, quote=False).splitlines():
        if heading := re.match(r"#{1,6}\s+(.*)", line):
            line = f"\n<b>{heading.group(1)}</b>"
        elif re.match(r"\s*[-*]\s+", line):
            line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        lines.append(line)
    return "\n".join(lines).strip()


def report_summary(result: dict[str, Any]) -> str:
    posts = result["posts"]
    if not posts:
        return "Нет публикаций для анализа."
    start, end = result["period"]
    title = f"@{result['username']}" if result.get("username") else "аккаунта"
    rate = result["engagement_median"]
    lines = [
        f"<b>📊 Отчёт {html.escape(title)}</b>",
        f"{start:%d.%m.%Y} — {end:%d.%m.%Y} · постов: {len(posts)} · {result['per_week']:.1f} в неделю",
        f"Подписчиков: {result['followers'] or '—'} · вовлечённость: {'—' if rate is None else f'{rate:.2f}%'}",
        "",
        "<b>Выводы</b>",
        *[f"• {markdown_to_html(note)}" for note in insights_summary(result)],
    ]
    if result["top"]:
        lines += ["", "<b>Лучшие посты</b>"]
        for p in result["top"][:3]:
            rate = p.engagement(result["followers"])
            lines.append(
                f'• <a href="{html.escape(p.permalink)}">{p.published:%d.%m}</a> · '
                f"{FORMAT_NAMES.get(p.format, p.format)} · {'—' if rate is None else f'{rate:.2f}%'} · "
                f"❤ {p.likes} 💬 {p.comments} 🔖 {p.saved}"
            )
    lines += ["", "Полный отчёт — в файле."]
    return "\n".join(lines)


def parse_schedule(value: str) -> tuple[int, int, int] | None:
    """'mon 10:00' → (0, 10, 0). Пустая строка — расписание выключено."""
    value = value.strip().lower()
    if not value:
        return None
    try:
        day, clock = value.split()
        hour, minute = map(int, clock.split(":"))
        return WEEKDAYS[day], hour, minute
    except (ValueError, KeyError):
        raise RuntimeError(f"Неверный TELEGRAM_REPORT_SCHEDULE: {value!r}, нужно например 'mon 10:00'")


class ReportBot:
    def __init__(self, api: TelegramAPI, allowed: set[int], out: Path, tz: str, limit: int,
                 schedule: tuple[int, int, int] | None, goal: str | None):
        self.api = api
        self.allowed = allowed
        self.out = out
        self.tz = tz
        self.limit = limit
        self.schedule = schedule
        self.goal = goal
        self.offset = 0
        self.last_scheduled: str | None = None

    def _analyze(self) -> tuple[str, dict[str, Any]]:
        args = argparse.Namespace(fetch=True, file=None, limit=self.limit, tz=self.tz, out=self.out)
        return run_analyze(args)

    def send_report(self, chat_id: int) -> None:
        self.api.send_message(chat_id, "Собираю данные из Instagram…")
        self.api.typing(chat_id)
        report, result = self._analyze()
        path = _save(report, self.out, "report")
        self.api.send_message(chat_id, report_summary(result))
        self.api.send_document(chat_id, path)

    def send_recommendations(self, chat_id: int, goal: str | None) -> None:
        self.api.send_message(chat_id, "Собираю данные и спрашиваю Claude, это займёт пару минут…")
        self.api.typing(chat_id)
        report, result = self._analyze()
        _save(report, self.out, "report")
        text = get_recommendations(report, result, goal=goal or self.goal)
        path = _save(text, self.out, "recommendations")
        self.api.send_message(chat_id, markdown_to_html(text))
        self.api.send_document(chat_id, path)

    def send_profile(self, chat_id: int) -> None:
        profile = InstagramGraphClient(load_settings()).get_profile()
        self.api.send_message(chat_id, "\n".join([
            f"<b>@{html.escape(profile.get('username', ''))}</b> {html.escape(profile.get('name') or '')}",
            f"Подписчики: {profile.get('followers_count', '—')} · подписки: {profile.get('follows_count', '—')}",
            f"Публикаций: {profile.get('media_count', '—')}",
        ]))

    def handle(self, message: dict[str, Any]) -> None:
        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return
        command, _, rest = text.partition(" ")
        command = command.split("@")[0].lower()

        if chat_id not in self.allowed:
            log.warning("Запрос из чужого чата %s", chat_id)
            self.api.send_message(chat_id, f"Нет доступа. ID этого чата: <code>{chat_id}</code>\n"
                                           "Добавьте его в TELEGRAM_ALLOWED_CHAT_IDS и перезапустите бота.")
            return

        try:
            if command in ("/start", "/help"):
                self.api.send_message(chat_id, HELP)
            elif command == "/report":
                self.send_report(chat_id)
            elif command == "/recommend":
                self.send_recommendations(chat_id, rest.strip() or None)
            elif command == "/profile":
                self.send_profile(chat_id)
            else:
                self.api.send_message(chat_id, "Не знаю такой команды.\n\n" + HELP)
        except (RuntimeError, GraphAPIError, RecommendationError, requests.RequestException) as exc:
            log.exception("Ошибка команды %s", command)
            self.api.send_message(chat_id, f"Ошибка: {html.escape(str(exc))}")

    def check_schedule(self, now: datetime) -> None:
        if not self.schedule:
            return
        day, hour, minute = self.schedule
        key = now.strftime("%Y-%m-%d")
        if now.weekday() != day or (now.hour, now.minute) < (hour, minute) or self.last_scheduled == key:
            return
        if now.hour > hour + 1:
            # Бот был выключен в момент рассылки — не шлём с большим опозданием.
            self.last_scheduled = key
            return
        self.last_scheduled = key
        for chat_id in self.allowed:
            try:
                self.api.send_message(chat_id, "🗓 Еженедельный отчёт")
                self.send_report(chat_id)
            except Exception:
                log.exception("Не удалось отправить отчёт по расписанию в %s", chat_id)

    def run(self) -> None:
        log.info("Бот запущен, чаты: %s, расписание: %s", self.allowed or "не заданы", self.schedule)
        zone = ZoneInfo(self.tz)
        while True:
            try:
                updates = self.api.call("getUpdates", http_timeout=40, offset=self.offset, timeout=30,
                                        allowed_updates='["message"]')
            except (RuntimeError, requests.RequestException) as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(5)
                updates = []
            for update in updates:
                self.offset = update["update_id"] + 1
                if message := update.get("message"):
                    try:
                        self.handle(message)
                    except Exception:
                        log.exception("Не удалось обработать сообщение")
            self.check_schedule(datetime.now(zone))


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Ошибка: не задан TELEGRAM_BOT_TOKEN (см. .env.example)")
        return 1
    allowed = {int(x) for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").replace(" ", "").split(",") if x}
    try:
        bot = ReportBot(
            api=TelegramAPI(token),
            allowed=allowed,
            out=Path(os.getenv("INSTAGRAM_DATA_DIR") or "data"),
            tz=os.getenv("INSTAGRAM_TIMEZONE") or "UTC",
            limit=int(os.getenv("TELEGRAM_REPORT_POSTS") or 100),
            schedule=parse_schedule(os.getenv("TELEGRAM_REPORT_SCHEDULE", "")),
            goal=os.getenv("INSTAGRAM_GOAL") or None,
        )
    except RuntimeError as exc:
        print(f"Ошибка: {exc}")
        return 1
    try:
        bot.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
