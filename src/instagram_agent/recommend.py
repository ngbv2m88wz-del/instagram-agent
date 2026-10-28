"""Рекомендации по контенту от Claude на основе отчёта и подписей к постам."""

from __future__ import annotations

from typing import Any

import anthropic

from .analysis import FORMAT_NAMES, Post

MODEL = "claude-opus-5-5"
MAX_CAPTION = 1500  # подписи длиннее обрезаются, чтобы запрос не разрастался

SYSTEM_PROMPT = """Ты — опытный стратег по контенту в Instagram. Тебе дают отчёт с аналитикой \
аккаунта и список постов с метриками и подписями. Дай автору конкретные рекомендации на русском языке.

Опирайся на данные: ссылайся на конкретные посты, цифры и закономерности из отчёта. \
Если данных мало для вывода (меньше 3 постов в группе), прямо скажи об этом, а не выдумывай тренд. \
Не давай общих советов вроде «публикуйте качественный контент» — только то, что следует из этого аккаунта.

Структура ответа в Markdown:
## Что работает
## Что не работает
## Темы и подписи — какие темы, хуки и призывы к действию заходят лучше, с примерами из постов
## Рекомендации — 5–7 конкретных действий по приоритету, у каждого: что сделать и почему (с опорой на цифры)
## Идеи постов — 5 идей с форматом и черновым хуком, в духе лучших постов автора
## План на неделю — сколько постов, какие форматы, дни и время"""


class RecommendationError(RuntimeError):
    pass


def _post_block(index: int, post: Post, followers: int | None) -> str:
    engagement = post.engagement(followers)
    caption = post.caption.strip() or "(без подписи)"
    if len(caption) > MAX_CAPTION:
        caption = caption[:MAX_CAPTION] + "…"
    reach = "—" if post.reach is None else post.reach
    views = "—" if post.views is None else post.views
    return (
        f"### Пост {index}: {post.published:%d.%m.%Y %H:%M}, {FORMAT_NAMES.get(post.format, post.format)}\n"
        f"Ссылка: {post.permalink}\n"
        f"Вовлечённость: {'—' if engagement is None else f'{engagement:.2f}%'} · охват: {reach} · "
        f"просмотры: {views} · лайки: {post.likes} · комментарии: {post.comments} · "
        f"сохранения: {post.saved} · репосты: {post.shares}\n"
        f"Подпись:\n{caption}"
    )


def build_prompt(report: str, result: dict[str, Any], goal: str | None = None) -> str:
    followers = result.get("followers")
    posts = sorted(result["posts"], key=lambda p: p.published, reverse=True)
    parts = []
    if goal:
        parts.append(f"<цель_автора>\n{goal}\n</цель_автора>")
    parts.append(f"<отчёт>\n{report}\n</отчёт>")
    parts.append("<посты>\n" + "\n\n".join(
        _post_block(i, p, followers) for i, p in enumerate(posts, 1)
    ) + "\n</посты>")
    parts.append("Проанализируй аккаунт и дай рекомендации по структуре из инструкции."
                 + (" Все рекомендации подчини цели автора." if goal else ""))
    return "\n\n".join(parts)


def get_recommendations(
    report: str,
    result: dict[str, Any],
    goal: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> str:
    if not result.get("posts"):
        raise RecommendationError("Нет публикаций для рекомендаций")

    try:
        client = client or anthropic.Anthropic()
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": build_prompt(report, result, goal)}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise RecommendationError("Неверный ANTHROPIC_API_KEY")
    except anthropic.RateLimitError:
        raise RecommendationError("Превышен лимит запросов к Claude, попробуйте позже")
    except anthropic.APIStatusError as exc:
        raise RecommendationError(f"Ошибка Claude API ({exc.status_code}): {exc.message}")
    except anthropic.APIConnectionError:
        raise RecommendationError("Нет соединения с Claude API")
    except anthropic.AnthropicError as exc:
        raise RecommendationError(f"Claude API недоступен: {exc}")
    except TypeError as exc:
        if "authentication" not in str(exc):
            raise
        raise RecommendationError("Не задан ANTHROPIC_API_KEY (см. .env.example)")

    if message.stop_reason == "refusal":
        raise RecommendationError("Claude отказался отвечать на этот запрос")

    text = "".join(block.text for block in message.content if block.type == "text").strip()
    if not text:
        raise RecommendationError("Claude вернул пустой ответ")
    if message.stop_reason == "max_tokens":
        text += "\n\n_Ответ обрезан по лимиту длины._"
    return text
