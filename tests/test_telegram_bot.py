from datetime import datetime
from pathlib import Path

import pytest

from instagram_agent.analysis import analyze, render_report
from instagram_agent.telegram_bot import (
    ReportBot,
    markdown_to_html,
    parse_schedule,
    report_summary,
    split_message,
)
from test_analysis import sample_media


class FakeAPI:
    def __init__(self):
        self.messages = []
        self.documents = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_document(self, chat_id, path, caption=""):
        self.documents.append((chat_id, Path(path)))

    def typing(self, chat_id):
        pass


def make_bot(tmp_path, schedule=None):
    api = FakeAPI()
    bot = ReportBot(api, allowed={1}, out=tmp_path, tz="UTC", limit=10, schedule=schedule, goal=None)
    result = analyze(sample_media(), {"followers_count": 2000, "username": "test"})
    bot._analyze = lambda: (render_report(result), result)
    return bot, api


def message(chat_id, text):
    return {"chat": {"id": chat_id}, "text": text}


def test_split_message_respects_limit():
    text = "\n".join(f"строка {i}" for i in range(2000))
    chunks = split_message(text, limit=500)
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(chunks) == text


def test_markdown_to_html_escapes_and_formats():
    out = markdown_to_html("## Итог\n- **Reels** лучше <фото>\n- `#tips`")
    assert "<b>Итог</b>" in out
    assert "• <b>Reels</b> лучше &lt;фото&gt;" in out
    assert "<code>#tips</code>" in out


def test_parse_schedule():
    assert parse_schedule("Mon 10:30") == (0, 10, 30)
    assert parse_schedule("") is None
    with pytest.raises(RuntimeError):
        parse_schedule("каждый день")


def test_unknown_chat_gets_its_id(tmp_path):
    bot, api = make_bot(tmp_path)
    bot.handle(message(42, "/report"))
    assert api.documents == []
    assert "42" in api.messages[0][1]


def test_report_command_sends_summary_and_file(tmp_path):
    bot, api = make_bot(tmp_path)
    bot.handle(message(1, "/report"))
    summary = api.messages[-1][1]
    assert "Отчёт @test" in summary and "Лучшие посты" in summary
    chat_id, path = api.documents[0]
    assert chat_id == 1 and path.read_text(encoding="utf-8").startswith("# Анализ публикаций")


def test_summary_is_html_safe():
    result = analyze(sample_media(), {"followers_count": 2000, "username": "a<b"})
    assert "@a&lt;b" in report_summary(result)


def test_schedule_fires_once_per_day(tmp_path):
    bot, api = make_bot(tmp_path, schedule=(0, 10, 0))
    monday = datetime(2026, 10, 26, 10, 5)
    bot.check_schedule(datetime(2026, 10, 26, 9, 59))
    assert api.documents == []
    bot.check_schedule(monday)
    bot.check_schedule(monday.replace(minute=30))
    assert len(api.documents) == 1


def test_schedule_skips_when_too_late(tmp_path):
    bot, api = make_bot(tmp_path, schedule=(0, 10, 0))
    bot.check_schedule(datetime(2026, 10, 26, 15, 0))
    assert api.documents == []
