from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from anthropic import Anthropic


class ClaudeReporterError(Exception):
    """Raised when Claude reporting fails."""


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MEDIUM_FINDING_LIMIT = 20
LOW_FINDING_LIMIT = 10


def build_prompt(findings: list[dict], client_context: dict | None = None) -> str:
    context = client_context or {}
    return f"""
You are a senior UAATEAM-style Google Ads auditor. Produce a concise, prioritized, actionable markdown report.

Hard rules:
- Use only the provided findings.
- Do not invent numbers.
- Do not invent campaigns, search terms, conversion actions, asset groups, or segments.
- If evidence is missing, say what needs manual validation.
- Avoid repeating the same issue multiple times.
- Merge duplicate or closely related findings into one recommendation when appropriate.
- Be direct and professional.
- Prioritize business impact over technical detail.
- Do not produce a huge report.
- Prefer practical action items over explanation.
- Always include all seven top-level sections exactly as listed below.
- If space is tight, summarize groups of similar findings instead of adding more detail.

Client context:
{json.dumps(context, indent=2)}

Use this exact markdown structure:

# Google Ads AI Audit Report

## 1. Executive Summary
- 3-5 concise bullets.
- Mention only the most important account-level risks/opportunities.
- Avoid generic advice.

## 2. Priority Action Plan
Create a table with:
| Priority | Issue | Impact | Recommended Action | Owner |
Owner must be one of:
- PPC Specialist
- Analytics Specialist
- Creative Specialist
- CRO/Website Specialist
- Client/Business Owner

## 3. Critical Issues
Only include high/critical severity findings.
For each issue include:
- What happened
- Why it matters
- Evidence from data
- Recommended action
- Expected impact

## 4. Optimization Opportunities
Include medium/low severity findings that are useful but not urgent.
Group by:
- Campaign structure
- Tracking and measurement
- Search terms
- Performance Max
- Geo/device/schedule
- Budget allocation

## 5. Tracking & Measurement Risks
Summarize conversion tracking and attribution-related findings.
If no tracking findings exist, explicitly state that no major tracking issue was detected from the available data, but deeper manual validation may still be required.

## 6. Recommended Next 7 Days
Give a practical checklist of actions for the next week.
Limit to 5-8 actions.
Each action should be specific and tied to a finding.

## 7. Data Limitations
Mention:
- Audit is based on API-accessible data only.
- Some checks require manual validation.
- Recommendations should be reviewed before implementation.
- No automatic account changes were made.

Findings JSON:
{json.dumps(findings, indent=2)}
""".strip()


def generate_markdown_report(api_key: str, findings: list[dict], client_context: dict | None = None) -> str:
    if not findings:
        return build_fallback_report([], "No findings generated.")

    try:
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4500,
            messages=[{"role": "user", "content": build_prompt(findings, client_context)}],
        )
        return message.content[0].text
    except Exception as exc:
        return build_fallback_report(findings, f"Claude API request failed: {exc}")


def build_findings_payload(findings: list[dict]) -> dict:
    processed_findings, claude_findings = prepare_findings(findings)
    return {
        "summary": {
            "raw_count": len(findings),
            "processed_count": len(processed_findings),
            "claude_payload_count": len(claude_findings),
            "processed_counts_by_severity": severity_counts(processed_findings),
            "claude_counts_by_severity": severity_counts(claude_findings),
        },
        "raw_findings": findings,
        "processed_findings": processed_findings,
        "claude_findings": claude_findings,
    }


