from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ClientConfig
from .conversions import ConversionAction, fetch_conversion_actions
from .date_ranges import DateRange, evidence_date_ranges
from .metrics import CampaignPeriodMetrics, fetch_campaign_period_metrics
from .pmax import PMaxAssetGroupMetrics, fetch_pmax_asset_groups
from .search_terms import SearchTermMetrics, fetch_search_terms
from .segments import (
    DeviceSegmentMetrics,
    GeoSegmentMetrics,
    TimeSegmentMetrics,
    fetch_day_of_week_segments,
    fetch_device_segments,
    fetch_geo_segments,
    fetch_hour_of_day_segments,
)


def collect_evidence_pack(client, client_config: ClientConfig, report_dir: Path) -> tuple[Path, list[str]]:
    evidence_dir = report_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    date_ranges = evidence_date_ranges()
    modules = {
        "campaigns": "skipped",
        "conversion_actions": "skipped",
        "search_terms": "skipped",
        "pmax": "skipped",
        "segments": "skipped",
    }
    warnings: list[str] = []
    customer_id = client_config.google_ads_customer_id

    campaign_failures = 0
    for date_range in date_ranges:
        path = evidence_dir / f"google_ads_campaigns_{date_range.days}d.json"
        try:
            campaigns = fetch_campaign_period_metrics(client, customer_id, date_range)
            write_json(path, [campaign_period_to_dict(campaign) for campaign in campaigns])
        except Exception as exc:
            campaign_failures += 1
            write_json(path, [])
            warnings.append(f"{date_range.period_label} campaign evidence failed: {exc}")
    modules["campaigns"] = "failed" if campaign_failures else "success"

    try:
        conversion_actions = fetch_conversion_actions(client, customer_id)
        write_json(evidence_dir / "conversion_actions.json", [conversion_action_to_dict(action) for action in conversion_actions])
        modules["conversion_actions"] = "success"
    except Exception as exc:
        write_json(evidence_dir / "conversion_actions.json", [])
        modules["conversion_actions"] = "failed"
        warnings.append(f"conversion action evidence failed: {exc}")

    date_range_30d = date_ranges[0]
    try:
        search_terms = fetch_search_terms(
            client,
            customer_id,
            start_date=date_range_30d.start_date,
            end_date=date_range_30d.end_date,
        )
        write_json(evidence_dir / "search_terms_30d.json", [search_term_to_dict(term) for term in search_terms])
        modules["search_terms"] = "success"
    except Exception as exc:
        write_json(evidence_dir / "search_terms_30d.json", [])
        modules["search_terms"] = "failed"
        warnings.append(f"search term evidence failed: {exc}")

    try:
        asset_groups = fetch_pmax_asset_groups(
            client,
            customer_id,
            start_date=date_range_30d.start_date,
            end_date=date_range_30d.end_date,
        )
        write_json(evidence_dir / "pmax_asset_groups_30d.json", [pmax_asset_group_to_dict(asset_group) for asset_group in asset_groups])
        modules["pmax"] = "success"
    except Exception as exc:
        write_json(evidence_dir / "pmax_asset_groups_30d.json", [])
        modules["pmax"] = "failed"
        warnings.append(f"PMax evidence failed: {exc}")

    segments, segment_warnings = collect_segment_evidence(client, customer_id, date_range_30d)
    write_json(evidence_dir / "segments_30d.json", segments)
    modules["segments"] = "failed" if len(segment_warnings) == 4 else "success"
    warnings.extend(segment_warnings)

    metadata = {
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "google_ads_customer_id": client_config.google_ads_customer_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_ranges": [date_range.to_dict() for date_range in date_ranges],
        "modules": modules,
        "warnings": warnings,
    }
    write_json(evidence_dir / "audit_metadata.json", metadata)

    return evidence_dir, warnings


