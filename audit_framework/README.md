# Manual Audit Pattern Framework

This folder stores source material from manual Google Ads audits so recurring human audit patterns can be translated into future automated checks.

These files are not connected to the runtime audit engine yet. They are intended as a reference layer for planning and prioritizing new checks.

## Files

- `manual_audit_patterns.schema.json`: JSON Schema for manual audit pattern records.
- `manual_audit_patterns.json`: Starter library of reusable Google Ads audit patterns.

## How To Use

Add a new pattern when a manual audit insight appears repeatedly across clients. Keep the language practical and implementation-oriented:

- `how_to_detect` should describe what an auditor looks for or how automation could detect it.
- `data_required` should list Google Ads API fields, report segments, or external data needed.
- `implementation_status` should show whether the pattern is only source material or already represented by automated checks.
- `related_check_ids` should reference existing checks in `audit_checks.json` when applicable.

This framework should help turn manual judgment into clear, testable audit signals without changing the running audit pipeline until a pattern is intentionally promoted into code.
