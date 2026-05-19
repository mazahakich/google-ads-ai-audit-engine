from __future__ import annotations

from datetime import date
from pathlib import Path


class GoogleDocsExportError(Exception):
    """Raised when Google Docs export fails."""


DOCS_SCOPES = (
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
)
SERVICE_ACCOUNT_SCOPES = (
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
)
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"


def export_markdown_report(
    markdown_path: Path,
    *,
    client_name: str,
    auth_mode: str = "oauth",
    client_secret_file: Path | None = None,
    token_file: Path | None = None,
    service_account_file: Path | None = None,
    parent_folder_id: str | None = None,
    report_date: date | None = None,
) -> str:
    if not markdown_path.exists():
        raise GoogleDocsExportError(f"Markdown report does not exist: {markdown_path}")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise GoogleDocsExportError(
            "Google Docs export dependencies are missing. Install google-api-python-client, google-auth, and google-auth-oauthlib."
        ) from exc

    title = f"{client_name} - Google Ads AI Audit - {(report_date or date.today()).isoformat()}"
    report_content = markdown_path.read_text(encoding="utf-8")

    try:
        credentials = build_credentials(
            auth_mode=auth_mode,
            client_secret_file=client_secret_file,
            token_file=token_file,
            service_account_file=service_account_file,
        )
        drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        docs_service = build("docs", "v1", credentials=credentials, cache_discovery=False)

        file_metadata = {
            "name": title,
            "mimeType": GOOGLE_DOC_MIME_TYPE,
        }
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        document = drive_service.files().create(
            body=file_metadata,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()
        document_id = document["id"]

        if report_content:
            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": report_content,
                            }
                        }
                    ]
                },
            ).execute()

        return document.get("webViewLink") or f"https://docs.google.com/document/d/{document_id}/edit"
    except HttpError as exc:
        raise GoogleDocsExportError(build_google_api_error_message(exc)) from exc
    except Exception as exc:
        raise GoogleDocsExportError(f"Google Docs export failed: {exc}") from exc


def build_credentials(
    *,
    auth_mode: str,
    client_secret_file: Path | None,
    token_file: Path | None,
    service_account_file: Path | None,
):
    if auth_mode == "service_account":
        return build_service_account_credentials(service_account_file)
    if auth_mode == "oauth":
        return build_oauth_credentials(client_secret_file, token_file)
    raise GoogleDocsExportError("GOOGLE_DOCS_AUTH_MODE must be either oauth or service_account.")


def build_service_account_credentials(service_account_file: Path | None):
    if not service_account_file:
        raise GoogleDocsExportError("GOOGLE_SERVICE_ACCOUNT_FILE is required when service account export is enabled.")
    if not service_account_file.exists():
        raise GoogleDocsExportError("Configured Google service account file was not found.")

    try:
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise GoogleDocsExportError("Google auth dependency is missing. Install google-auth.") from exc

    return Credentials.from_service_account_file(
        str(service_account_file),
        scopes=SERVICE_ACCOUNT_SCOPES,
    )


def build_oauth_credentials(client_secret_file: Path | None, token_file: Path | None):
    if not client_secret_file:
        raise GoogleDocsExportError("GOOGLE_DOCS_CLIENT_SECRET_FILE is required when OAuth export is enabled.")
    if not client_secret_file.exists():
        raise GoogleDocsExportError("Configured Google Docs OAuth client secret file was not found.")
    if not token_file:
        raise GoogleDocsExportError("GOOGLE_DOCS_TOKEN_FILE is required when OAuth export is enabled.")

    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GoogleDocsExportError(
            "OAuth export dependencies are missing. Install google-auth-oauthlib, google-auth, and google-api-python-client."
        ) from exc

    credentials = None
    if token_file.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_file), DOCS_SCOPES)
        except Exception as exc:
            raise GoogleDocsExportError(f"Failed to load Google Docs OAuth token file: {exc}") from exc

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            write_oauth_token(credentials, token_file)
            return credentials
        except RefreshError as exc:
            raise GoogleDocsExportError(f"Google Docs OAuth token refresh failed: {exc}") from exc

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), DOCS_SCOPES)
        credentials = flow.run_local_server(port=0)
        write_oauth_token(credentials, token_file)
        return credentials
    except Exception as exc:
        raise GoogleDocsExportError(f"Google Docs OAuth browser flow failed: {exc}") from exc


def write_oauth_token(credentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")


def build_google_api_error_message(exc: Exception) -> str:
    message = str(exc)
    if "404" in message or "File not found" in message:
        return (
            "Google Drive folder was not found during Docs export. Confirm GOOGLE_DRIVE_PARENT_FOLDER_ID is set "
            "to the destination folder ID, for example 11iGQRLOOZfMpc3lC-BZskoVLBHN2hZ86, and that the folder "
            "is shared with the service account email as Editor. If the folder is in a Shared Drive, confirm the "
            f"service account has access to that Shared Drive or folder. Original error: {message}"
        )
    if "403" not in message:
        return f"Google API error during Docs export: {message}"

    return (
        "Google API permission error during Docs export. Confirm that Google Docs API and Google Drive API "
        "are enabled, GOOGLE_DRIVE_PARENT_FOLDER_ID is correct, and the authenticated Google user has access "
        "to the destination folder. In service account mode, the destination folder must be shared with the "
        f"service account email as Editor. Original error: {message}"
    )
