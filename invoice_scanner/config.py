"""Configuration and state management."""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv = __import__("dotenv").load_dotenv

load_dotenv()

STATE_FILE = Path.home() / ".invoice_scanner_state.json"

DATE_DD_MM_YYYY_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
DATE_YYYY_MM_DD_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

logger = logging.getLogger(__name__)


class InvoiceExtract(BaseModel):
    """Data structure for extracted invoice information."""

    model_config = {
        "extra": "ignore",
    }

    file_id: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    extraction_date: str | None = None

    invoice_number: str
    invoice_date: str
    language: str = "unknown"
    company: str
    product: str
    total_value: str
    currency: str
    taxes_paid: str = "N/A"
    extra_fields: dict[str, object] = Field(default_factory=dict)

    @field_validator("invoice_date", mode="before")
    @classmethod
    def _normalize_invoice_date(cls, value: str) -> str:
        if not value:
            return value

        dd_mm_yyyy = DATE_DD_MM_YYYY_RE.match(value)
        if dd_mm_yyyy:
            day, month, year = dd_mm_yyyy.groups()
            return f"{year}-{month}-{day}"

        yyyy_mm_dd = DATE_YYYY_MM_DD_RE.match(value)
        if yyyy_mm_dd:
            return value
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        raise ValueError("Invoice date must be in YYYY-MM-DD format")

    @field_validator(
        "company", "product", "language", "total_value", "currency", mode="before"
    )
    @classmethod
    def _require_non_unknown(cls, value: str) -> str:
        if value is None:
            raise ValueError("Required field is missing")
        if isinstance(value, str) and value.strip().lower() in {"n/a", "unknown", ""}:
            raise ValueError("Required field is missing")
        return value


class State(BaseModel):
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
        return self.model_dump()

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
            data = cls._load_state_file()
            if data is not None:
                return cls.from_dict(data)
        return cls()

    @staticmethod
    def _load_state_file() -> dict[str, Any] | None:
        """Read the state file and return its JSON content."""
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load state file: {e}")
            return None


class AppSettings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    google_credentials_path: str = "credentials.json"
    drive_folder_id: str = ""
    spreadsheet_id: str = ""
    sheet_name: str = "Invoices"


class Config:
    """Configuration management."""

    def __init__(self, state: State):
        self.app_settings = AppSettings()

        self.google_credentials_path: str = os.getenv(
            "GOOGLE_CREDENTIALS_PATH", self.app_settings.google_credentials_path
        )
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

        self.drive_folder_id = (
            state.drive_folder_id or self.app_settings.drive_folder_id
        )
        self.spreadsheet_id = state.spreadsheet_id or self.app_settings.spreadsheet_id
        self.sheet_name = state.sheet_name or self.app_settings.sheet_name
        self.state = state

        self.oauth2_client_config = self._load_oauth2_config()

        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

    def _load_oauth2_config(self) -> dict[str, Any] | None:
        """Load OAuth2 client configuration from credentials file."""
        if not Path(self.google_credentials_path).exists():
            return None

        creds_data = self._read_credentials_file()
        if creds_data is None:
            return None

        if "installed" in creds_data:
            return creds_data["installed"]
        if "web" in creds_data:
            return creds_data["web"]
        return None

    def _read_credentials_file(self) -> dict[str, Any] | None:
        """Read OAuth2 credentials from disk."""
        try:
            with open(self.google_credentials_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to load OAuth2 credentials: {e}")
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
