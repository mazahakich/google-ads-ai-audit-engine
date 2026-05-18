from __future__ import annotations

import json
import sys

from .checks import (
    generate_conversion_findings,
    generate_findings,
    generate_pmax_findings,
    generate_search_term_findings,
    load_check_catalog,
)
from .claude_reporter import ClaudeReporterError, generate_markdown_report, write_report
from .config import ConfigError, load_settings
from .conversions import ConversionActionQueryError, fetch_conversion_actions
from .google_ads_client import GoogleAdsClientError, build_google_ads_client
from .metrics import fetch_campaign_metrics
from .pmax import PMaxQueryError, fetch_pmax_asset_groups
from .search_terms import SearchTermQueryError, fetch_search_terms


def run() -> int:
    try:
        settings = load_settings()
        client = build_google_ads_client(settings)
        campaign_data = fetch_campaign_metrics(client, settings.google_ads_customer_id)
        conversion_actions = []
        search_terms = []
        pmax_asset_groups = []

        try:
            conversion_actions = fetch_conversion_actions(client, settings.google_ads_customer_id)
        except ConversionActionQueryError as exc:
            print(f"Warning: conversion tracking audit skipped: {exc}", file=sys.stderr)

        try:
            search_terms = fetch_search_terms(client, settings.google_ads_customer_id)
        except SearchTermQueryError as exc:
            print(f"Warning: search terms audit skipped: {exc}", file=sys.stderr)

        try:
            pmax_asset_groups = fetch_pmax_asset_groups(client, settings.google_ads_customer_id)
        except PMaxQueryError as exc:
            print(f"Warning: Performance Max audit skipped: {exc}", file=sys.stderr)

        check_catalog = load_check_catalog(settings.audit_checks_path)
        findings = generate_findings(campaign_data, check_catalog)
        findings.extend(generate_conversion_findings(conversion_actions, check_catalog, campaign_data))
        findings.extend(generate_search_term_findings(search_terms, check_catalog, settings.brand_terms))
        findings.extend(generate_pmax_findings(campaign_data, pmax_asset_groups, check_catalog))

        print("\nAI FINDINGS JSON\n")
        print(json.dumps(findings, indent=2))

        report = generate_markdown_report(settings.anthropic_api_key, findings)
        path = write_report(report, settings.reports_dir)
        print(f"\nAudit report saved to: {path}")
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


if __name__ == "__main__":
    raise SystemExit(run())
