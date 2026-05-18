from __future__ import annotations

import json
from pathlib import Path

from .conversions import ConversionAction
from .metrics import CampaignMetrics
from .search_terms import SearchTermMetrics

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
BUSINESS_OUTCOME_CONVERSION_INDICATORS = (
    "purchase",
    "lead",
    "booking",
    "form",
    "sign up",
    "signup",
    "subscribe",
    "sale",
    "checkout",
    "conversion",
    "contact",
)
MODERN_ATTRIBUTION_MODEL = "DATA_DRIVEN"
SEARCH_TERM_SPEND_WITHOUT_CONVERSIONS_THRESHOLD = 30
SEARCH_TERM_HIGH_CLICK_THRESHOLD = 20
SEARCH_TERM_LOW_CTR_IMPRESSIONS_THRESHOLD = 100
SEARCH_TERM_LOW_CTR_THRESHOLD = 0.01
SEARCH_TERM_POOR_ROAS_COST_THRESHOLD = 30
SEARCH_TERM_POOR_ROAS_THRESHOLD = 1.0
SEARCH_TERM_FINDING_LIMIT = 25
INFORMATIONAL_QUERY_TERMS = (
    "how",
    "what",
    "why",
    "guide",
    "tutorial",
    "example",
    "free",
    "meaning",
    "definition",
    "review",
    "reddit",
    "forum",
    "pdf",
    "template",
)
COMPETITOR_QUERY_TERMS = (
    "vs",
    "versus",
    "alternative",
    "alternatives",
    "competitor",
    "competitors",
    "compare",
    "comparison",
)
BRAND_CAMPAIGN_INDICATORS = ("brand", "branded")
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


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


def conversion_action_is_enabled(action: ConversionAction) -> bool:
    return normalize_enum(action.status) == "ENABLED"


def conversion_action_is_primary_or_included(action: ConversionAction) -> bool:
    return conversion_action_is_enabled(action) and (
        action.primary_for_goal or action.include_in_conversions_metric
    )


def conversion_action_has_business_outcome_signal(action: ConversionAction) -> bool:
    text = f"{action.name} {action.category}".lower().replace("_", " ").replace("-", " ")
    return any(indicator in text for indicator in BUSINESS_OUTCOME_CONVERSION_INDICATORS)


def conversion_action_context(action: ConversionAction) -> dict:
    return {
        "conversion_action_id": action.id,
        "category": action.category,
        "type": action.type,
        "status": action.status,
        "primary_for_goal": action.primary_for_goal,
        "include_in_conversions_metric": action.include_in_conversions_metric,
        "default_value": action.default_value,
        "always_use_default_value": action.always_use_default_value,
        "counting_type": action.counting_type,
        "attribution_model": action.attribution_model,
    }


def conversion_finding(
    checks: list[dict],
    *,
    entity_type: str,
    entity_name: str,
    context: dict | None = None,
) -> dict:
    return {
        "scope": "account",
        "entity_type": entity_type,
        "entity_name": entity_name,
        "triggered_checks": checks,
        "checks": checks,
        "context": context or {},
    }


def normalized_text(value: str) -> str:
    return value.lower().replace("_", " ").replace("-", " ")


def search_term_context(term: SearchTermMetrics) -> dict:
    return {
        "search_term": term.search_term,
        "campaign_id": term.campaign_id,
        "campaign_status": term.campaign_status,
        "ad_group_id": term.ad_group_id,
        "cost": round(term.cost, 2),
        "clicks": term.clicks,
        "impressions": term.impressions,
        "conversions": round(term.conversions, 2),
        "conversion_value": round(term.conversion_value, 2),
        "ctr": round(term.ctr, 4),
        "average_cpc": round(term.average_cpc, 2),
        "cpa": round(term.cpa, 2),
        "roas": round(term.roas, 2),
    }


def query_contains_any(search_term: str, indicators: tuple[str, ...]) -> bool:
    query = normalized_text(search_term)
    query_words = set(query.split())

    for indicator in indicators:
        normalized_indicator = normalized_text(indicator)
        if " " in normalized_indicator:
            if normalized_indicator in query:
                return True
        elif normalized_indicator in query_words:
            return True

    return False


def query_contains_brand_term(search_term: str, brand_terms: tuple[str, ...]) -> bool:
    query = normalized_text(search_term)
    return any(normalized_text(term) in query for term in brand_terms)


def campaign_name_is_brand(campaign_name: str) -> bool:
    return query_contains_any(campaign_name, BRAND_CAMPAIGN_INDICATORS)


def highest_severity_rank(finding: dict) -> int:
    checks = finding.get("triggered_checks") or finding.get("checks") or []
    severities = [SEVERITY_RANK.get(check.get("severity", "low"), 2) for check in checks]
    return min(severities, default=2)


def limit_search_term_findings(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda finding: (
            highest_severity_rank(finding),
            -finding.get("context", {}).get("cost", 0),
        ),
    )[:SEARCH_TERM_FINDING_LIMIT]


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


def generate_conversion_findings(
    conversion_actions: list[ConversionAction],
    check_catalog: dict[str, dict],
    campaign_data: dict[str, CampaignMetrics] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    enabled_primary_actions = [
        action for action in conversion_actions if conversion_action_is_primary_or_included(action)
    ]
    inactive_actions = [
        action for action in conversion_actions if not conversion_action_is_enabled(action)
    ]
    account_has_conversion_value = any(
        data.last7_value > 0 or data.prev7_value > 0 for data in (campaign_data or {}).values()
    )

    if not enabled_primary_actions:
        findings.append(
            conversion_finding(
                [check_catalog["TRACK_001"]],
                entity_type="account_tracking",
                entity_name="Account conversion tracking",
                context={
                    "enabled_primary_or_included_conversion_actions": 0,
                    "total_conversion_actions": len(conversion_actions),
                },
            )
        )

    if len(enabled_primary_actions) > 3:
        findings.append(
            conversion_finding(
                [check_catalog["TRACK_002"]],
                entity_type="account_tracking",
                entity_name="Account conversion tracking",
                context={
                    "enabled_primary_or_included_conversion_actions": len(enabled_primary_actions),
                    "conversion_action_names": [action.name for action in enabled_primary_actions],
                },
            )
        )

    if enabled_primary_actions and not any(
        conversion_action_has_business_outcome_signal(action) for action in enabled_primary_actions
    ):
        findings.append(
            conversion_finding(
                [check_catalog["TRACK_003"]],
                entity_type="account_tracking",
                entity_name="Account conversion tracking",
                context={
                    "enabled_primary_or_included_conversion_actions": len(enabled_primary_actions),
                    "conversion_action_names": [action.name for action in enabled_primary_actions],
                },
            )
        )

    for action in enabled_primary_actions:
        triggered_checks: list[dict] = []
        context = {
            **conversion_action_context(action),
            "account_has_conversion_value_metrics": account_has_conversion_value,
        }

        if action.default_value in (None, 0):
            triggered_checks.append(check_catalog["TRACK_004"])

        if action.always_use_default_value:
            triggered_checks.append(check_catalog["TRACK_005"])

        attribution_model = normalize_enum(action.attribution_model)
        if attribution_model and MODERN_ATTRIBUTION_MODEL not in attribution_model:
            triggered_checks.append(check_catalog["TRACK_007"])

        if triggered_checks:
            findings.append(
                conversion_finding(
                    triggered_checks,
                    entity_type="conversion_action",
                    entity_name=action.name,
                    context=context,
                )
            )

    for action in inactive_actions:
        findings.append(
            conversion_finding(
                [check_catalog["TRACK_006"]],
                entity_type="conversion_action",
                entity_name=action.name,
                context=conversion_action_context(action),
            )
        )

    return findings


def generate_search_term_findings(
    search_terms: list[SearchTermMetrics],
    check_catalog: dict[str, dict],
    brand_terms: tuple[str, ...] = (),
) -> list[dict]:
    findings: list[dict] = []

    for term in search_terms:
        triggered_checks: list[dict] = []
        is_brand_campaign = campaign_name_is_brand(term.campaign_name)
        query_has_brand = query_contains_brand_term(term.search_term, brand_terms) if brand_terms else False

        if term.cost > SEARCH_TERM_SPEND_WITHOUT_CONVERSIONS_THRESHOLD and term.conversions == 0:
            triggered_checks.append(check_catalog["QUERY_001"])
        if term.clicks >= SEARCH_TERM_HIGH_CLICK_THRESHOLD and term.conversions == 0:
            triggered_checks.append(check_catalog["QUERY_002"])
        if term.impressions >= SEARCH_TERM_LOW_CTR_IMPRESSIONS_THRESHOLD and term.ctr < SEARCH_TERM_LOW_CTR_THRESHOLD:
            triggered_checks.append(check_catalog["QUERY_003"])
        if query_contains_any(term.search_term, INFORMATIONAL_QUERY_TERMS):
            triggered_checks.append(check_catalog["QUERY_004"])
        if query_contains_any(term.search_term, COMPETITOR_QUERY_TERMS):
            triggered_checks.append(check_catalog["QUERY_005"])
        if brand_terms and not is_brand_campaign and query_has_brand:
            triggered_checks.append(check_catalog["QUERY_006"])
        if brand_terms and is_brand_campaign and not query_has_brand:
            triggered_checks.append(check_catalog["QUERY_007"])
        if (
            term.cost > SEARCH_TERM_POOR_ROAS_COST_THRESHOLD
            and term.conversion_value > 0
            and term.roas < SEARCH_TERM_POOR_ROAS_THRESHOLD
        ):
            triggered_checks.append(check_catalog["QUERY_008"])

        if triggered_checks:
            findings.append(
                {
                    "scope": "search_term",
                    "entity_type": "search_term",
                    "entity_name": term.search_term,
                    "campaign": term.campaign_name,
                    "ad_group": term.ad_group_name,
                    "triggered_checks": triggered_checks,
                    "checks": triggered_checks,
                    "context": search_term_context(term),
                }
            )

    return limit_search_term_findings(findings)
