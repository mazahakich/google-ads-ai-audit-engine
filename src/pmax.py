from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .metrics import CampaignMetrics


class PMaxQueryError(Exception):
    """Raised when Performance Max asset group queries fail."""


@dataclass
class PMaxAssetGroupMetrics:
    campaign_id: int | None = None
    campaign_name: str = ""
    campaign_status: str = ""
    asset_group_id: int | None = None
    asset_group_name: str = ""
    asset_group_status: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: float = 0.0
    conversion_value: float = 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions > 0 else 0

    @property
    def average_cpc(self) -> float:
        return self.cost / self.clicks if self.clicks > 0 else 0

    @property
    def cpa(self) -> float:
        return self.cost / self.conversions if self.conversions > 0 else 0

    @property
    def roas(self) -> float:
        return self.conversion_value / self.cost if self.cost > 0 else 0


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name:
        return name

    text = str(value or "")
    return text.rsplit(".", maxsplit=1)[-1]


def pmax_campaigns_from_metrics(campaign_data: dict[str, CampaignMetrics]) -> list[CampaignMetrics]:
    return [
        data
        for data in campaign_data.values()
        if _enum_name(data.advertising_channel_type).upper() == "PERFORMANCE_MAX"
    ]


def _aggregate_row(
    asset_groups: dict[tuple[int | None, str, int | None, str], PMaxAssetGroupMetrics],
    row,
) -> None:
    key = (
        getattr(row.campaign, "id", None),
        row.campaign.name,
        getattr(row.asset_group, "id", None),
        row.asset_group.name,
    )
    metrics = asset_groups[key]
    metrics.campaign_id = getattr(row.campaign, "id", None)
    metrics.campaign_name = row.campaign.name
    metrics.campaign_status = _enum_name(getattr(row.campaign, "status", ""))
    metrics.asset_group_id = getattr(row.asset_group, "id", None)
    metrics.asset_group_name = row.asset_group.name
    metrics.asset_group_status = _enum_name(getattr(row.asset_group, "status", ""))
    metrics.impressions += row.metrics.impressions
    metrics.clicks += row.metrics.clicks
    metrics.cost += row.metrics.cost_micros / 1_000_000
    metrics.conversions += row.metrics.conversions
    metrics.conversion_value += row.metrics.conversions_value


def _date_filter(start_date: str | None = None, end_date: str | None = None) -> str:
    if start_date and end_date:
        return f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    return "segments.date DURING LAST_30_DAYS"


def fetch_pmax_asset_groups(
    client,
    customer_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[PMaxAssetGroupMetrics]:
    date_filter = _date_filter(start_date, end_date)
    queries = (
        f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          asset_group.id,
          asset_group.name,
          asset_group.status,
          segments.date,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM asset_group
        WHERE {date_filter}
          AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
        """,
        f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          asset_group.id,
          asset_group.name,
          asset_group.status,
          segments.date,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM asset_group
        WHERE {date_filter}
        """,
        f"""
        SELECT
          campaign.name,
          asset_group.name,
          asset_group.status,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM asset_group
        WHERE {date_filter}
        """,
    )
    last_error: Exception | None = None

    for query in queries:
        asset_groups: dict[tuple[int | None, str, int | None, str], PMaxAssetGroupMetrics] = defaultdict(
            PMaxAssetGroupMetrics
        )

        try:
            ga_service = client.get_service("GoogleAdsService")
            response = ga_service.search_stream(customer_id=customer_id, query=query)

            for batch in response:
                for row in batch.results:
                    _aggregate_row(asset_groups, row)

            return list(asset_groups.values())
        except Exception as exc:
            last_error = exc

    raise PMaxQueryError(f"Performance Max asset group query failed: {last_error}") from last_error
