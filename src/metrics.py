from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .google_ads_client import GoogleAdsClientError


@dataclass
class CampaignMetrics:
    campaign_id: int | None = None
    campaign_name: str = ""
    campaign_status: str = ""
    advertising_channel_type: str = ""
    bidding_strategy_type: str = ""
    target_google_search: bool = False
    target_search_network: bool = False
    target_content_network: bool = False
    target_partner_search_network: bool = False
    last7_cost: float = 0.0
    last7_conv: float = 0.0
    last7_value: float = 0.0
    last7_impressions: int = 0
    last7_clicks: int = 0
    prev7_cost: float = 0.0
    prev7_conv: float = 0.0
    prev7_value: float = 0.0
    prev7_impressions: int = 0
    prev7_clicks: int = 0
    status: str = ""

    @property
    def previous7_cost(self) -> float:
        return self.prev7_cost

    @property
    def last7_conversions(self) -> float:
        return self.last7_conv

    @property
    def previous7_conversions(self) -> float:
        return self.prev7_conv

    @property
    def last7_conversion_value(self) -> float:
        return self.last7_value

    @property
    def previous7_conversion_value(self) -> float:
        return self.prev7_value

    @property
    def previous7_impressions(self) -> int:
        return self.prev7_impressions

    @property
    def impressions(self) -> int:
        return self.last7_impressions

    @property
    def last7_roas(self) -> float:
        return self.last7_value / self.last7_cost if self.last7_cost > 0 else 0

    @property
    def previous7_roas(self) -> float:
        return self.prev7_value / self.prev7_cost if self.prev7_cost > 0 else 0

    @property
    def last7_cpa(self) -> float:
        return self.last7_cost / self.last7_conv if self.last7_conv > 0 else 0

    @property
    def previous7_cpa(self) -> float:
        return self.prev7_cost / self.prev7_conv if self.prev7_conv > 0 else 0


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name:
        return name

    text = str(value)
    return text.rsplit(".", maxsplit=1)[-1]


def _apply_campaign_setup(metrics: CampaignMetrics, campaign) -> None:
    metrics.campaign_id = campaign.id
    metrics.campaign_name = campaign.name
    metrics.campaign_status = _enum_name(campaign.status)
    metrics.status = metrics.campaign_status
    metrics.advertising_channel_type = _enum_name(campaign.advertising_channel_type)
    metrics.bidding_strategy_type = _enum_name(campaign.bidding_strategy_type)
    metrics.target_google_search = campaign.network_settings.target_google_search
    metrics.target_search_network = campaign.network_settings.target_search_network
    metrics.target_content_network = campaign.network_settings.target_content_network
    metrics.target_partner_search_network = campaign.network_settings.target_partner_search_network


def fetch_campaign_metrics(client, customer_id: str) -> dict[str, CampaignMetrics]:
    setup_query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign.bidding_strategy_type,
          campaign.network_settings.target_google_search,
          campaign.network_settings.target_search_network,
          campaign.network_settings.target_content_network,
          campaign.network_settings.target_partner_search_network,
          segments.date,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_14_DAYS
    """
    fallback_query = """
        SELECT
          campaign.name,
          campaign.status,
          segments.date,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_14_DAYS
    """

    today = date.today()
    last_7_start = today - timedelta(days=7)
    prev_7_start = today - timedelta(days=14)
    last_error: Exception | None = None

    for query in (setup_query, fallback_query):
        data = defaultdict(CampaignMetrics)
        ga_service = client.get_service("GoogleAdsService")

        try:
            response = ga_service.search_stream(customer_id=customer_id, query=query)

            for batch in response:
                for row in batch.results:
                    campaign = row.campaign.name
                    _apply_campaign_setup(data[campaign], row.campaign)
                    metric_date = datetime.strptime(str(row.segments.date), "%Y-%m-%d").date()
                    cost = row.metrics.cost_micros / 1_000_000
                    conv = row.metrics.conversions
                    value = row.metrics.conversions_value
                    impressions = row.metrics.impressions
                    clicks = getattr(row.metrics, "clicks", 0)

                    if metric_date >= last_7_start:
                        data[campaign].last7_cost += cost
                        data[campaign].last7_conv += conv
                        data[campaign].last7_value += value
                        data[campaign].last7_impressions += impressions
                        data[campaign].last7_clicks += clicks
                    elif metric_date >= prev_7_start:
                        data[campaign].prev7_cost += cost
                        data[campaign].prev7_conv += conv
                        data[campaign].prev7_value += value
                        data[campaign].prev7_impressions += impressions
                        data[campaign].prev7_clicks += clicks

            return dict(data)
        except Exception as exc:
            last_error = exc

    raise GoogleAdsClientError(f"Google Ads query failed: {last_error}") from last_error
