from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


class SegmentQueryError(Exception):
    """Raised when a segmentation query fails."""


@dataclass
class SegmentMetrics:
    campaign_id: int | None = None
    campaign_name: str = ""
    campaign_status: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: float = 0.0
    conversion_value: float = 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions > 0 else 0

    @property
    def cpa(self) -> float:
        return self.cost / self.conversions if self.conversions > 0 else 0

    @property
    def roas(self) -> float:
        return self.conversion_value / self.cost if self.cost > 0 else 0


@dataclass
class GeoSegmentMetrics(SegmentMetrics):
    segment_name: str = ""
    location_type: str = ""


@dataclass
class DeviceSegmentMetrics(SegmentMetrics):
    device: str = ""


@dataclass
class TimeSegmentMetrics(SegmentMetrics):
    segment_type: str = ""
    segment_value: str = ""


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name:
        return name

    text = str(value or "")
    return text.rsplit(".", maxsplit=1)[-1]


def _add_metrics(metrics: SegmentMetrics, row) -> None:
    metrics.campaign_id = getattr(row.campaign, "id", None)
    metrics.campaign_name = row.campaign.name
    metrics.campaign_status = _enum_name(getattr(row.campaign, "status", ""))
    metrics.impressions += row.metrics.impressions
    metrics.clicks += row.metrics.clicks
    metrics.cost += row.metrics.cost_micros / 1_000_000
    metrics.conversions += row.metrics.conversions
    metrics.conversion_value += row.metrics.conversions_value


def fetch_geo_segments(client, customer_id: str) -> list[GeoSegmentMetrics]:
    queries = (
        """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          geographic_view.country_criterion_id,
          geographic_view.location_type,
          segments.geo_target_country,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM geographic_view
        WHERE segments.date DURING LAST_30_DAYS
        """,
        """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          geographic_view.country_criterion_id,
          geographic_view.location_type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM geographic_view
        WHERE segments.date DURING LAST_30_DAYS
        """,
    )
    last_error: Exception | None = None

    for query in queries:
        segments: dict[tuple[int | None, str, str, str], GeoSegmentMetrics] = defaultdict(GeoSegmentMetrics)

        try:
            ga_service = client.get_service("GoogleAdsService")
            response = ga_service.search_stream(customer_id=customer_id, query=query)

            for batch in response:
                for row in batch.results:
                    location_type = _enum_name(getattr(row.geographic_view, "location_type", ""))
                    country = str(getattr(row.segments, "geo_target_country", "") or "")
                    criterion_id = getattr(row.geographic_view, "country_criterion_id", "")
                    segment_name = country or str(criterion_id)
                    key = (getattr(row.campaign, "id", None), row.campaign.name, segment_name, location_type)
                    metrics = segments[key]
                    metrics.segment_name = segment_name
                    metrics.location_type = location_type
                    _add_metrics(metrics, row)

            return list(segments.values())
        except Exception as exc:
            last_error = exc

    raise SegmentQueryError(f"Geo segment query failed: {last_error}") from last_error


def fetch_device_segments(client, customer_id: str) -> list[DeviceSegmentMetrics]:
    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          segments.device,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
    """
    segments: dict[tuple[int | None, str, str], DeviceSegmentMetrics] = defaultdict(DeviceSegmentMetrics)

    try:
        ga_service = client.get_service("GoogleAdsService")
        response = ga_service.search_stream(customer_id=customer_id, query=query)

        for batch in response:
            for row in batch.results:
                device = _enum_name(row.segments.device)
                key = (getattr(row.campaign, "id", None), row.campaign.name, device)
                metrics = segments[key]
                metrics.device = device
                _add_metrics(metrics, row)

        return list(segments.values())
    except Exception as exc:
        raise SegmentQueryError(f"Device segment query failed: {exc}") from exc


def fetch_day_of_week_segments(client, customer_id: str) -> list[TimeSegmentMetrics]:
    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          segments.day_of_week,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
    """
    return _fetch_time_segments(client, customer_id, query, "day_of_week")


def fetch_hour_of_day_segments(client, customer_id: str) -> list[TimeSegmentMetrics]:
    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          segments.hour,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
    """
    return _fetch_time_segments(client, customer_id, query, "hour_of_day")


def _fetch_time_segments(client, customer_id: str, query: str, segment_type: str) -> list[TimeSegmentMetrics]:
    segments: dict[tuple[int | None, str, str, str], TimeSegmentMetrics] = defaultdict(TimeSegmentMetrics)

    try:
        ga_service = client.get_service("GoogleAdsService")
        response = ga_service.search_stream(customer_id=customer_id, query=query)

        for batch in response:
            for row in batch.results:
                if segment_type == "day_of_week":
                    segment_value = _enum_name(row.segments.day_of_week)
                else:
                    segment_value = str(row.segments.hour)

                key = (getattr(row.campaign, "id", None), row.campaign.name, segment_type, segment_value)
                metrics = segments[key]
                metrics.segment_type = segment_type
                metrics.segment_value = segment_value
                _add_metrics(metrics, row)

        return list(segments.values())
    except Exception as exc:
        raise SegmentQueryError(f"{segment_type} segment query failed: {exc}") from exc
