from types import SimpleNamespace

import pytest

from instagram_agent.analysis import analyze, render_report
from instagram_agent.recommend import RecommendationError, build_prompt, get_recommendations
from test_analysis import sample_media


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    def __init__(self, message):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.message = message

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.message)


def make_message(text="## Что работает\nReels", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


def sample():
    result = analyze(sample_media(), {"followers_count": 2000, "username": "test"})
    return render_report(result), result


def test_prompt_contains_report_posts_and_goal():
    report, result = sample()
    prompt = build_prompt(report, result, goal="больше заявок")
    assert "<отчёт>" in prompt and "# Анализ публикаций @test" in prompt
    assert prompt.count("### Пост ") == 8
    assert "#reels #tips" in prompt
    assert "больше заявок" in prompt


def test_recommendations_request_and_text():
    report, result = sample()
    client = FakeClient(make_message())
    assert get_recommendations(report, result, client=client) == "## Что работает\nReels"
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"


def test_refusal_raises():
    report, result = sample()
    with pytest.raises(RecommendationError):
        get_recommendations(report, result, client=FakeClient(make_message("", "refusal")))


def test_no_posts_raises():
    with pytest.raises(RecommendationError):
        get_recommendations("", {"posts": []}, client=FakeClient(make_message()))
