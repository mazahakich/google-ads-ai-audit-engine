from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import sys


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
PRIORITY_LABEL_PATTERN = re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b")
MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
NUMBERED_LINE_PATTERN = re.compile(r"^\d+\.\s+")


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
            try:
                insert_formatted_report(
                    docs_service,
                    document_id,
                    report_content,
                    client_name=client_name,
                    report_date=report_date or date.today(),
                )
            except Exception as exc:
                print(
                    f"Warning: Google Docs formatting failed; inserting plain markdown instead: {exc}",
                    file=sys.stderr,
                )
                insert_plain_report(
                    docs_service,
                    document_id,
                    report_content,
                    client_name=client_name,
                    report_date=report_date or date.today(),
                )

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


def insert_formatted_report(docs_service, document_id: str, markdown: str, *, client_name: str, report_date: date) -> None:
    text, style_requests = build_formatted_report_requests(markdown, client_name=client_name, report_date=report_date)
    docs_service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": text,
                    }
                },
                *style_requests,
            ]
        },
    ).execute()


def insert_plain_report(docs_service, document_id: str, markdown: str, *, client_name: str, report_date: date) -> None:
    text = "\n".join(
        [
            "Google Ads AI Audit Report",
            f"Client: {client_name}",
            f"Date: {report_date.isoformat()}",
            "",
            markdown,
        ]
    )
    docs_service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
    ).execute()


def build_formatted_report_requests(markdown: str, *, client_name: str, report_date: date) -> tuple[str, list[dict]]:
    builder = GoogleDocMarkdownBuilder()
    builder.append_line("Google Ads AI Audit Report", paragraph_style="HEADING_1")
    builder.append_line(f"Client: {client_name}", bold_spans=[(0, len("Client:"))])
    builder.append_line(f"Date: {report_date.isoformat()}", bold_spans=[(0, len("Date:"))])
    builder.append_blank_line()

    lines = markdown.splitlines()
    if lines and lines[0].strip() == "# Google Ads AI Audit Report":
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if is_markdown_table_line(stripped):
            table_lines = []
            while index < len(lines) and is_markdown_table_line(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            for table_line in format_markdown_table(table_lines):
                builder.append_line(table_line, monospace=True)
            builder.append_blank_line()
            continue

        if not stripped:
            builder.append_blank_line()
            index += 1
            continue

        if stripped.startswith("### "):
            builder.append_markdown_line(stripped[4:], paragraph_style="HEADING_3")
        elif stripped.startswith("## "):
            builder.append_markdown_line(stripped[3:], paragraph_style="HEADING_2")
        elif stripped.startswith("# "):
            builder.append_markdown_line(stripped[2:], paragraph_style="HEADING_1")
        elif stripped.startswith("- "):
            builder.append_markdown_line(f"• {stripped[2:]}")
        elif NUMBERED_LINE_PATTERN.match(stripped):
            builder.append_markdown_line(stripped)
        else:
            builder.append_markdown_line(stripped)

        index += 1

    return builder.text, builder.requests


class GoogleDocMarkdownBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.requests: list[dict] = []
        self.current_index = 1

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def append_blank_line(self) -> None:
        self.append_line("")

    def append_markdown_line(self, markdown_line: str, paragraph_style: str | None = None) -> None:
        plain_line, bold_spans = strip_markdown_bold(markdown_line)
        bold_spans.extend(priority_label_spans(plain_line))
        self.append_line(plain_line, paragraph_style=paragraph_style, bold_spans=bold_spans)

    def append_line(
        self,
        line: str,
        *,
        paragraph_style: str | None = None,
        bold_spans: list[tuple[int, int]] | None = None,
        monospace: bool = False,
    ) -> None:
        start_index = self.current_index
        text = f"{line}\n"
        end_index = start_index + len(text)
        self.parts.append(text)
        self.current_index = end_index

        content_end = end_index - 1
        if paragraph_style and content_end > start_index:
            self.requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_index, "endIndex": content_end},
                        "paragraphStyle": {"namedStyleType": paragraph_style},
                        "fields": "namedStyleType",
                    }
                }
            )

        if monospace and content_end > start_index:
            self.requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start_index, "endIndex": content_end},
                        "textStyle": {"weightedFontFamily": {"fontFamily": "Courier New"}},
                        "fields": "weightedFontFamily",
                    }
                }
            )

        for span_start, span_end in bold_spans or []:
            absolute_start = start_index + span_start
            absolute_end = start_index + span_end
            if absolute_end > absolute_start:
                self.requests.append(
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": absolute_start, "endIndex": absolute_end},
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    }
                )


def strip_markdown_bold(text: str) -> tuple[str, list[tuple[int, int]]]:
    plain_parts = []
    bold_spans = []
    cursor = 0

    for match in MARKDOWN_BOLD_PATTERN.finditer(text):
        plain_parts.append(text[cursor : match.start()])
        bold_text = match.group(1)
        span_start = sum(len(part) for part in plain_parts)
        plain_parts.append(bold_text)
        bold_spans.append((span_start, span_start + len(bold_text)))
        cursor = match.end()

    plain_parts.append(text[cursor:])
    return "".join(plain_parts), bold_spans


def priority_label_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in PRIORITY_LABEL_PATTERN.finditer(text)]


def is_markdown_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def format_markdown_table(lines: list[str]) -> list[str]:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)

    if not rows:
        return []

    column_count = max(len(row) for row in rows)
    widths = [
        max(len(row[index]) if index < len(row) else 0 for row in rows)
        for index in range(column_count)
    ]

    formatted = []
    for row_index, row in enumerate(rows):
        padded = [
            (row[index] if index < len(row) else "").ljust(widths[index])
            for index in range(column_count)
        ]
        formatted.append(" | ".join(padded).rstrip())
        if row_index == 0 and len(rows) > 1:
            formatted.append("-+-".join("-" * width for width in widths).rstrip())
    return formatted


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
