from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checks import (
    generate_conversion_findings,
    generate_findings,
    generate_pmax_findings,
    generate_search_term_findings,
    generate_segment_findings,
    load_check_catalog,
)
from .claude_reporter import (
    ClaudeReporterError,
    build_findings_payload,
    generate_markdown_report,
    write_findings,
    write_report,
)
from .config import ConfigError, Settings, load_settings
from .config import ClientConfig, load_client_configs
from .conversions import ConversionActionQueryError, fetch_conversion_actions
from .google_docs_exporter import GoogleDocsExportError, export_markdown_report
from .google_ads_client import GoogleAdsClientError, build_google_ads_client
from .metrics import fetch_campaign_metrics
from .pmax import PMaxQueryError, fetch_pmax_asset_groups
from .search_terms import SearchTermQueryError, fetch_search_terms
from .segments import (
    SegmentQueryError,
    fetch_day_of_week_segments,
    fetch_device_segments,
    fetch_geo_segments,
    fetch_hour_of_day_segments,
)


def run() -> int:
    try:
        settings = load_settings()
        client_configs = load_client_configs(settings)
        client = build_google_ads_client(settings)
        check_catalog = load_check_catalog(settings.audit_checks_path)

        multi_client_mode = settings.clients_config_path.exists()
        summaries = []

        for client_config in client_configs:
            report_dir = client_report_dir(settings.reports_dir, client_config, multi_client_mode)
            try:
                summaries.append(
                    audit_client(
                        client,
                        client_config,
                        check_catalog,
                        settings,
                        report_dir,
                    )
                )
            except Exception as exc:  # Keep multi-client runs moving.
                if not multi_client_mode:
                    raise
                print(f"Client audit failed for {client_config.client_name}: {exc}", file=sys.stderr)
                summaries.append(
                    {
                        "client_name": client_config.client_name,
                        "findings_count": 0,
                        "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                        "high_priority_findings": 0,
                        "review_status": "failed",
                        "suggested_reviewers": ["PPC Specialist"],
                        "report_path": "",
                        "google_doc_url": None,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        if multi_client_mode:
            summary_path = write_run_summary(summaries, settings.reports_dir)
            print(f"\nRun summary saved to: {summary_path}")

        return 0

    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
    except GoogleAdsClientError as exc:
        print(f"Google Ads error: {exc}", file=sys.stderr)
    except ClaudeReporterError as exc:
        print(f"Claude reporting error: {exc}", file=sys.stderr)
    except FileNotFoundError as exc:
        print(f"File error: {exc}", file=sys.stderr)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON configuration: {exc}", file=sys.stderr)
    return 1


def audit_client(
    client,
    client_config: ClientConfig,
    check_catalog: dict[str, dict],
    settings: Settings,
    report_dir: Path,
) -> dict:
    warnings: list[str] = []
    customer_id = client_config.google_ads_customer_id

    print(f"\nRunning audit for {client_config.client_name} ({client_config.client_id})")

    campaign_data = fetch_campaign_metrics(client, customer_id)
    conversion_actions = []
    search_terms = []
    pmax_asset_groups = []
    geo_segments = []
    device_segments = []
    day_segments = []
    hour_segments = []

    try:
        conversion_actions = fetch_conversion_actions(client, customer_id)
    except ConversionActionQueryError as exc:
        warnings.append(f"conversion tracking audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        search_terms = fetch_search_terms(client, customer_id)
    except SearchTermQueryError as exc:
        warnings.append(f"search terms audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        pmax_asset_groups = fetch_pmax_asset_groups(client, customer_id)
    except PMaxQueryError as exc:
        warnings.append(f"Performance Max audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        geo_segments = fetch_geo_segments(client, customer_id)
    except SegmentQueryError as exc:
        warnings.append(f"geo segment audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        device_segments = fetch_device_segments(client, customer_id)
    except SegmentQueryError as exc:
        warnings.append(f"device segment audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        day_segments = fetch_day_of_week_segments(client, customer_id)
    except SegmentQueryError as exc:
        warnings.append(f"day-of-week segment audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    try:
        hour_segments = fetch_hour_of_day_segments(client, customer_id)
    except SegmentQueryError as exc:
        warnings.append(f"hour-of-day segment audit skipped: {exc}")
        print(f"Warning: {warnings[-1]}", file=sys.stderr)

    findings = generate_findings(campaign_data, check_catalog)
    findings.extend(generate_conversion_findings(conversion_actions, check_catalog, campaign_data))
    findings.extend(generate_search_term_findings(search_terms, check_catalog, client_config.brand_terms))
    findings.extend(generate_pmax_findings(campaign_data, pmax_asset_groups, check_catalog))
    findings.extend(
        generate_segment_findings(
            geo_segments,
            device_segments,
            day_segments,
            hour_segments,
            check_catalog,
        )
    )

    findings_payload = build_findings_payload(findings)
    findings_path = write_findings(findings_payload, report_dir)
    claude_findings = findings_payload["claude_findings"]
    review_metadata = build_review_metadata(client_config, findings_payload)

    print(
        "AI findings generated: "
        f"{findings_payload['summary']['raw_count']} raw, "
        f"{findings_payload['summary']['processed_count']} deduped, "
        f"{findings_payload['summary']['claude_payload_count']} sent to Claude."
    )
    print(f"Findings JSON saved to: {findings_path}")

    report = generate_markdown_report(
        settings.anthropic_api_key,
        claude_findings,
        client_context_for_prompt(client_config),
    )
    if "Claude report generation failed:" in report:
        warnings.append("Claude report generated from local fallback data.")
    report = add_review_workflow_section(report, review_metadata)
    report_path = write_report(report, report_dir)
    print(f"Audit report saved to: {report_path}")

    google_doc_url = None
    if settings.google_docs_export_enabled:
        try:
            google_doc_url = export_markdown_report(
                report_path,
                client_name=client_config.client_name,
                auth_mode=settings.google_docs_auth_mode,
                client_secret_file=settings.google_docs_client_secret_file,
                token_file=settings.google_docs_token_file,
                service_account_file=settings.google_service_account_file,
                parent_folder_id=settings.google_drive_parent_folder_id,
            )
            print(f"Google Doc exported: {google_doc_url}")
        except GoogleDocsExportError as exc:
            warnings.append(f"Google Docs export skipped: {exc}")
            print(f"Warning: {warnings[-1]}", file=sys.stderr)

    review_metadata["google_doc_url"] = google_doc_url
    review_status_path = write_review_status(review_metadata, report_dir)
    print(f"Review status saved to: {review_status_path}")

    status = "partial" if warnings else "success"
    return {
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "findings_count": findings_payload["summary"]["processed_count"],
        "counts": findings_payload["summary"]["processed_counts_by_severity"],
        "high_priority_findings": review_metadata["high_priority_findings"],
        "review_status": review_metadata["review_status"],
        "suggested_reviewers": review_metadata["required_reviewers"] + review_metadata["additional_reviewers"],
        "report_path": str(report_path),
        "google_doc_url": google_doc_url,
        "status": status,
        "warnings": warnings,
    }


def client_report_dir(reports_dir: Path, client_config: ClientConfig, multi_client_mode: bool) -> Path:
    if not multi_client_mode:
        return reports_dir
    return reports_dir / safe_path_component(client_config.client_id)


def safe_path_component(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
    return cleaned.strip("_") or "client"


def client_context_for_prompt(client_config: ClientConfig) -> dict:
    return {
        "client_name": client_config.client_name,
        "business_type": client_config.business_type,
        "currency": client_config.currency,
        "target_roas": client_config.target_roas,
        "target_cpa": client_config.target_cpa,
        "brand_terms": list(client_config.brand_terms[:5]),
        "brand_terms_count": len(client_config.brand_terms),
    }


def build_review_metadata(client_config: ClientConfig, findings_payload: dict) -> dict:
    processed_findings = findings_payload.get("processed_findings", [])
    counts = findings_payload["summary"]["processed_counts_by_severity"]
    has_tracking = has_tracking_findings(processed_findings)
    additional_reviewers = ["Analytics Specialist"] if has_tracking else []
    generated_at = datetime.now(timezone.utc)

    return {
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "google_ads_customer_id": client_config.google_ads_customer_id,
        "review_status": "internal_draft",
        "review_status_label": "Internal Draft",
        "generated_by": "Google Ads AI Audit Engine",
        "required_reviewers": ["PPC Specialist"],
        "additional_reviewers": additional_reviewers,
        "generated_at": generated_at.isoformat(),
        "generated_date": generated_at.date().isoformat(),
        "findings_count": findings_payload["summary"]["processed_count"],
        "high_priority_findings": counts.get("critical", 0) + counts.get("high", 0),
    }


def has_tracking_findings(findings: list[dict]) -> bool:
    for finding in findings:
        for check in finding.get("triggered_checks", []):
            if check.get("category") in {"tracking", "attribution"}:
                return True
            if str(check.get("check_id", "")).startswith("TRACK_"):
                return True
    return False


def add_review_workflow_section(report: str, metadata: dict) -> str:
    reviewers = metadata["required_reviewers"] + metadata["additional_reviewers"]
    additional_reviewer = ", ".join(metadata["additional_reviewers"]) if metadata["additional_reviewers"] else "Not required from automated findings"

    section = "\n".join(
        [
            "## Review Metadata",
            f"- Review status: {metadata['review_status_label']}",
            f"- Generated by: {metadata['generated_by']}",
            f"- Required reviewer: {', '.join(metadata['required_reviewers'])}",
            f"- Additional reviewer: {additional_reviewer}",
            f"- Generated date: {metadata['generated_date']}",
            f"- Client name: {metadata['client_name']}",
            f"- Google Ads customer ID: {metadata['google_ads_customer_id']}",
            f"- Suggested reviewers: {', '.join(reviewers)}",
            "",
            "**No account changes were made automatically. Recommendations require human validation.**",
            "",
            "## Human Review Checklist",
            "- [ ] Verify conversion tracking findings in Google Ads UI",
            "- [ ] Validate any ROAS / CPA anomalies against actual business data",
            "- [ ] Review search term negatives before applying",
            "- [ ] Confirm PMax recommendations manually before restructuring",
            "- [ ] Check recent account change history",
            "- [ ] Remove or rewrite anything not suitable for client delivery",
            "- [ ] Approve final version before sharing with client",
            "",
        ]
    )

    lines = report.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join([lines[0], "", section, *lines[1:]]).strip() + "\n"
    return f"# Google Ads AI Audit Report\n\n{section}{report}".strip() + "\n"


def write_review_status(metadata: dict, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "latest_review_status.json"
    output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return output


def write_run_summary(summaries: list[dict], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "run_summary.md"
    lines = [
        "# Google Ads AI Audit Run Summary",
        "",
        "| Client | Findings | High/Critical | Google Doc | Review Status | Suggested Reviewers | Report | Status |",
        "|---|---:|---:|---|---|---|---|---|",
    ]

    for summary in summaries:
        report_path = summary.get("report_path") or ""
        report_link = f"[Report]({report_path})" if report_path else "Not generated"
        google_doc_url = summary.get("google_doc_url")
        google_doc_link = f"[Google Doc]({google_doc_url})" if google_doc_url else "Not exported"
        reviewers = ", ".join(summary.get("suggested_reviewers") or ["PPC Specialist"])
        lines.append(
            "| {client} | {findings} | {high_priority} | {google_doc} | {review_status} | {reviewers} | {report} | {status} |".format(
                client=summary.get("client_name", "Unknown client"),
                findings=summary.get("findings_count", 0),
                high_priority=summary.get("high_priority_findings", 0),
                google_doc=google_doc_link,
                review_status=summary.get("review_status", "internal_draft"),
                reviewers=reviewers,
                report=report_link,
                status=summary.get("status", "failed"),
            )
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    raise SystemExit(run())
