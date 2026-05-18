from __future__ import annotations

import json
import sys
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
from .config import ConfigError, load_settings
from .config import ClientConfig, load_client_configs
from .conversions import ConversionActionQueryError, fetch_conversion_actions
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
                        settings.anthropic_api_key,
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
                        "report_path": "",
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
    anthropic_api_key: str,
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

    print(
        "AI findings generated: "
        f"{findings_payload['summary']['raw_count']} raw, "
        f"{findings_payload['summary']['processed_count']} deduped, "
        f"{findings_payload['summary']['claude_payload_count']} sent to Claude."
    )
    print(f"Findings JSON saved to: {findings_path}")

    report = generate_markdown_report(
        anthropic_api_key,
        claude_findings,
        client_context_for_prompt(client_config),
    )
    if "Claude report generation failed:" in report:
        warnings.append("Claude report generated from local fallback data.")
    report_path = write_report(report, report_dir)
    print(f"Audit report saved to: {report_path}")

    status = "partial" if warnings else "success"
    return {
        "client_name": client_config.client_name,
        "findings_count": findings_payload["summary"]["processed_count"],
        "counts": findings_payload["summary"]["processed_counts_by_severity"],
        "report_path": str(report_path),
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


def write_run_summary(summaries: list[dict], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "run_summary.md"
    lines = [
        "# Google Ads AI Audit Run Summary",
        "",
        "| Client | Findings | Critical | High | Medium | Low | Report | Status |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]

    for summary in summaries:
        counts = summary.get("counts", {})
        report_path = summary.get("report_path") or ""
        report_link = f"[Report]({report_path})" if report_path else "Not generated"
        lines.append(
            "| {client} | {findings} | {critical} | {high} | {medium} | {low} | {report} | {status} |".format(
                client=summary.get("client_name", "Unknown client"),
                findings=summary.get("findings_count", 0),
                critical=counts.get("critical", 0),
                high=counts.get("high", 0),
                medium=counts.get("medium", 0),
                low=counts.get("low", 0),
                report=report_link,
                status=summary.get("status", "failed"),
            )
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    raise SystemExit(run())
