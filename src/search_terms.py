from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


class SearchTermQueryError(Exception):
    """Raised when search term queries fail."""


@dataclass
class SearchTermMetrics:
    search_term: str = ""
    campaign_id: int | None = None
    campaign_name: str = ""
    campaign_status: str = ""
    ad_group_id: int | None = None
    ad_group_name: str = ""
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
    def roas(self) -> float:
        return self.conversion_value / self.cost if self.cost > 0 else 0

    @property
    def cpa(self) -> float:
        return self.cost / self.conversions if self.conversions > 0 else 0


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name:
        return name

    text = str(value or "")
    return text.rsplit(".", maxsplit=1)[-1]


def _aggregate_row(terms: dict[tuple[str, str, str], SearchTermMetrics], row) -> None:
    key = (
        row.search_term_view.search_term,
        row.campaign.name,
        row.ad_group.name,
    )
    metrics = terms[key]
    metrics.search_term = row.search_term_view.search_term
    metrics.campaign_id = getattr(row.campaign, "id", None)
    metrics.campaign_name = row.campaign.name
    metrics.campaign_status = _enum_name(getattr(row.campaign, "status", ""))
    metrics.ad_group_id = getattr(row.ad_group, "id", None)
    metrics.ad_group_name = row.ad_group.name
    metrics.impressions += row.metrics.impressions
    metrics.clicks += row.metrics.clicks
    metrics.cost += row.metrics.cost_micros / 1_000_000
    metrics.conversions += row.metrics.conversions
    metrics.conversion_value += row.metrics.conversions_value


def _date_filter(start_date: str | None = None, end_date: str | None = None) -> str:
    if start_date and end_date:
        return f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    return "segments.date DURING LAST_30_DAYS"


def fetch_search_terms(
    client,
    customer_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[SearchTermMetrics]:
    date_filter = _date_filter(start_date, end_date)
    queries = (
        f"""
        SELECT
          search_term_view.search_term,
          campaign.id,
          campaign.name,
          campaign.status,
          ad_group.id,
          ad_group.name,
          segments.date,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc
        FROM search_term_view
        WHERE {date_filter}
        """,
        f"""
        SELECT
          search_term_view.search_term,
          campaign.id,
          campaign.name,
          campaign.status,
          ad_group.id,
          ad_group.name,
          segments.date,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM search_term_view
        WHERE {date_filter}
        """,
        f"""
        SELECT
          search_term_view.search_term,
          campaign.name,
          ad_group.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM search_term_view
        WHERE {date_filter}
        """,
    )
    last_error: Exception | None = None

    for query in queries:
        terms: dict[tuple[str, str, str], SearchTermMetrics] = defaultdict(SearchTermMetrics)

        try:
            ga_service = client.get_service("GoogleAdsService")
            response = ga_service.search_stream(customer_id=customer_id, query=query)

            for batch in response:
                for row in batch.results:
                    _aggregate_row(terms, row)

            return list(terms.values())
        except Exception as exc:
            last_error = exc

    raise SearchTermQueryError(f"Search term query failed: {last_error}") from last_error
