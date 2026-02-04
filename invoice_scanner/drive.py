"""Google Drive service wrapper."""

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .google_api import build_drive_service

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Service for interacting with Google Drive."""

    def __init__(self, credentials: Credentials):
        self.service = build_drive_service(credentials)

    def _list_files(
        self, query: str, fields: str, page_token: str | None
    ) -> dict | None:
        """List files using a Drive query."""
        try:
            return (
                self.service.files()
                .list(
                    q=query,
                    pageSize=100,
                    fields=fields,
                    pageToken=page_token,
                    orderBy="name",
                )
                .execute()
            )
        except HttpError as e:
            logger.error(f"Failed to list files with query '{query}': {e}")
            return None

    def list_accessible_folders(self) -> list[dict[str, str]]:
        """List all folders accessible to the user."""
        folders = []
        page_token = None

        while True:
            results = self._list_files(
                query="mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name, modifiedTime)",
                page_token=page_token,
            )
            if results is None:
                break

            for folder in results.get("files", []):
                folders.append(
                    {
                        "id": folder["id"],
                        "name": folder["name"],
                        "modified": folder.get("modifiedTime", "unknown"),
                    }
                )

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return folders

    def get_folder_name(self, folder_id: str) -> str:
        """Get the name of a folder by ID."""
        try:
            result = self.service.files().get(fileId=folder_id, fields="name").execute()
        except HttpError as e:
            logger.error(f"Failed to get folder name for {folder_id}: {e}")
            return "Unknown"
        return result.get("name", "Unknown")

    def get_pdf_files(self, folder_id: str) -> list[dict]:
        """Iteratively get all PDF files from a folder and its subfolders."""
        pdfs: list[dict] = []
        pending_folders = [folder_id]

        while pending_folders:
            current_folder_id = pending_folders.pop(0)
            logger.debug(f"Scanning folder {current_folder_id}")

            page_token = None
            while True:
                query = (
                    f"'{current_folder_id}' in parents and mimeType='application/pdf' "
                    "and trashed=false"
                )
                results = self._list_files(
                    query=query,
                    fields="nextPageToken, files(id, name, webViewLink, mimeType)",
                    page_token=page_token,
                )
                if results is None:
                    break

                pdfs.extend(results.get("files", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            folder_query = (
                f"'{current_folder_id}' in parents and "
                "mimeType='application/vnd.google-apps.folder' and trashed=false"
            )
            page_token = None
            while True:
                folder_results = self._list_files(
                    query=folder_query,
                    fields="nextPageToken, files(id, name)",
                    page_token=page_token,
                )
                if folder_results is None:
                    break

                for folder in folder_results.get("files", []):
                    pending_folders.append(folder["id"])

                page_token = folder_results.get("nextPageToken")
                if not page_token:
                    break

        return pdfs

    def download_pdf(self, file_id: str) -> bytes:
        """Download a PDF file from Google Drive."""
        request = self.service.files().get_media(fileId=file_id)
        from io import BytesIO

        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        return fh.getvalue()
