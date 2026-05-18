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


def load_check_catalog(path: Path) -> dict[str, dict]:
    checks = json.loads(path.read_text(encoding="utf-8"))
    return {item["check_id"]: item for item in checks}


def generate_findings(campaign_data: dict[str, CampaignMetrics], check_catalog: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []
    total_last7_cost = sum(data.last7_cost for data in campaign_data.values())

    for campaign, data in campaign_data.items():
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
        if data.status == "ENABLED" and data.last7_impressions == 0:
            triggered_checks.append(check_catalog["PERF_006"])
        if total_last7_cost > 0 and data.last7_cost > total_last7_cost * SPEND_CONCENTRATION_THRESHOLD:
            triggered_checks.append(check_catalog["PERF_007"])
        if data.last7_cost >= data.prev7_cost * STABLE_SPEND_RATIO and data.last7_conv < data.prev7_conv * CONVERSION_DROP_RATIO:
            triggered_checks.append(check_catalog["PERF_008"])

        if triggered_checks:
            findings.append(
                {
                    "campaign": campaign,
                    "cost_change": round(cost_change, 2),
                    "conv_change": round(conv_change, 2),
                    "roas_change": round(roas_change, 2),
                    "checks": triggered_checks,
                }
            )

    return findings
