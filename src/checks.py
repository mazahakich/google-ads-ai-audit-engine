from __future__ import annotations

import json
from pathlib import Path

from metrics import CampaignMetrics


def load_check_catalog(path: Path) -> dict[str, dict]:
    checks = json.loads(path.read_text(encoding="utf-8"))
    return {item["check_id"]: item for item in checks}


def generate_findings(campaign_data: dict[str, CampaignMetrics], check_catalog: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []

    for campaign, data in campaign_data.items():
        last_roas = data.last7_value / data.last7_cost if data.last7_cost > 0 else 0
        prev_roas = data.prev7_value / data.prev7_cost if data.prev7_cost > 0 else 0

        cost_change = data.last7_cost - data.prev7_cost
        conv_change = data.last7_conv - data.prev7_conv
        roas_change = last_roas - prev_roas

        triggered_checks: list[dict] = []

        if cost_change > 20:
            triggered_checks.append(check_catalog["PERF_001"])
        if roas_change < -0.2:
            triggered_checks.append(check_catalog["PERF_002"])
        if data.last7_cost > 50 and data.last7_conv == 0:
            triggered_checks.append(check_catalog["PERF_003"])

        # Structural checks can be extended here in future without changing the interface.

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
