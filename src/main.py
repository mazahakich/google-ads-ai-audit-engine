from __future__ import annotations

import json
import sys

from .checks import generate_findings, load_check_catalog
from .claude_reporter import ClaudeReporterError, generate_markdown_report, write_report
from .config import ConfigError, load_settings
from .google_ads_client import GoogleAdsClientError, build_google_ads_client
from .metrics import fetch_campaign_metrics


def run() -> int:
    try:
        settings = load_settings()
        client = build_google_ads_client(settings)
        campaign_data = fetch_campaign_metrics(client, settings.google_ads_customer_id)
        check_catalog = load_check_catalog(settings.audit_checks_path)
        findings = generate_findings(campaign_data, check_catalog)

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
