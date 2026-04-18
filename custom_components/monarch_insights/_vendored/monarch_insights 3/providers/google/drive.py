"""Drive vault: stores tax docs, statements, paystub PDFs and exposes a search API.

Drive auto-OCRs PDFs at upload, so ``search_text`` is effectively free OCR.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from monarch_insights.observability import get_logger
from monarch_insights.providers.google.auth import GoogleAuth

log = get_logger(__name__)


class DriveVault:
    def __init__(self, auth: GoogleAuth, *, root_folder_name: str = "Monarch Insights") -> None:
        self.auth = auth
        self.root_folder_name = root_folder_name
        self._service = None
        self._root_id: str | None = None

    def service(self):
        if self._service is None:
            self._service = self.auth.build("drive", "v3")
        return self._service

    def _ensure_root(self) -> str:
        if self._root_id:
            return self._root_id
        svc = self.service()
        results = (
            svc.files()
            .list(
                q=f"name='{self.root_folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)",
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            self._root_id = files[0]["id"]
            return self._root_id
        created = (
            svc.files()
            .create(
                body={
                    "name": self.root_folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
            )
            .execute()
        )
        self._root_id = created["id"]
        return self._root_id

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        svc = self.service()
        results = (
            svc.files()
            .list(
                q=f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)",
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            return files[0]["id"]
        created = (
            svc.files()
            .create(
                body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        return created["id"]

    async def upload(
        self,
        path: Path,
        *,
        tax_year: int | None = None,
        institution: str | None = None,
        doc_type: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(self._upload_sync, path, tax_year, institution, doc_type)

    def _upload_sync(
        self,
        path: Path,
        tax_year: int | None,
        institution: str | None,
        doc_type: str | None,
    ) -> dict:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-api-python-client missing") from exc
        svc = self.service()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        root = self._ensure_root()
        parent = self._ensure_folder(root, str(tax_year)) if tax_year else root
        if institution:
            parent = self._ensure_folder(parent, institution)
        mime, _ = mimetypes.guess_type(path.name)
        media = MediaFileUpload(str(path), mimetype=mime or "application/octet-stream")
        body = {
            "name": path.name,
            "parents": [parent],
            "appProperties": {
                k: str(v)
                for k, v in {
                    "tax_year": tax_year,
                    "institution": institution,
                    "doc_type": doc_type,
                }.items()
                if v is not None
            },
        }
        return svc.files().create(body=body, media_body=media, fields="id, name, webViewLink").execute()

    async def search_text(self, query: str, *, limit: int = 25) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[dict]:
        svc = self.service()
        result = (
            svc.files()
            .list(
                q=f"fullText contains '{query}' and trashed=false",
                fields="files(id, name, mimeType, webViewLink, appProperties, modifiedTime)",
                pageSize=limit,
            )
            .execute()
        )
        return result.get("files", [])
