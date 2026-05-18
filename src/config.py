from __future__ import annotations

import os
import json
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
    google_ads_customer_id: str | None
    anthropic_api_key: str
    brand_terms: tuple[str, ...]
    clients_config_path: Path
    audit_checks_path: Path
    reports_dir: Path


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    client_name: str
    google_ads_customer_id: str
    brand_terms: tuple[str, ...]
    business_type: str | None = None
    currency: str | None = None
    target_roas: float | None = None
    target_cpa: float | None = None
    notes: str | None = None


def load_settings() -> Settings:
    load_dotenv()

    required_env = {
        "google_ads_developer_token": "GOOGLE_ADS_DEVELOPER_TOKEN",
        "google_ads_client_id": "GOOGLE_ADS_CLIENT_ID",
        "google_ads_client_secret": "GOOGLE_ADS_CLIENT_SECRET",
        "google_ads_refresh_token": "GOOGLE_ADS_REFRESH_TOKEN",
        "google_ads_login_customer_id": "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
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

    root = Path(__file__).resolve().parent.parent
    clients_config_path = resolve_project_path(
        os.getenv("CLIENTS_CONFIG_PATH", "clients.json"),
        root,
    )

    google_ads_customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID")
    if not clients_config_path.exists() and not google_ads_customer_id:
        missing.append("GOOGLE_ADS_CUSTOMER_ID")

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing required environment variables: {joined}")

    brand_terms = parse_brand_terms(os.getenv("BRAND_TERMS", ""))
    return Settings(
        **values,
        google_ads_customer_id=google_ads_customer_id,
        brand_terms=brand_terms,
        clients_config_path=clients_config_path,
        audit_checks_path=root / "audit_checks.json",
        reports_dir=root / "reports",
    )


def load_client_configs(settings: Settings) -> tuple[ClientConfig, ...]:
    if settings.clients_config_path.exists():
        return load_clients_file(settings.clients_config_path, settings.brand_terms)

    if not settings.google_ads_customer_id:
        raise ConfigError("GOOGLE_ADS_CUSTOMER_ID is required when clients.json is not present.")

    return (
        ClientConfig(
            client_id="default",
            client_name="Google Ads Account",
            google_ads_customer_id=settings.google_ads_customer_id,
            brand_terms=settings.brand_terms,
        ),
    )


def load_clients_file(path: Path, fallback_brand_terms: tuple[str, ...]) -> tuple[ClientConfig, ...]:
    try:
        raw_clients = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid clients configuration JSON: {exc}") from exc

    if not isinstance(raw_clients, list) or not raw_clients:
        raise ConfigError("Client configuration must be a non-empty JSON array.")

    clients = []
    seen_client_ids: set[str] = set()

    for index, raw_client in enumerate(raw_clients, start=1):
        if not isinstance(raw_client, dict):
            raise ConfigError(f"Client config entry {index} must be an object.")

        client_id = str(raw_client.get("client_id", "")).strip()
        google_ads_customer_id = str(raw_client.get("google_ads_customer_id", "")).strip()

        if not client_id:
            raise ConfigError(f"Client config entry {index} is missing client_id.")
        if not google_ads_customer_id:
            raise ConfigError(f"Client config entry {index} is missing google_ads_customer_id.")
        if client_id in seen_client_ids:
            raise ConfigError(f"Duplicate client_id in clients configuration: {client_id}")

        seen_client_ids.add(client_id)
        client_brand_terms = parse_brand_terms(raw_client.get("brand_terms", ())) or fallback_brand_terms

        clients.append(
            ClientConfig(
                client_id=client_id,
                client_name=str(raw_client.get("client_name") or client_id).strip(),
                google_ads_customer_id=google_ads_customer_id,
                brand_terms=client_brand_terms,
                business_type=optional_string(raw_client.get("business_type")),
                currency=optional_string(raw_client.get("currency")),
                target_roas=optional_float(raw_client.get("target_roas")),
                target_cpa=optional_float(raw_client.get("target_cpa")),
                notes=optional_string(raw_client.get("notes")),
            )
        )

    return tuple(clients)


def parse_brand_terms(value: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_terms = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_terms = value
    else:
        return ()

    return tuple(str(term).strip().lower() for term in raw_terms if str(term).strip())


def resolve_project_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Expected numeric value, got: {value}") from exc
