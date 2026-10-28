"""Клиент Instagram Graph API: профиль, публикации, сторис и статистика."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from .config import Settings

PROFILE_FIELDS = (
    "id,username,name,biography,website,profile_picture_url,"
    "followers_count,follows_count,media_count"
)
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
    "permalink,timestamp,like_count,comments_count"
)

# Набор метрик зависит от типа публикации; недоступные API отклоняет целиком.
MEDIA_METRICS = {
    "FEED": "reach,views,likes,comments,saved,shares,total_interactions",
    "REELS": "reach,views,likes,comments,saved,shares,total_interactions,ig_reels_avg_watch_time",
    "STORY": "reach,views,replies,shares,total_interactions,navigation",
}
ACCOUNT_METRICS = "reach,views,accounts_engaged,total_interactions,likes,comments,saves,shares"


class GraphAPIError(RuntimeError):
    def __init__(self, status: int, payload: dict[str, Any]):
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        self.status = status
        self.code = error.get("code")
        self.type = error.get("type")
        self.message = error.get("message") or str(payload)
        super().__init__(f"[{status}] {self.type or 'Error'} {self.code}: {self.message}")


class InstagramGraphClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None, timeout: float = 30):
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path_or_url.startswith("https://"):
            # Ссылка пагинации уже содержит токен и все параметры.
            url, query = path_or_url, None
        else:
            url = f"{self.settings.base_url}/{path_or_url.lstrip('/')}"
            query = {**(params or {}), "access_token": self.settings.access_token}

        response = self.session.get(url, params=query, timeout=self.timeout)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": {"message": response.text}}
        if response.status_code >= 400 or "error" in payload:
            raise GraphAPIError(response.status_code, payload)
        return payload

    def _paginate(self, path: str, params: dict[str, Any], limit: int | None) -> Iterator[dict[str, Any]]:
        page = self._get(path, params)
        count = 0
        while True:
            for item in page.get("data", []):
                yield item
                count += 1
                if limit is not None and count >= limit:
                    return
            next_url = page.get("paging", {}).get("next")
            if not next_url:
                return
            page = self._get(next_url)

    def get_profile(self) -> dict[str, Any]:
        return self._get(self.settings.account_id, {"fields": PROFILE_FIELDS})

    def iter_media(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        page_size = min(limit, 100) if limit else 100
        return self._paginate(
            f"{self.settings.account_id}/media",
            {"fields": MEDIA_FIELDS, "limit": page_size},
            limit,
        )

    def get_stories(self) -> list[dict[str, Any]]:
        """Активные сторис (только за последние 24 часа)."""
        return list(self._paginate(f"{self.settings.account_id}/stories", {"fields": MEDIA_FIELDS}, None))

    def get_media_insights(self, media: dict[str, Any]) -> dict[str, Any]:
        """Метрики одной публикации в виде {метрика: значение}."""
        product_type = media.get("media_product_type", "FEED")
        metrics = MEDIA_METRICS.get(product_type, MEDIA_METRICS["FEED"])
        payload = self._get(f"{media['id']}/insights", {"metric": metrics})
        return _flatten_insights(payload)

    def get_account_insights(
        self,
        since: int | None = None,
        until: int | None = None,
        metrics: str = ACCOUNT_METRICS,
    ) -> dict[str, Any]:
        """Суммарные метрики аккаунта за период (unix-время, не больше 30 дней)."""
        params: dict[str, Any] = {"metric": metrics, "period": "day", "metric_type": "total_value"}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        payload = self._get(f"{self.settings.account_id}/insights", params)
        return _flatten_insights(payload)


def _flatten_insights(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in payload.get("data", []):
        if "total_value" in item:
            value = item["total_value"].get("value")
        else:
            values = item.get("values") or [{}]
            value = values[-1].get("value")
        result[item["name"]] = value
    return result