def prepare_findings(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    normalized = [normalize_finding(finding) for finding in findings]
    deduped = dedupe_findings(normalized)
    sorted_findings = sorted(deduped, key=finding_sort_key)
    limited = limit_findings_for_claude(sorted_findings)
    return sorted_findings, limited


def normalize_finding(finding: dict) -> dict:
    checks = finding.get("triggered_checks") or finding.get("checks") or []
    normalized_checks = [dict(check) for check in checks]
    severity = highest_severity(normalized_checks)
    context = {}
    if finding.get("metrics"):
        context.update(finding["metrics"])
    if finding.get("campaign_setup"):
        context["campaign_setup"] = finding["campaign_setup"]
    if finding.get("context"):
        context.update(finding["context"])
    campaign = finding.get("campaign")
    entity_name = finding.get("entity_name") or finding.get("campaign") or "Account"
    entity_type = finding.get("entity_type") or ("campaign" if finding.get("campaign") else "account")
    scope = finding.get("scope") or ("campaign" if finding.get("campaign") else "account")

    normalized = {
        "scope": scope,
        "entity_type": entity_type,
        "entity_name": entity_name,
        "campaign": campaign,
        "severity": severity,
        "triggered_checks": normalized_checks,
        "context": context,
        "evidence": build_evidence(finding, context),
    }

    return {key: value for key, value in normalized.items() if value is not None}


def build_evidence(finding: dict, context: dict) -> dict:
    evidence = {}

    for key in (
        "cost_change",
        "conv_change",
        "roas_change",
    ):
        if key in finding:
            evidence[key] = finding[key]

    for key in (
        "cost",
        "clicks",
        "impressions",
        "conversions",
        "conversion_value",
        "ctr",
        "cpa",
        "roas",
        "spend_share",
        "last7_cost",
        "previous7_cost",
        "last7_conversions",
        "previous7_conversions",
        "last7_conversion_value",
        "previous7_conversion_value",
        "last7_roas",
        "previous7_roas",
        "last7_cpa",
        "previous7_cpa",
    ):
        if key in context:
            evidence[key] = context[key]

    return evidence


def dedupe_findings(findings: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict] = []

    for finding in findings:
        unique_checks = []
        for check in finding["triggered_checks"]:
            check_id = check.get("check_id", "")
            key = (
                finding.get("scope", ""),
                finding.get("entity_type", ""),
                str(finding.get("campaign", "")),
                str(finding.get("entity_name", "")),
                check_id,
            )
            if key in seen:
                continue
            seen.add(key)
            unique_checks.append(check)

        if unique_checks:
            finding = dict(finding)
            finding["triggered_checks"] = unique_checks
            finding["severity"] = highest_severity(unique_checks)
            deduped.append(finding)

    return deduped


def limit_findings_for_claude(findings: list[dict]) -> list[dict]:
    buckets = {"critical": [], "high": [], "medium": [], "low": []}

    for finding in findings:
        buckets.setdefault(finding["severity"], []).append(finding)

    return (
        buckets["critical"]
        + buckets["high"]
        + buckets["medium"][:MEDIUM_FINDING_LIMIT]
        + buckets["low"][:LOW_FINDING_LIMIT]
    )


def highest_severity(checks: list[dict]) -> str:
    if not checks:
        return "low"

    return min(
        (str(check.get("severity", "low")).lower() for check in checks),
        key=lambda severity: SEVERITY_ORDER.get(severity, SEVERITY_ORDER["low"]),
    )


def finding_sort_key(finding: dict) -> tuple[int, float]:
    severity_rank = SEVERITY_ORDER.get(finding.get("severity", "low"), SEVERITY_ORDER["low"])
    evidence = finding.get("evidence", {})
    context = finding.get("context", {})
    impact_value = first_number(
        evidence,
        context,
        ("cost", "last7_cost", "cost_change", "conversion_value", "last7_conversion_value", "spend_share"),
    )
    return severity_rank, -impact_value


def first_number(evidence: dict, context: dict, keys: tuple[str, ...]) -> float:
    for source in (evidence, context):
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return 0


def severity_counts(findings: list[dict]) -> dict[str, int]:
    counts = Counter(finding.get("severity", "low") for finding in findings)
    return {severity: counts.get(severity, 0) for severity in ("critical", "high", "medium", "low")}


def build_fallback_report(findings: list[dict], error_message: str) -> str:
    counts = Counter(finding.get("severity", "low") for finding in findings)
    top_findings = findings[:10]

    lines = [
        "# Google Ads AI Audit Report",
        "",
        "## 1. Executive Summary",
        f"- Claude report generation failed: {error_message}",
        "- A fallback report was generated from local finding data.",
        "- Review the top findings below before making account changes.",
        "",
        "## 2. Priority Action Plan",
        "| Priority | Issue | Impact | Recommended Action | Owner |",
        "|---|---|---|---|---|",
    ]

    if top_findings:
        for index, finding in enumerate(top_findings[:8], start=1):
            issue = check_names(finding)
            impact = fallback_evidence_summary(finding)
            lines.append(
                f"| {index} | {issue} | {impact} | Review the finding context and validate before applying changes. | PPC Specialist |"
            )
    else:
        lines.append("| 1 | No findings available | No automated finding data was available. | Re-run the audit after data access is restored. | PPC Specialist |")

    lines.extend(
        [
            "",
            "## 3. Critical Issues",
        ]
    )

    critical = [
        finding
        for finding in findings
        if finding.get("severity") in {"critical", "high"}
    ]
    if critical:
        for finding in critical[:10]:
            lines.extend(
                [
                    f"### {check_names(finding)}",
                    f"- What happened: {finding.get('entity_name', 'Account')} triggered {check_ids(finding)}.",
                    f"- Why it matters: {check_why_it_matters(finding)}",
                    f"- Evidence from data: {fallback_evidence_summary(finding)}",
                    "- Recommended action: Review the check recommendation and validate against the account before making changes.",
                    "- Expected impact: Reduce waste, improve measurement quality, or improve prioritization depending on the finding.",
                    "",
                ]
            )
    else:
        lines.append("No high or critical findings were available in the processed findings.")

    lines.extend(
        [
            "",
            "## 4. Optimization Opportunities",
            "Medium and low severity opportunities are available in `reports/latest_findings.json` for review.",
            "",
            "## 5. Tracking & Measurement Risks",
            tracking_summary(findings),
            "",
            "## 6. Recommended Next 7 Days",
        ]
    )

    for finding in top_findings[:8]:
        lines.append(f"- Review `{finding.get('entity_name', 'Account')}` for {check_names(finding)}.")

    if not top_findings:
        lines.append("- Re-run the audit when API/reporting access is available.")

    lines.extend(
        [
            "",
            "## 7. Data Limitations",
            "- Audit is based on API-accessible data only.",
            "- Some checks require manual validation.",
            "- Recommendations should be reviewed before implementation.",
            "- No automatic account changes were made.",
            "",
            "## Finding Counts By Severity",
        ]
    )

    for severity in ("critical", "high", "medium", "low"):
        lines.append(f"- {severity}: {counts.get(severity, 0)}")

    return "\n".join(lines)


def tracking_summary(findings: list[dict]) -> str:
    tracking_findings = [
        finding
        for finding in findings
        if any(
            check.get("category") in {"tracking", "attribution"}
            for check in finding.get("triggered_checks", [])
        )
    ]
    if not tracking_findings:
        return "No major tracking issue was detected from the available data, but deeper manual validation may still be required."

    names = ", ".join(check_names(finding) for finding in tracking_findings[:5])
    return f"Tracking or attribution findings were detected: {names}."


def check_names(finding: dict) -> str:
    names = [check.get("name", check.get("check_id", "Unknown issue")) for check in finding.get("triggered_checks", [])]
    return "; ".join(names) if names else "Unknown issue"


def check_ids(finding: dict) -> str:
    ids = [check.get("check_id", "unknown") for check in finding.get("triggered_checks", [])]
    return ", ".join(ids)


def check_why_it_matters(finding: dict) -> str:
    reasons = [check.get("why_it_matters", "") for check in finding.get("triggered_checks", []) if check.get("why_it_matters")]
    return reasons[0] if reasons else "This may affect account performance or measurement quality."


def fallback_evidence_summary(finding: dict) -> str:
    evidence = finding.get("evidence", {})
    if not evidence:
        return "See finding context."

    parts = [f"{key}: {value}" for key, value in list(evidence.items())[:4]]
    return ", ".join(parts)


def write_findings(findings_payload: dict, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "latest_findings.json"
    output.write_text(json.dumps(findings_payload, indent=2), encoding="utf-8")
    return output


def write_report(report_markdown: str, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "latest_audit.md"
    output.write_text(report_markdown, encoding="utf-8")
    return output
