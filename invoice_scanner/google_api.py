"""Google API client helpers."""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build


def build_drive_service(credentials: Credentials) -> Resource:
    """Create a Google Drive API client."""
    return build("drive", "v3", credentials=credentials)


def build_sheets_service(credentials: Credentials) -> Resource:
    """Create a Google Sheets API client."""
    return build("sheets", "v4", credentials=credentials)
