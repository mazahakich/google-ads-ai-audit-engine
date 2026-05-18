from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .google_ads_client import GoogleAdsClientError


@dataclass
class CampaignMetrics:
    last7_cost: float = 0.0
    last7_conv: float = 0.0
    last7_value: float = 0.0
    last7_impressions: int = 0
    prev7_cost: float = 0.0
    prev7_conv: float = 0.0
    prev7_value: float = 0.0
    prev7_impressions: int = 0
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


def fetch_campaign_metrics(client, customer_id: str) -> dict[str, CampaignMetrics]:
    query = """
        SELECT
          campaign.name,
          campaign.status,
          segments.date,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.impressions
        FROM campaign
        WHERE segments.date DURING LAST_14_DAYS
    """

    today = date.today()
    last_7_start = today - timedelta(days=7)
    prev_7_start = today - timedelta(days=14)
    data = defaultdict(CampaignMetrics)

    try:
        ga_service = client.get_service("GoogleAdsService")
        response = ga_service.search_stream(customer_id=customer_id, query=query)

        for batch in response:
            for row in batch.results:
                campaign = row.campaign.name
                data[campaign].status = str(row.campaign.status)
                metric_date = datetime.strptime(str(row.segments.date), "%Y-%m-%d").date()
                cost = row.metrics.cost_micros / 1_000_000
                conv = row.metrics.conversions
                value = row.metrics.conversions_value
                impressions = row.metrics.impressions

                if metric_date >= last_7_start:
                    data[campaign].last7_cost += cost
                    data[campaign].last7_conv += conv
                    data[campaign].last7_value += value
                    data[campaign].last7_impressions += impressions
                elif metric_date >= prev_7_start:
                    data[campaign].prev7_cost += cost
                    data[campaign].prev7_conv += conv
                    data[campaign].prev7_value += value
                    data[campaign].prev7_impressions += impressions
    except Exception as exc:
        raise GoogleAdsClientError(f"Google Ads query failed: {exc}") from exc

    return dict(data)
