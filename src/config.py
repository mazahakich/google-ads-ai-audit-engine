from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Settings:
    google_ads_developer_token: str
    google_ads_client_id: str
    google_ads_client_secret: str
    google_ads_refresh_token: str
    google_ads_login_customer_id: str
    google_ads_customer_id: str
    anthropic_api_key: str
    audit_checks_path: Path
    reports_dir: Path


def load_settings() -> Settings:
    load_dotenv()

    required_env = {
        "google_ads_developer_token": "GOOGLE_ADS_DEVELOPER_TOKEN",
        "google_ads_client_id": "GOOGLE_ADS_CLIENT_ID",
        "google_ads_client_secret": "GOOGLE_ADS_CLIENT_SECRET",
        "google_ads_refresh_token": "GOOGLE_ADS_REFRESH_TOKEN",
        "google_ads_login_customer_id": "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "google_ads_customer_id": "GOOGLE_ADS_CUSTOMER_ID",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
    }

    values: dict[str, str] = {}
    missing: list[str] = []

    for key, env_name in required_env.items():
        value = os.getenv(env_name)
        if not value:
            missing.append(env_name)
        else:
            values[key] = value

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing required environment variables: {joined}")

    root = Path(__file__).resolve().parent.parent
    return Settings(
        **values,
        audit_checks_path=root / "audit_checks.json",
        reports_dir=root / "reports",
    )
