# Google Ads AI Audit Engine

Python audit runner for Google Ads accounts. It pulls API-accessible account data, generates structured findings across the current audit modules, sends prioritized findings to Claude, and writes markdown/JSON reports.

## Single-Client Mode

Single-client mode remains the default when `clients.json` is not present.

1. Copy `.env.example` to `.env`.
2. Set the existing credential variables and `GOOGLE_ADS_CUSTOMER_ID`.
3. Optionally set `BRAND_TERMS` as a comma-separated list.
4. Run:

```bash
python3 -m src.main
```

Outputs:

- `reports/latest_audit.md`
- `reports/latest_findings.json`

## Multi-Client Mode

Multi-client mode is enabled when the configured clients file exists. By default the app looks for:

```bash
clients.json
```

You can change the path with:

```bash
CLIENTS_CONFIG_PATH=clients.json
```

Create `clients.json` using `clients.example.json` as the template:

```json
[
  {
    "client_id": "demo_client",
    "client_name": "Demo Client",
    "google_ads_customer_id": "1234567890",
    "brand_terms": ["demo brand", "demobrand"],
    "business_type": "ecommerce",
    "currency": "USD",
    "target_roas": 3.0,
    "target_cpa": null,
    "notes": "Example client config. Do not put secrets here."
  }
]
```

`clients.json` is intentionally ignored by git. It may contain real customer IDs and internal client notes, but it must not contain API secrets.

Run the same command:

```bash
python3 -m src.main
```

Outputs:

- `reports/{client_id}/latest_audit.md`
- `reports/{client_id}/latest_findings.json`
- `reports/run_summary.md`

If one client fails in multi-client mode, the runner records the failure in `reports/run_summary.md` and continues with the next client.

## Brand Terms

Brand terms are used only for brand/non-brand search term checks.

Priority:

1. `brand_terms` in `clients.json`
2. `BRAND_TERMS` in `.env`
3. No brand terms, which skips brand/non-brand query checks gracefully

## Client Context

The Claude report receives non-secret client context where available:

- client name
- business type
- currency
- target ROAS
- target CPA
- limited brand term context

No automatic account changes are made by this audit engine.
