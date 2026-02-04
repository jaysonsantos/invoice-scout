"""Tests for the Config class."""

import os
from unittest.mock import patch

import pytest

from invoice_scanner import Config, State


class TestConfig:
    """Test cases for the Config class."""

    def test_config_requires_openrouter_api_key(self):
        """Test that Config raises error when OPENROUTER_API_KEY is missing."""
        state = State()
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="OPENROUTER_API_KEY"),
        ):
            Config(state)

    def test_config_uses_env_vars(self):
        """Test that Config correctly reads from environment variables."""
        state = State(sheet_name=None)
        env_vars = {
            "OPENROUTER_API_KEY": "test-key",
            "DRIVE_FOLDER_ID": "test-folder-id",
            "SPREADSHEET_ID": "test-spreadsheet-id",
            "SHEET_NAME": "TestSheet",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config(state)
            assert config.openrouter_api_key == "test-key"
            assert config.drive_folder_id == "test-folder-id"
            assert config.spreadsheet_id == "test-spreadsheet-id"
            assert config.sheet_name == "TestSheet"

    def test_config_uses_state_values(self):
        """Test that Config prefers state values over env vars."""
        state = State(
            drive_folder_id="state-folder-id",
            spreadsheet_id="state-spreadsheet-id",
            sheet_name="StateSheet",
        )
        env_vars = {
            "OPENROUTER_API_KEY": "test-key",
            "DRIVE_FOLDER_ID": "env-folder-id",
            "SPREADSHEET_ID": "env-spreadsheet-id",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config(state)
            assert config.drive_folder_id == "state-folder-id"
            assert config.spreadsheet_id == "state-spreadsheet-id"
            assert config.sheet_name == "StateSheet"

    def test_config_default_sheet_name(self):
        """Test that default sheet name is 'Invoices' when neither state nor env var set."""
        state = State()
        env_vars = {"OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config(state)
            assert config.sheet_name == "Invoices"

    def test_config_default_credentials_path(self):
        """Test that default credentials path is 'credentials.json'."""
        state = State()
        env_vars = {"OPENROUTER_API_KEY": "test-key"}
        with patch.dict(os.environ, env_vars, clear=True):
            config = Config(state)
            assert config.google_credentials_path == "credentials.json"


class TestState:
    """Test cases for the State class."""

    def test_state_default_values(self):
        """Test that State initializes with correct default values."""
        state = State()
        assert state.drive_folder_id is None
        assert state.drive_folder_name is None
        assert state.spreadsheet_id is None
        assert state.spreadsheet_name is None
        assert state.sheet_name is None
        assert state.last_run is None
        assert state.processed_count == 0
        assert state.refresh_token is None
        assert state.access_token is None
        assert state.token_expiry is None

    def test_state_to_dict(self):
        """Test that State.to_dict() returns correct dictionary."""
        state = State(
            drive_folder_id="folder-123",
            drive_folder_name="Test Folder",
            spreadsheet_id="sheet-456",
            processed_count=42,
        )
        data = state.to_dict()
        assert data["drive_folder_id"] == "folder-123"
        assert data["drive_folder_name"] == "Test Folder"
        assert data["spreadsheet_id"] == "sheet-456"
        assert data["processed_count"] == 42

    def test_state_from_dict(self):
        """Test that State.from_dict() creates State from dictionary."""
        data = {
            "drive_folder_id": "folder-123",
            "drive_folder_name": "Test Folder",
            "spreadsheet_id": "sheet-456",
            "spreadsheet_name": "Test Sheet",
            "sheet_name": "CustomSheet",
            "last_run": "2024-01-01T00:00:00",
            "processed_count": 100,
            "refresh_token": "refresh-123",
            "access_token": "access-456",
            "token_expiry": "2024-01-02T00:00:00",
        }
        state = State.from_dict(data)
        assert state.drive_folder_id == "folder-123"
        assert state.drive_folder_name == "Test Folder"
        assert state.spreadsheet_id == "sheet-456"
        assert state.sheet_name == "CustomSheet"
        assert state.processed_count == 100
        assert state.refresh_token == "refresh-123"

    def test_state_save_and_load(self, tmp_path):
        """Test that State can be saved and loaded correctly."""
        # Create a test state
        state = State(
            drive_folder_id="folder-123",
            processed_count=10,
            refresh_token="test-refresh",
        )

        test_state_file = tmp_path / ".test_invoice_scanner_state.json"

        try:
            # Save to temp file manually
            import json

            with open(test_state_file, "w") as f:
                json.dump(state.to_dict(), f)

            # Load and verify
            with open(test_state_file) as f:
                loaded_data = json.load(f)

            loaded_state = State.from_dict(loaded_data)
            assert loaded_state.drive_folder_id == "folder-123"
            assert loaded_state.processed_count == 10
            assert loaded_state.refresh_token == "test-refresh"
        finally:
            pass  # No cleanup needed with tmp_path


class TestInvoiceData:
    """Test cases for the InvoiceData dataclass."""

    def test_invoice_data_creation(self):
        """Test that InvoiceData can be created with all fields."""
        from invoice_scanner import InvoiceExtract

        invoice = InvoiceExtract(
            file_id="file-123",
            file_name="invoice.pdf",
            file_url="https://drive.google.com/file/d/123",
            invoice_number="INV-001",
            invoice_date="2024-03-15",
            company="Test Company",
            product="Test Product",
            total_value="100.00",
            taxes_paid="19.00",
            currency="EUR",
            extraction_date="2024-03-15T10:00:00",
            language="en",
        )
        assert invoice.file_id == "file-123"
        assert invoice.invoice_number == "INV-001"
        assert invoice.invoice_date == "2024-03-15"
        assert invoice.language == "en"

    def test_invoice_data_default_language(self):
        """Test that language defaults to 'unknown'."""
        from invoice_scanner import InvoiceExtract

        invoice = InvoiceExtract(
            file_id="file-123",
            file_name="invoice.pdf",
            file_url="https://example.com",
            invoice_number="INV-001",
            invoice_date="2024-03-15",
            company="Company",
            product="Product",
            total_value="100",
            taxes_paid="19",
            currency="EUR",
            extraction_date="2024-03-15T10:00:00",
        )
        assert invoice.language == "unknown"
