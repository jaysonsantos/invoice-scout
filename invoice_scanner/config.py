"""Configuration and state management."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

STATE_FILE = Path.home() / ".invoice_scanner_state.json"


@dataclass
class InvoiceData:
    """Data structure for extracted invoice information."""

    file_id: str
    file_name: str
    file_url: str
    invoice_number: str
    invoice_date: str
    company: str
    product: str
    total_value: str
    taxes_paid: str
    currency: str
    extraction_date: str
    language: str = "unknown"


@dataclass
class State:
    """Application state that persists between runs."""

    drive_folder_id: str | None = None
    drive_folder_name: str | None = None
    spreadsheet_id: str | None = None
    spreadsheet_name: str | None = None
    sheet_name: str | None = None
    last_run: str | None = None
    processed_count: int = 0
    refresh_token: str | None = None
    access_token: str | None = None
    token_expiry: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        return cls(**data)

    def save(self) -> None:
        """Save state to file."""
        with open(STATE_FILE, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls) -> "State":
        """Load state from file or return empty state."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                return cls.from_dict(data)
            except Exception:
                pass
        return cls()


class Config:
    """Configuration management."""

    def __init__(self, state: State):
        self.google_credentials_path = os.getenv(
            "GOOGLE_CREDENTIALS_PATH", "credentials.json"
        )
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        self.drive_folder_id = state.drive_folder_id or os.getenv("DRIVE_FOLDER_ID", "")
        self.spreadsheet_id = state.spreadsheet_id or os.getenv("SPREADSHEET_ID", "")
        self.sheet_name = state.sheet_name or os.getenv("SHEET_NAME", "Invoices")
        self.state = state

        self.oauth2_client_config = self._load_oauth2_config()

        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

    def _load_oauth2_config(self) -> dict[str, Any] | None:
        """Load OAuth2 client configuration from credentials file."""
        if not Path(self.google_credentials_path).exists():
            return None

        try:
            with open(self.google_credentials_path) as f:
                creds_data = json.load(f)

            if "installed" in creds_data:
                return creds_data["installed"]
            if "web" in creds_data:
                return creds_data["web"]
            return None
        except Exception:
            return None

    def has_oauth2_config(self) -> bool:
        """Check if OAuth2 configuration is available."""
        return self.oauth2_client_config is not None

    def get_oauth2_scopes(self) -> list[str]:
        """Get OAuth2 scopes needed for the application."""
        return [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
