from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic


class ClaudeReporterError(Exception):
    """Raised when Claude reporting fails."""


def build_prompt(findings: list[dict]) -> str:
    return f"""
You are a senior Google Ads auditor.

Analyze the structured Google Ads audit findings below.
Use only the provided data. Do not invent numbers.
For each issue, explain:
1. What happened
2. Why it matters
3. Recommended action
4. Priority

Client context:
- Business type: ecommerce / lead generation
- Period comparison: last 7 days vs previous 7 days

Findings JSON:
{json.dumps(findings, indent=2)}

Findings may be campaign-level, account-level, or conversion-action-level. Use the scope,
entity type, campaign setup, metrics, and context fields when present.
""".strip()


def generate_markdown_report(api_key: str, findings: list[dict]) -> str:
    if not findings:
        raise ClaudeReporterError("No findings generated. Claude summary skipped.")

    try:
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": build_prompt(findings)}],
        )
        summary = message.content[0].text
    except Exception as exc:
        raise ClaudeReporterError(f"Claude API request failed: {exc}") from exc

    return "\n".join([
        "# Google Ads Audit Report",
        "",
        "## AI Summary",
        summary,
        "",
        "## Structured Findings",
        "```json",
        json.dumps(findings, indent=2),
        "```",
    ])


def write_report(report_markdown: str, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "latest_audit.md"
    output.write_text(report_markdown, encoding="utf-8")
    return output
