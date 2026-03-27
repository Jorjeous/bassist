from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.config import Settings


class GoogleDriveTool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_files(self, query: str | None = None, page_size: int = 10) -> list[dict[str, str]]:
        service = build("drive", "v3", credentials=self._load_credentials())
        response = (
            service.files()
            .list(
                q=query,
                pageSize=page_size,
                fields="files(id, name, mimeType, webViewLink)",
            )
            .execute()
        )
        return response.get("files", [])

    def upload_file(self, path: Path, mime_type: str | None = None) -> dict[str, str]:
        service = build("drive", "v3", credentials=self._load_credentials())
        metadata = {"name": path.name}
        media = MediaFileUpload(filename=str(path), mimetype=mime_type, resumable=False)
        response = (
            service.files()
            .create(body=metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        return response

    def _load_credentials(self) -> Credentials:
        if self._settings.google_token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self._settings.google_token_file),
                self._settings.google_oauth_scopes,
            )
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self._settings.google_token_file.write_text(credentials.to_json(), encoding="utf-8")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._settings.google_credentials_file),
                self._settings.google_oauth_scopes,
            )
            credentials = flow.run_local_server(port=0)
            self._settings.google_token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials
