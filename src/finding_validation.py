from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
NAMING_ONLY_CHECK_IDS = {"STRUCT_007", "PMAX_007"}
BRAND_CHECK_IDS = {"QUERY_006", "QUERY_007"}
ROAS_OR_VALUE_CHECK_IDS = {
    "PERF_002",
    "STRUCT_004",
    "QUERY_008",
    "PMAX_003",
    "SEG_002",
    "SEG_004",
}
COMPARISON_CHECK_IDS = {"PERF_001", "PERF_002", "PERF_004", "PERF_008"}
PARTIAL_API_SCOPES = {"pmax", "segment"}


REQUIRED_METRICS_BY_CHECK = {
    "PERF_001": ("last7_cost", "previous7_cost"),
    "PERF_002": ("last7_roas", "previous7_roas"),
    "PERF_003": ("last7_cost", "last7_conversions"),
    "PERF_004": ("last7_cpa", "previous7_cpa"),
    "PERF_005": ("last7_conversions", "last7_conversion_value"),
    "PERF_006": ("last7_impressions",),
    "PERF_007": ("last7_cost",),
    "PERF_008": ("last7_cost", "previous7_cost", "last7_conversions", "previous7_conversions"),
    "STRUCT_001": ("last7_impressions",),
    "STRUCT_002": ("target_content_network",),
    "STRUCT_003": ("target_partner_search_network",),
    "STRUCT_004": ("bidding_strategy_type",),
    "STRUCT_005": ("last7_conversions", "last7_conversion_value"),
    "QUERY_001": ("cost", "conversions"),
    "QUERY_002": ("clicks", "conversions"),
    "QUERY_003": ("impressions", "ctr"),
    "QUERY_008": ("cost", "conversion_value", "roas"),
    "PMAX_002": ("cost", "conversions"),
    "PMAX_003": ("cost", "conversion_value", "roas"),
    "PMAX_004": ("spend_share",),
    "PMAX_005": ("impressions",),
    "PMAX_006": ("enabled_asset_group_count",),
    "SEG_001": ("cost", "conversions"),
    "SEG_002": ("cost", "conversion_value", "roas"),
    "SEG_003": ("cost", "conversions"),
    "SEG_004": ("cost", "conversion_value", "roas"),
    "SEG_005": ("cost", "conversions"),
    "SEG_006": ("cost", "conversions"),
    "SEG_007": ("spend_share",),
    "TRACK_001": ("enabled_primary_or_included_conversion_actions",),
    "TRACK_002": ("enabled_primary_or_included_conversion_actions",),
    "TRACK_004": ("default_value",),
    "TRACK_005": ("always_use_default_value",),
    "TRACK_007": ("attribution_model",),
}


def validate_findings(
    raw_findings: list[dict],
    *,
    evidence_dir: Path,
    brand_terms: tuple[str, ...] = (),
) -> dict:
    audit_metadata = load_json(evidence_dir / "audit_metadata.json", default={})
    normalized_findings = [normalize_for_validation(finding, evidence_dir, audit_metadata) for finding in raw_findings]
    validated_findings: list[dict] = []
    rejected_findings: list[dict] = []

    for finding in normalized_findings:
        validation = evaluate_finding(finding, brand_terms=brand_terms)
        if validation["status"] == "rejected":
            rejected_findings.append(
                {
                    "original_finding": finding,
                    "rejection_reason": "; ".join(validation["reasons"]),
                    "missing_fields": validation.get("missing_fields", []),
                }
            )
            continue

        finding["confidence"] = validation["confidence"]
        finding["manual_validation_required"] = validation["manual_validation_required"]
        finding["validation"] = {
            "status": validation["status"],
            "reasons": validation["reasons"],
        }
        validated_findings.append(finding)

    summary = build_validation_summary(raw_findings, validated_findings, rejected_findings)
    write_json(evidence_dir / "validated_findings.json", validated_findings)
    write_json(evidence_dir / "rejected_findings.json", rejected_findings)
    write_json(evidence_dir / "validation_summary.json", summary)

    return {
        "validated_findings": validated_findings,
        "rejected_findings": rejected_findings,
        "validation_summary": summary,
    }


