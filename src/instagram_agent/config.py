"""Настройки подключения к Instagram Graph API из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_API_HOST = "graph.facebook.com"
DEFAULT_API_VERSION = "v23.0"


@dataclass(frozen=True)
class Settings:
    access_token: str
    account_id: str
    api_host: str = DEFAULT_API_HOST
    api_version: str = DEFAULT_API_VERSION

    @property
    def base_url(self) -> str:
        return f"https://{self.api_host}/{self.api_version}"


def load_settings() -> Settings:
    """Читает .env и окружение.

    Два варианта доступа:
    - Instagram Login: INSTAGRAM_API_HOST=graph.instagram.com, ID аккаунта можно не указывать ("me").
    - Facebook Login: host graph.facebook.com и обязательный INSTAGRAM_BUSINESS_ACCOUNT_ID.
    """
    load_dotenv()

    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не задан INSTAGRAM_ACCESS_TOKEN (см. .env.example)")

    host = os.getenv("INSTAGRAM_API_HOST", "").strip() or DEFAULT_API_HOST
    account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
    if not account_id:
        if host == "graph.instagram.com":
            account_id = "me"
        else:
            raise RuntimeError(
                "Не задан INSTAGRAM_BUSINESS_ACCOUNT_ID (обязателен для graph.facebook.com)"
            )

    return Settings(
        access_token=token,
        account_id=account_id,
        api_host=host,
        api_version=os.getenv("INSTAGRAM_API_VERSION", "").strip() or DEFAULT_API_VERSION,
    )
