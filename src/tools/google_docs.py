from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import Settings


class GoogleDocsTool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_document(self, title: str, content: str) -> dict[str, str]:
        service = build("docs", "v1", credentials=self._load_credentials())
        document = service.documents().create(body={"title": title}).execute()
        document_id = document["documentId"]
        service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    }
                ]
            },
        ).execute()
        return {
            "document_id": document_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    def read_document(self, document_id: str) -> str:
        service = build("docs", "v1", credentials=self._load_credentials())
        document = service.documents().get(documentId=document_id).execute()
        content: list[str] = []
        for element in document.get("body", {}).get("content", []):
            for paragraph_element in element.get("paragraph", {}).get("elements", []):
                text_run = paragraph_element.get("textRun")
                if text_run:
                    content.append(text_run.get("content", ""))
        return "".join(content).strip()

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