def normalize_for_validation(finding: dict, evidence_dir: Path, audit_metadata: dict) -> dict:
    checks = [dict(check) for check in (finding.get("triggered_checks") or finding.get("checks") or [])]
    check_ids = [str(check.get("check_id", "")) for check in checks if check.get("check_id")]
    severity = highest_severity(checks)
    context = build_context(finding)
    scope = normalize_scope(finding, context)
    entity_type = finding.get("entity_type") or ("campaign" if finding.get("campaign") else "account")
    entity_name = finding.get("entity_name") or finding.get("campaign") or "Account"
    campaign = finding.get("campaign")
    entity_id = entity_id_for_finding(scope, entity_type, entity_name, campaign, context)
    evidence = build_validation_evidence(
        scope=scope,
        entity_type=entity_type,
        check_ids=check_ids,
        context=context,
        finding=finding,
        evidence_dir=evidence_dir,
        audit_metadata=audit_metadata,
    )

    normalized = {
        "finding_id": finding_id(scope, entity_type, entity_id, entity_name, check_ids),
        "scope": scope,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "campaign": campaign,
        "severity": severity,
        "confidence": "low",
        "manual_validation_required": True,
        "triggered_checks": checks,
        "context": context,
        "evidence": evidence,
        "validation": {
            "status": "validated",
            "reasons": [],
        },
    }
    return {key: value for key, value in normalized.items() if value is not None}


def build_context(finding: dict) -> dict:
    context: dict[str, Any] = {}
    if finding.get("metrics"):
        context.update(finding["metrics"])
    if finding.get("campaign_setup"):
        context.update(finding["campaign_setup"])
        context["campaign_setup"] = finding["campaign_setup"]
    if finding.get("context"):
        context.update(finding["context"])
    for key in ("cost_change", "conv_change", "roas_change"):
        if key in finding:
            context[key] = finding[key]
    return context


def normalize_scope(finding: dict, context: dict) -> str:
    entity_type = finding.get("entity_type", "")
    scope = finding.get("scope")
    if entity_type == "conversion_action":
        return "conversion_action"
    if scope == "search_term":
        return "search_term"
    if scope == "pmax":
        return "pmax"
    if scope == "segment":
        return "segment"
    if scope == "account":
        return "account"
    if finding.get("campaign") or context.get("campaign_id"):
        return "campaign"
    return "account"


def entity_id_for_finding(scope: str, entity_type: str, entity_name: str, campaign: str | None, context: dict) -> str | None:
    for key in ("conversion_action_id", "asset_group_id", "campaign_id", "ad_group_id"):
        value = context.get(key)
        if value not in (None, ""):
            return str(value)
    if scope == "search_term":
        return "|".join(part for part in (campaign or "", context.get("ad_group_name", ""), entity_name) if part)
    if scope == "segment":
        campaign_id = str(context.get("campaign_id", campaign or ""))
        segment_value = str(context.get("segment_value", entity_name))
        return "|".join(part for part in (campaign_id, entity_type, segment_value) if part)
    if scope == "account":
        return "account"
    return None


def build_validation_evidence(
    *,
    scope: str,
    entity_type: str,
    check_ids: list[str],
    context: dict,
    finding: dict,
    evidence_dir: Path,
    audit_metadata: dict,
) -> dict:
    date_range = date_range_for_finding(scope, check_ids, audit_metadata)
    metrics = metrics_from_context(context)
    comparison_metrics = comparison_metrics_from_context(context)
    calculated_deltas = calculated_deltas_from_context(context)
    raw_entity_ids = raw_entity_ids_from_context(context)
    evidence_files = evidence_files_for_finding(scope, entity_type, check_ids, evidence_dir)

    return {
        "source_module": source_module_for_finding(scope, entity_type, check_ids),
        "period_label": date_range.get("period_label"),
        "start_date": date_range.get("start_date"),
        "end_date": date_range.get("end_date"),
        "metrics": metrics,
        "comparison_metrics": comparison_metrics,
        "calculated_deltas": calculated_deltas,
        "raw_entity_ids": raw_entity_ids,
        "evidence_files": evidence_files,
        "audit_metadata_file": str(evidence_dir / "audit_metadata.json"),
    }


def date_range_for_finding(scope: str, check_ids: list[str], audit_metadata: dict) -> dict:
    ranges = audit_metadata.get("date_ranges") or []
    default_range = ranges[0] if ranges else {}
    if any(check_id.startswith("PERF_") or check_id.startswith("STRUCT_") for check_id in check_ids):
        return default_range
    if scope in {"search_term", "pmax", "segment"}:
        return default_range
    if scope in {"account", "conversion_action"}:
        return {
            "period_label": "account_setup_snapshot",
            "start_date": audit_metadata.get("generated_at", "")[:10],
            "end_date": audit_metadata.get("generated_at", "")[:10],
        }
    return default_range


