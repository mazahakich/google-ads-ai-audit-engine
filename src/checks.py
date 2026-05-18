from __future__ import annotations

import json
from pathlib import Path

from .metrics import CampaignMetrics

PERF_001_COST_INCREASE_THRESHOLD = 20
ROAS_DROP_THRESHOLD = 0.30
ZERO_CONVERSION_SPEND_THRESHOLD = 50
CPA_INCREASE_THRESHOLD = 0.30
SPEND_CONCENTRATION_THRESHOLD = 0.60
STABLE_SPEND_RATIO = 0.90
CONVERSION_DROP_RATIO = 0.80
MAXIMIZE_CONVERSIONS_SIGNAL = "MAXIMIZE_CONVERSIONS"
CAMPAIGN_NAME_STRUCTURE_INDICATORS = (
    "brand",
    "nonbrand",
    "non-brand",
    "search",
    "shopping",
    "pmax",
    "performance max",
    "remarketing",
    "retargeting",
    "prospecting",
    "competitor",
    "local",
    "geo",
    "display",
    "youtube",
    "demand",
)


def normalize_enum(value) -> str:
    return str(value or "").rsplit(".", maxsplit=1)[-1].upper()


def campaign_is_enabled(data: CampaignMetrics) -> bool:
    return normalize_enum(data.campaign_status or data.status) == "ENABLED"


def campaign_is_search(data: CampaignMetrics) -> bool:
    return normalize_enum(data.advertising_channel_type) == "SEARCH"


def campaign_is_pmax(data: CampaignMetrics) -> bool:
    return normalize_enum(data.advertising_channel_type) == "PERFORMANCE_MAX"


def campaign_name_has_structure_signal(campaign_name: str) -> bool:
    normalized_name = campaign_name.lower().replace("_", " ").replace("-", " ")
    normalized_indicators = [indicator.replace("-", " ") for indicator in CAMPAIGN_NAME_STRUCTURE_INDICATORS]
    return any(indicator in normalized_name for indicator in normalized_indicators)


def load_check_catalog(path: Path) -> dict[str, dict]:
    checks = json.loads(path.read_text(encoding="utf-8"))
    return {item["check_id"]: item for item in checks}


def generate_findings(campaign_data: dict[str, CampaignMetrics], check_catalog: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []
    total_last7_cost = sum(data.last7_cost for data in campaign_data.values())

    for campaign, data in campaign_data.items():
        campaign_name = data.campaign_name or campaign
        cost_change = data.last7_cost - data.prev7_cost
        conv_change = data.last7_conv - data.prev7_conv
        roas_change = data.last7_roas - data.previous7_roas

        triggered_checks: list[dict] = []

        if cost_change > PERF_001_COST_INCREASE_THRESHOLD:
            triggered_checks.append(check_catalog["PERF_001"])
        if data.previous7_roas > 0 and data.last7_roas < data.previous7_roas * (1 - ROAS_DROP_THRESHOLD):
            triggered_checks.append(check_catalog["PERF_002"])
        if data.last7_cost > ZERO_CONVERSION_SPEND_THRESHOLD and data.last7_conv == 0:
            triggered_checks.append(check_catalog["PERF_003"])
        if data.previous7_cpa > 0 and data.last7_cpa > data.previous7_cpa * (1 + CPA_INCREASE_THRESHOLD):
            triggered_checks.append(check_catalog["PERF_004"])
        if data.last7_conv > 0 and data.last7_value == 0:
            triggered_checks.append(check_catalog["PERF_005"])
        if campaign_is_enabled(data) and data.last7_impressions == 0:
            triggered_checks.append(check_catalog["PERF_006"])
        if total_last7_cost > 0 and data.last7_cost > total_last7_cost * SPEND_CONCENTRATION_THRESHOLD:
            triggered_checks.append(check_catalog["PERF_007"])
        if data.last7_cost >= data.prev7_cost * STABLE_SPEND_RATIO and data.last7_conv < data.prev7_conv * CONVERSION_DROP_RATIO:
            triggered_checks.append(check_catalog["PERF_008"])
        if campaign_is_enabled(data) and data.last7_impressions == 0:
            triggered_checks.append(check_catalog["STRUCT_001"])
        if campaign_is_search(data) and data.target_content_network:
            triggered_checks.append(check_catalog["STRUCT_002"])
        if campaign_is_search(data) and data.target_partner_search_network:
            triggered_checks.append(check_catalog["STRUCT_003"])
        if (
            MAXIMIZE_CONVERSIONS_SIGNAL in normalize_enum(data.bidding_strategy_type)
            and (data.last7_value > 0 or data.prev7_value > 0)
        ):
            triggered_checks.append(check_catalog["STRUCT_004"])
        if data.last7_conv > 0 and data.last7_value == 0:
            triggered_checks.append(check_catalog["STRUCT_005"])
        if campaign_is_pmax(data):
            triggered_checks.append(check_catalog["STRUCT_006"])
        if campaign_is_enabled(data) and not campaign_name_has_structure_signal(campaign_name):
            triggered_checks.append(check_catalog["STRUCT_007"])

        if triggered_checks:
            findings.append(
                {
                    "campaign": campaign_name,
                    "campaign_setup": {
                        "campaign_id": data.campaign_id,
                        "campaign_status": data.campaign_status or data.status,
                        "advertising_channel_type": data.advertising_channel_type,
                        "bidding_strategy_type": data.bidding_strategy_type,
                        "target_google_search": data.target_google_search,
                        "target_search_network": data.target_search_network,
                        "target_content_network": data.target_content_network,
                        "target_partner_search_network": data.target_partner_search_network,
                    },
                    "metrics": {
                        "last7_cost": round(data.last7_cost, 2),
                        "previous7_cost": round(data.previous7_cost, 2),
                        "last7_conversions": round(data.last7_conversions, 2),
                        "previous7_conversions": round(data.previous7_conversions, 2),
                        "last7_conversion_value": round(data.last7_conversion_value, 2),
                        "previous7_conversion_value": round(data.previous7_conversion_value, 2),
                        "last7_impressions": data.last7_impressions,
                        "previous7_impressions": data.previous7_impressions,
                        "last7_roas": round(data.last7_roas, 2),
                        "previous7_roas": round(data.previous7_roas, 2),
                        "last7_cpa": round(data.last7_cpa, 2),
                        "previous7_cpa": round(data.previous7_cpa, 2),
                    },
                    "cost_change": round(cost_change, 2),
                    "conv_change": round(conv_change, 2),
                    "roas_change": round(roas_change, 2),
                    "checks": triggered_checks,
                }
            )

    return findings
