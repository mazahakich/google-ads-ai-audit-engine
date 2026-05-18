from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from google_ads_client import GoogleAdsClientError


@dataclass
class CampaignMetrics:
    last7_cost: float = 0.0
    last7_conv: float = 0.0
    last7_value: float = 0.0
    prev7_cost: float = 0.0
    prev7_conv: float = 0.0
    prev7_value: float = 0.0


def fetch_campaign_metrics(client, customer_id: str) -> dict[str, CampaignMetrics]:
    query = """
        SELECT
          campaign.name,
          segments.date,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
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
                metric_date = datetime.strptime(str(row.segments.date), "%Y-%m-%d").date()
                cost = row.metrics.cost_micros / 1_000_000
                conv = row.metrics.conversions
                value = row.metrics.conversions_value

                if metric_date >= last_7_start:
                    data[campaign].last7_cost += cost
                    data[campaign].last7_conv += conv
                    data[campaign].last7_value += value
                elif metric_date >= prev_7_start:
                    data[campaign].prev7_cost += cost
                    data[campaign].prev7_conv += conv
                    data[campaign].prev7_value += value
    except Exception as exc:
        raise GoogleAdsClientError(f"Google Ads query failed: {exc}") from exc

    return dict(data)