def source_module_for_finding(scope: str, entity_type: str, check_ids: list[str]) -> str:
    if scope == "search_term":
        return "search_terms"
    if scope == "pmax":
        return "pmax"
    if scope == "segment":
        return "segments"
    if scope == "conversion_action" or any(check_id.startswith("TRACK_") for check_id in check_ids):
        return "conversion_actions"
    if scope == "account" and entity_type == "account_tracking":
        return "conversion_actions"
    return "campaign_metrics"


def evidence_files_for_finding(scope: str, entity_type: str, check_ids: list[str], evidence_dir: Path) -> list[str]:
    if scope == "search_term":
        filenames = ["search_terms_30d.json"]
    elif scope == "pmax":
        filenames = ["pmax_asset_groups_30d.json", "google_ads_campaigns_30d.json"]
    elif scope == "segment":
        filenames = ["segments_30d.json"]
    elif scope == "conversion_action" or entity_type in {"conversion_action", "account_tracking"}:
        filenames = ["conversion_actions.json"]
    else:
        filenames = ["google_ads_campaigns_30d.json", "google_ads_campaigns_60d.json", "google_ads_campaigns_90d.json", "google_ads_campaigns_180d.json"]
    return [str(evidence_dir / filename) for filename in filenames]


def metrics_from_context(context: dict) -> dict:
    metric_keys = (
        "cost",
        "clicks",
        "impressions",
        "conversions",
        "conversion_value",
        "ctr",
        "average_cpc",
        "cpa",
        "roas",
        "spend_share",
        "last7_cost",
        "last7_conversions",
        "last7_conversion_value",
        "last7_impressions",
        "last7_roas",
        "last7_cpa",
        "enabled_primary_or_included_conversion_actions",
        "total_conversion_actions",
        "enabled_asset_group_count",
    )
    return {key: context[key] for key in metric_keys if key in context}


def comparison_metrics_from_context(context: dict) -> dict:
    keys = (
        "previous7_cost",
        "previous7_conversions",
        "previous7_conversion_value",
        "previous7_impressions",
        "previous7_roas",
        "previous7_cpa",
    )
    return {key: context[key] for key in keys if key in context}


def calculated_deltas_from_context(context: dict) -> dict:
    return {key: context[key] for key in ("cost_change", "conv_change", "roas_change") if key in context}


def raw_entity_ids_from_context(context: dict) -> dict:
    keys = ("campaign_id", "ad_group_id", "asset_group_id", "conversion_action_id")
    return {key: context[key] for key in keys if context.get(key) not in (None, "")}


def evaluate_finding(finding: dict, *, brand_terms: tuple[str, ...]) -> dict:
    reasons: list[str] = []
    missing_fields: list[str] = []
    check_ids = check_ids_for_finding(finding)
    context = finding.get("context", {})
    evidence = finding.get("evidence", {})
    severity = finding.get("severity")
    scope = finding.get("scope", "")

    required_top_fields = ("entity_name", "triggered_checks", "severity", "evidence")
    for field in required_top_fields:
        value = finding.get(field)
        if value in (None, "", []):
            missing_fields.append(field)

    if entity_id_required(finding) and not finding.get("entity_id"):
        missing_fields.append("entity_id")

    if evidence:
        for field in ("source_module",):
            if not evidence.get(field):
                missing_fields.append(f"evidence.{field}")
        if requires_date_range(check_ids, scope):
            for field in ("period_label", "start_date", "end_date"):
                if not evidence.get(field):
                    missing_fields.append(f"evidence.{field}")

    required_metric_fields = required_metrics(check_ids)
    for metric in required_metric_fields:
        if metric not in context and metric not in evidence.get("metrics", {}) and metric not in evidence.get("comparison_metrics", {}):
            missing_fields.append(f"metric.{metric}")

    if missing_fields:
        reasons.append("missing required validation fields")

    if any(check_id in BRAND_CHECK_IDS for check_id in check_ids) and not brand_terms:
        reasons.append("brand/non-brand finding requires configured brand terms")

    if any(check_id in ROAS_OR_VALUE_CHECK_IDS for check_id in check_ids) and conversion_value_missing_for_value_claim(context, evidence):
        reasons.append("ROAS or conversion value claim lacks reported conversion value evidence")

    if any(check_id in COMPARISON_CHECK_IDS for check_id in check_ids) and not evidence.get("comparison_metrics"):
        reasons.append("comparison finding lacks comparison metrics")

    if any(check_id in NAMING_ONLY_CHECK_IDS for check_id in check_ids) and severity in {"critical", "high"}:
        reasons.append("naming-convention-only finding cannot be high or critical severity")

    if reasons:
        return {
            "status": "rejected",
            "confidence": "low",
            "manual_validation_required": True,
            "reasons": reasons,
            "missing_fields": sorted(set(missing_fields)),
        }

    confidence = "high"
    status = "validated"
    validation_reasons: list[str] = []
    manual_validation_required = False

    if any(check_id in NAMING_ONLY_CHECK_IDS for check_id in check_ids):
        confidence = "low"
        status = "downgraded"
        manual_validation_required = True
        validation_reasons.append("naming convention signal requires manual validation")

    if scope in PARTIAL_API_SCOPES:
        confidence = min_confidence(confidence, "low" if scope == "pmax" else "medium")
        status = "downgraded" if confidence != "high" else status
        manual_validation_required = True
        validation_reasons.append(f"{scope} API evidence can have limited visibility")

    if any(check_id.startswith("TRACK_") or check_id.startswith("STRUCT_") for check_id in check_ids):
        confidence = min_confidence(confidence, "medium")
        status = "downgraded" if confidence != "high" else status
        manual_validation_required = True
        validation_reasons.append("settings evidence should be verified in the Google Ads UI")

    if any(check_id in ROAS_OR_VALUE_CHECK_IDS for check_id in check_ids):
        confidence = min_confidence(confidence, "medium")
        manual_validation_required = True
        validation_reasons.append("conversion value is reported value and is not yet GA4/revenue validated")

    return {
        "status": status,
        "confidence": confidence,
        "manual_validation_required": manual_validation_required,
        "reasons": validation_reasons,
        "missing_fields": [],
    }


