from __future__ import annotations

from google.ads.googleads.client import GoogleAdsClient

from config import Settings


class GoogleAdsClientError(Exception):
    """Raised when Google Ads client or query execution fails."""


def build_google_ads_client(settings: Settings) -> GoogleAdsClient:
    try:
        return GoogleAdsClient.load_from_dict(
            {
                "developer_token": settings.google_ads_developer_token,
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": settings.google_ads_refresh_token,
                "login_customer_id": settings.google_ads_login_customer_id,
                "use_proto_plus": True,
            }
        )
    except Exception as exc:  # Google SDK raises mixed types
        raise GoogleAdsClientError(f"Failed to initialize Google Ads client: {exc}") from exc
