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

## Google Docs Export

Google Docs export is optional. Local markdown and JSON reports are always generated first, and Docs export failures are logged as warnings without stopping the audit.

Add these settings to `.env` when you want Google Docs export:

```bash
GOOGLE_DOCS_EXPORT_ENABLED=true
GOOGLE_DOCS_AUTH_MODE=oauth
GOOGLE_DOCS_CLIENT_SECRET_FILE=google_docs_client_secret.json
GOOGLE_DOCS_TOKEN_FILE=google_docs_token.json
GOOGLE_DRIVE_PARENT_FOLDER_ID=
```

Setup steps:

1. In Google Cloud, create or choose a project for reporting automation.
2. Enable the Google Docs API and Google Drive API for that project.
3. Create an OAuth Client ID of type Desktop App.
4. Download the OAuth JSON and save it locally as `google_docs_client_secret.json`.
5. Do not commit `google_docs_client_secret.json` or `google_docs_token.json`.
6. On the first run, the app opens a browser for Google login and saves `google_docs_token.json` locally.
7. Created Docs belong to the authenticated Google user account.
8. If exporting into a specific Drive folder, copy the folder ID from the Google Drive URL and set `GOOGLE_DRIVE_PARENT_FOLDER_ID`. For example, this folder URL:

```text
https://drive.google.com/drive/u/2/folders/11iGQRLOOZfMpc3lC-BZskoVLBHN2hZ86
```

uses:

```bash
GOOGLE_DRIVE_PARENT_FOLDER_ID=11iGQRLOOZfMpc3lC-BZskoVLBHN2hZ86
```

9. Run:

```bash
python3 -m src.main
```

Single-client mode prints the Google Doc URL when export succeeds. Multi-client mode exports each client report separately and includes the Google Doc URL in `reports/run_summary.md`.

Google Docs export creates a review-ready internal draft, not a final client-approved report. It applies basic markdown-to-doc formatting for headings, bullets, bold labels, priority labels, and simple tables. The Priority Action Plan is converted into clean action blocks instead of a raw pipe table. If formatting fails, the exporter falls back to plain markdown insertion so the audit still completes.

Service account export remains available for older setups by setting:

```bash
GOOGLE_DOCS_AUTH_MODE=service_account
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

For service account mode, share the destination Drive folder with the service account email address using Editor access. OAuth mode is recommended when Docs should be created under a normal Google user account.