def entity_id_required(finding: dict) -> bool:
    return finding.get("scope") not in {"account"}


def requires_date_range(check_ids: list[str], scope: str) -> bool:
    return scope in {"campaign", "search_term", "pmax", "segment"} or any(check_id.startswith(("PERF_", "QUERY_", "PMAX_", "SEG_")) for check_id in check_ids)


def required_metrics(check_ids: list[str]) -> tuple[str, ...]:
    metrics: list[str] = []
    for check_id in check_ids:
        metrics.extend(REQUIRED_METRICS_BY_CHECK.get(check_id, ()))
    return tuple(sorted(set(metrics)))


def conversion_value_missing_for_value_claim(context: dict, evidence: dict) -> bool:
    metrics = evidence.get("metrics", {})
    comparison = evidence.get("comparison_metrics", {})
    for key in ("conversion_value", "last7_conversion_value", "default_value"):
        if numeric_positive(context.get(key)) or numeric_positive(metrics.get(key)):
            return False
    for key in ("previous7_conversion_value",):
        if numeric_positive(context.get(key)) or numeric_positive(comparison.get(key)):
            return False
    return True


def numeric_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 0


def check_ids_for_finding(finding: dict) -> list[str]:
    return [
        str(check.get("check_id", ""))
        for check in finding.get("triggered_checks", [])
        if check.get("check_id")
    ]


def highest_severity(checks: list[dict]) -> str:
    if not checks:
        return ""
    return min(
        (str(check.get("severity", "low")).lower() for check in checks),
        key=lambda severity: SEVERITY_ORDER.get(severity, SEVERITY_ORDER["low"]),
    )


def min_confidence(current: str, candidate: str) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    return current if order[current] >= order[candidate] else candidate


def finding_id(scope: str, entity_type: str, entity_id: str | None, entity_name: str, check_ids: list[str]) -> str:
    basis = "|".join([scope, entity_type, str(entity_id or ""), entity_name, ",".join(sorted(check_ids))])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def build_validation_summary(raw_findings: list[dict], validated_findings: list[dict], rejected_findings: list[dict]) -> dict:
    confidence_counts = Counter(finding.get("confidence", "low") for finding in validated_findings)
    rejection_reasons = Counter()
    for rejected in rejected_findings:
        for reason in str(rejected.get("rejection_reason", "")).split("; "):
            if reason:
                rejection_reasons[reason] += 1

    return {
        "raw_findings_count": len(raw_findings),
        "validated_findings_count": len(validated_findings),
        "rejected_findings_count": len(rejected_findings),
        "high_confidence_count": confidence_counts.get("high", 0),
        "medium_confidence_count": confidence_counts.get("medium", 0),
        "low_confidence_count": confidence_counts.get("low", 0),
        "manual_validation_required_count": sum(
            1 for finding in validated_findings if finding.get("manual_validation_required")
        ),
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_reasons.most_common(10)
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
