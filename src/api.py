from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .checks import load_check_catalog
from .config import ClientConfig, ConfigError, load_settings
from .google_ads_client import GoogleAdsClientError, build_google_ads_client
from .main import (
    apply_client_notification,
    client_report_dir,
    notification_config_from_settings,
    run_audit_for_client,
)


app = FastAPI(title="Google Ads AI Audit Engine")


class AuditRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_name: str = Field(..., min_length=1)
    google_ads_customer_id: str = Field(..., min_length=1)
    brand_terms: list[str] = Field(default_factory=list)
    business_type: str | None = None
    currency: str | None = None
    target_roas: float | None = None
    target_cpa: float | None = None
    zoho_task_id: str | None = None


@app.post("/run-audit")
def run_audit(request_body: AuditRequest, x_audit_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    try:
        settings = load_settings()
        validate_api_key(settings.audit_api_key, x_audit_api_key)

        client_config = ClientConfig(
            client_id=request_body.client_id,
            client_name=request_body.client_name,
            google_ads_customer_id=request_body.google_ads_customer_id,
            brand_terms=tuple(term.strip().lower() for term in request_body.brand_terms if term.strip()),
            business_type=request_body.business_type,
            currency=request_body.currency,
            target_roas=request_body.target_roas,
            target_cpa=request_body.target_cpa,
        )

        client = build_google_ads_client(settings)
        check_catalog = load_check_catalog(settings.audit_checks_path)
        report_dir = client_report_dir(settings.reports_dir, client_config, multi_client_mode=True)
        summary = run_audit_for_client(client, client_config, check_catalog, settings, report_dir)
        apply_client_notification(summary, notification_config_from_settings(settings))
        return build_success_response(summary, client_config, request_body.zoho_task_id)
    except HTTPException:
        raise
    except (ConfigError, GoogleAdsClientError, FileNotFoundError) as exc:
        return build_failure_response(str(exc), request_body)
    except Exception as exc:
        return build_failure_response(str(exc), request_body)


def validate_api_key(expected_api_key: str | None, provided_api_key: str | None) -> None:
    if expected_api_key and provided_api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Audit-Api-Key header.")


def build_success_response(summary: dict, client_config: ClientConfig, zoho_task_id: str | None) -> dict:
    return {
        "status": "success" if summary.get("status") in {None, "success", "partial"} else summary.get("status"),
        "client_id": client_config.client_id,
        "client_name": client_config.client_name,
        "google_ads_customer_id": client_config.google_ads_customer_id,
        "google_doc_url": summary.get("google_doc_url"),
        "local_report_path": summary.get("report_path"),
        "findings_path": summary.get("findings_path"),
        "evidence_path": summary.get("evidence_path"),
        "findings_count": summary.get("findings_count", 0),
        "high_critical_findings": summary.get("high_priority_findings", 0),
        "review_status": summary.get("review_status", "internal_draft"),
        "required_reviewers": summary.get("suggested_reviewers", ["PPC Specialist"]),
        "zoho_task_id": zoho_task_id,
        "telegram_notification_sent": bool(summary.get("notification_sent")),
    }


def build_failure_response(error: str, request_body: AuditRequest) -> dict:
    return {
        "status": "failed",
        "error": error,
        "client_id": request_body.client_id,
        "zoho_task_id": request_body.zoho_task_id,
    }