def collect_segment_evidence(client, customer_id: str, date_range: DateRange) -> tuple[dict[str, list[dict]], list[str]]:
    warnings: list[str] = []
    segments: dict[str, list[dict]] = {
        "geo": [],
        "device": [],
        "day_of_week": [],
        "hour_of_day": [],
    }

    try:
        geo_segments = fetch_geo_segments(client, customer_id, date_range.start_date, date_range.end_date)
        segments["geo"] = [geo_segment_to_dict(segment) for segment in geo_segments]
    except Exception as exc:
        warnings.append(f"geo segment evidence failed: {exc}")

    try:
        device_segments = fetch_device_segments(client, customer_id, date_range.start_date, date_range.end_date)
        segments["device"] = [device_segment_to_dict(segment) for segment in device_segments]
    except Exception as exc:
        warnings.append(f"device segment evidence failed: {exc}")

    try:
        day_segments = fetch_day_of_week_segments(client, customer_id, date_range.start_date, date_range.end_date)
        segments["day_of_week"] = [time_segment_to_dict(segment) for segment in day_segments]
    except Exception as exc:
        warnings.append(f"day-of-week segment evidence failed: {exc}")

    try:
        hour_segments = fetch_hour_of_day_segments(client, customer_id, date_range.start_date, date_range.end_date)
        segments["hour_of_day"] = [time_segment_to_dict(segment) for segment in hour_segments]
    except Exception as exc:
        warnings.append(f"hour-of-day segment evidence failed: {exc}")

    return segments, warnings


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def campaign_period_to_dict(campaign: CampaignPeriodMetrics) -> dict:
    return {
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "campaign_status": campaign.campaign_status,
        "advertising_channel_type": campaign.advertising_channel_type,
        "bidding_strategy_type": campaign.bidding_strategy_type,
        "impressions": campaign.impressions,
        "clicks": campaign.clicks,
        "cost": campaign.cost,
        "conversions": campaign.conversions,
        "conversion_value": campaign.conversion_value,
        "ctr": campaign.ctr,
        "average_cpc": campaign.average_cpc,
        "cpa": campaign.cpa,
        "roas": campaign.roas,
        "period_label": campaign.period_label,
        "start_date": campaign.start_date,
        "end_date": campaign.end_date,
    }


def conversion_action_to_dict(action: ConversionAction) -> dict:
    return asdict(action)


def search_term_to_dict(term: SearchTermMetrics) -> dict:
    return {
        "search_term": term.search_term,
        "campaign_id": term.campaign_id,
        "campaign_name": term.campaign_name,
        "campaign_status": term.campaign_status,
        "ad_group_id": term.ad_group_id,
        "ad_group_name": term.ad_group_name,
        "impressions": term.impressions,
        "clicks": term.clicks,
        "cost": term.cost,
        "conversions": term.conversions,
        "conversion_value": term.conversion_value,
        "ctr": term.ctr,
        "average_cpc": term.average_cpc,
        "cpa": term.cpa,
        "roas": term.roas,
    }


def pmax_asset_group_to_dict(asset_group: PMaxAssetGroupMetrics) -> dict:
    return {
        "campaign_id": asset_group.campaign_id,
        "campaign_name": asset_group.campaign_name,
        "campaign_status": asset_group.campaign_status,
        "asset_group_id": asset_group.asset_group_id,
        "asset_group_name": asset_group.asset_group_name,
        "asset_group_status": asset_group.asset_group_status,
        "impressions": asset_group.impressions,
        "clicks": asset_group.clicks,
        "cost": asset_group.cost,
        "conversions": asset_group.conversions,
        "conversion_value": asset_group.conversion_value,
        "ctr": asset_group.ctr,
        "average_cpc": asset_group.average_cpc,
        "cpa": asset_group.cpa,
        "roas": asset_group.roas,
    }


def base_segment_dict(segment) -> dict:
    return {
        "campaign_id": segment.campaign_id,
        "campaign_name": segment.campaign_name,
        "campaign_status": segment.campaign_status,
        "impressions": segment.impressions,
        "clicks": segment.clicks,
        "cost": segment.cost,
        "conversions": segment.conversions,
        "conversion_value": segment.conversion_value,
        "ctr": segment.ctr,
        "cpa": segment.cpa,
        "roas": segment.roas,
    }


def geo_segment_to_dict(segment: GeoSegmentMetrics) -> dict:
    data = base_segment_dict(segment)
    data.update(
        {
            "segment_name": segment.segment_name,
            "location_type": segment.location_type,
        }
    )
    return data


def device_segment_to_dict(segment: DeviceSegmentMetrics) -> dict:
    data = base_segment_dict(segment)
    data["device"] = segment.device
    return data


def time_segment_to_dict(segment: TimeSegmentMetrics) -> dict:
    data = base_segment_dict(segment)
    data.update(
        {
            "segment_type": segment.segment_type,
            "segment_value": segment.segment_value,
        }
    )
    return data
