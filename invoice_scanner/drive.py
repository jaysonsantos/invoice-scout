"""Google Drive service wrapper."""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


class GoogleDriveService:
    """Service for interacting with Google Drive."""

    def __init__(self, credentials: Credentials):
        self.service = build("drive", "v3", credentials=credentials)

    def list_accessible_folders(self) -> list[dict[str, str]]:
        """List all folders accessible to the user."""
        folders = []
        page_token = None

        while True:
            try:
                results = (
                    self.service.files()
                    .list(
                        q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                        pageSize=100,
                        fields="nextPageToken, files(id, name, modifiedTime)",
                        pageToken=page_token,
                        orderBy="name",
                    )
                    .execute()
                )

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
            except Exception:
                break

        return folders

    def get_folder_name(self, folder_id: str) -> str:
        """Get the name of a folder by ID."""
        try:
            result = self.service.files().get(fileId=folder_id, fields="name").execute()
            return result.get("name", "Unknown")
        except Exception:
            return "Unknown"

    def get_pdf_files(self, folder_id: str) -> list[dict]:
        """Recursively get all PDF files from a folder."""
        pdfs = []
        page_token = None

        while True:
            query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
            results = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=100,
                    fields="nextPageToken, files(id, name, webViewLink, mimeType)",
                    pageToken=page_token,
                )
                .execute()
            )
            pdfs.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        folder_query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        folders = (
            self.service.files()
            .list(q=folder_query, pageSize=100, fields="files(id, name)")
            .execute()
        )
        for folder in folders.get("files", []):
            pdfs.extend(self.get_pdf_files(folder["id"]))

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
