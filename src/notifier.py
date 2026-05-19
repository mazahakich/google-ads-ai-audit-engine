from __future__ import annotations

from dataclasses import dataclass
from urllib import error, parse, request


class NotificationError(Exception):
    """Raised when an audit notification cannot be sent."""


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool
    channel: str
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def notify_client_audit(summary: dict, config: NotificationConfig) -> dict:
    if not config.enabled:
        return notification_result(False, config.channel)

    message = build_client_message(summary)
    send_message(message, config)
    return notification_result(True, config.channel)


def notify_run_summary(summaries: list[dict], config: NotificationConfig) -> dict:
    if not config.enabled:
        return notification_result(False, config.channel)

    total_clients = len(summaries)
    successful = sum(1 for summary in summaries if summary.get("status") in {"success", "partial"})
    failed = sum(1 for summary in summaries if summary.get("status") == "failed")
    high_critical = sum(int(summary.get("high_priority_findings", 0)) for summary in summaries)

    message = "\n".join(
        [
            "Google Ads AI Audit Run Summary",
            "",
            f"Total clients: {total_clients}",
            f"Successful: {successful}",
            f"Failed: {failed}",
            f"Total high/critical findings: {high_critical}",
            "",
            "Next step: PPC specialist should review and approve before client delivery.",
        ]
    )
    send_message(message, config)
    return notification_result(True, config.channel)


def notify_text(message: str, config: NotificationConfig) -> dict:
    if not config.enabled:
        return notification_result(False, config.channel)
    send_message(message, config)
    return notification_result(True, config.channel)


def build_client_message(summary: dict) -> str:
    reviewers = ", ".join(summary.get("suggested_reviewers") or ["PPC Specialist"])
    google_doc_url = summary.get("google_doc_url") or "Not exported"
    local_report_path = summary.get("report_path") or "Not generated"

    return "\n".join(
        [
            "Google Ads AI Audit Generated",
            "",
            f"Client: {summary.get('client_name', 'Unknown client')}",
            "Review status: Internal Draft",
            f"Findings: {summary.get('findings_count', 0)}",
            f"High/Critical findings: {summary.get('high_priority_findings', 0)}",
            f"Required reviewers: {reviewers}",
            f"Google Doc: {google_doc_url}",
            f"Local report: {local_report_path}",
            "",
            "Next step: PPC specialist should review and approve before client delivery.",
        ]
    )


def send_message(message: str, config: NotificationConfig) -> None:
    if config.channel != "telegram":
        raise NotificationError(f"Unsupported notification channel: {config.channel}. Only telegram is supported.")
    send_telegram_message(message, config.telegram_bot_token, config.telegram_chat_id)


def send_telegram_message(message: str, bot_token: str | None, chat_id: str | None) -> None:
    if not bot_token:
        raise NotificationError("TELEGRAM_BOT_TOKEN is required when Telegram notifications are enabled.")
    if not chat_id:
        raise NotificationError("TELEGRAM_CHAT_ID is required when Telegram notifications are enabled.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    response = execute_request(req, "Telegram")
    if response:
        try:
            import json

            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise NotificationError("Telegram notification response was not valid JSON.") from exc
        if payload.get("ok") is not True:
            description = payload.get("description", "unknown Telegram API error")
            raise NotificationError(f"Telegram notification failed: {description}")


def execute_request(req: request.Request, label: str) -> str:
    try:
        with request.urlopen(req, timeout=10) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise NotificationError(f"{label} notification failed with HTTP status {status}.")
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise NotificationError(f"{label} notification failed with HTTP {exc.code}.") from exc
    except error.URLError as exc:
        raise NotificationError(f"{label} notification request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise NotificationError(f"{label} notification timed out.") from exc


def notification_result(sent: bool, channel: str, error_message: str | None = None) -> dict:
    return {
        "notification_sent": sent,
        "notification_channel": channel,
        "notification_error": error_message,
    }
