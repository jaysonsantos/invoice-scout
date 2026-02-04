"""Main application logic for invoice scanning."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from concurrent.futures import as_completed
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from pydantic import ValidationError

from .cli import setup_wizard
from .config import Config, InvoiceExtract, State
from .drive import GoogleDriveService
from .oauth import OAuth2Manager
from .openrouter import OpenRouterService
from .sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


class InvoiceProcessor:
    """Main processor that orchestrates the invoice scanning workflow."""

    def __init__(self, config: Config, credentials: Credentials):
        self.config = config
        self.credentials = credentials
        self.drive_service = GoogleDriveService(credentials)
        self.sheets_service = GoogleSheetsService(credentials, config.spreadsheet_id)
        self.openrouter_service = OpenRouterService(config.openrouter_api_key)

    def _process_file(self, file_info: dict) -> InvoiceExtract | None:
        """Process a single file and return InvoiceExtract."""
        pdf_content = self._download_pdf(file_info)
        if not pdf_content:
            return None

        extracted = self._extract_invoice(pdf_content, file_info)
        if not extracted:
            return None

        return extracted.model_copy(
            update={
                "file_id": file_info["id"],
                "file_name": file_info["name"],
                "file_url": file_info.get("webViewLink", ""),
                "extraction_date": datetime.now().isoformat(),
            }
        )

    def _download_pdf(self, file_info: dict) -> bytes | None:
        """Download a PDF for processing."""
        try:
            return self.drive_service.download_pdf(file_info["id"])
        except HttpError as e:
            logger.exception(f"Failed to download {file_info['name']}: {e}")
            return None

    def _extract_invoice(
        self, pdf_content: bytes, file_info: dict
    ) -> InvoiceExtract | None:
        """Extract invoice data from a PDF."""
        try:
            return self.openrouter_service.extract_invoice_data(
                pdf_content, file_info["name"]
            )
        except (ValueError, ValidationError) as e:
            logger.exception(f"Failed to extract {file_info['name']}: {e}")
            return None

    def _append_invoice(self, invoice: InvoiceExtract, file_name: str) -> bool:
        """Append invoice to sheets and report success."""
        try:
            self.sheets_service.append_invoice(invoice, invoice.invoice_date)
            return True
        except HttpError as e:
            logger.exception(f"Failed to append invoice {file_name}: {e}")
            return False

    def _parse_total_value(self, invoice: InvoiceExtract) -> float | None:
        """Parse total value for summary reporting."""
        try:
            return float(str(invoice.total_value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    def run(self) -> None:
        """Execute the main processing workflow."""
        logger.info("Starting invoice processing...")

        processed_ids = self.sheets_service.get_processed_file_ids()
        logger.info(f"Found {len(processed_ids)} already processed files")

        pdf_files = self.drive_service.get_pdf_files(self.config.drive_folder_id)
        logger.info(f"Found {len(pdf_files)} PDF files in folder")

        new_files = [f for f in pdf_files if f["id"] not in processed_ids]
        logger.info(f"{len(new_files)} new files to process")

        processed_count = 0
        total_value = 0.0

        with PoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._process_file, file_info): file_info
                for file_info in new_files
            }

            for future in as_completed(futures):
                file_info = futures[future]
                invoice = future.result()
                if not invoice:
                    continue

                if self._append_invoice(invoice, file_info["name"]):
                    processed_count += 1
                    value = self._parse_total_value(invoice)
                    if value is not None:
                        total_value += value
                    logger.info(f"Successfully processed: {file_info['name']}")

        state = self.config.state
        state.last_run = datetime.now().isoformat()
        state.processed_count += processed_count
        state.save()

        logger.info("Invoice processing complete!")
        print(f"\n✅ Processed {processed_count} new invoices")
        print(f"💰 Total value processed: {total_value:.2f}")


def authenticate_command(config: Config) -> bool:
    """Run authentication flow separately."""
    if not config.has_oauth2_config():
        print("❌ OAuth2 credentials not found. Please set up credentials.json first.")
        return False

    print("🔐 Running Google OAuth2 authentication...")
    oauth2_manager = OAuth2Manager(config, config.state)

    try:
        oauth2_manager.get_credentials()
        print("✅ Authentication successful!")
        print("   Your tokens have been saved and will be used for future scans.")
        return True
    except ValueError as e:
        print(f"❌ Authentication failed: {e}")
        return False


def _reset_config() -> None:
    """Reset stored configuration."""
    State().save()
    print("✅ Configuration reset.")


def _show_status() -> None:
    """Show configuration status."""
    print("Configuration loaded.")


def _load_config(state: State) -> Config | None:
    """Load configuration or emit a user-facing error."""
    try:
        return Config(state)
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nRun 'uv run main.py setup' to configure.")
        return None


def _get_credentials(config: Config, state: State) -> Credentials | None:
    """Fetch valid OAuth2 credentials."""
    oauth2_manager = OAuth2Manager(config, state)
    try:
        return oauth2_manager.get_credentials()
    except ValueError as e:
        print(f"❌ Authentication failed: {e}")
        return None


def _run_setup(config: Config) -> None:
    """Run interactive setup and handle user-facing errors."""
    try:
        setup_wizard(config)
        print("\n🎉 Setup complete! You can now run 'uv run main.py scan'")
    except ValueError as e:
        print(f"\n❌ Setup failed: {e}")


def _run_scan(config: Config, state: State) -> None:
    """Run invoice scanning with validated config and credentials."""
    if not config.drive_folder_id or not config.spreadsheet_id:
        print("❌ Missing configuration. Run 'uv run main.py setup' first.")
        return

    credentials = _get_credentials(config, state)
    if not credentials:
        return

    processor = InvoiceProcessor(config, credentials)
    processor.run()


def main() -> None:
    """Main entry point with CLI."""
    parser = argparse.ArgumentParser(
        description="InvoiceScout - Extract data from PDF invoices in Google Drive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run main.py auth           # Authenticate with Google (OAuth2)
  uv run main.py setup          # Run interactive setup wizard
  uv run main.py scan           # Scan invoices (after setup)
  uv run main.py status         # Show current configuration
  uv run main.py reset          # Reset saved configuration
        """,
    )

    parser.add_argument(
        "command",
        choices=["auth", "setup", "scan", "status", "reset"],
        nargs="?",
        default="scan",
        help="Command to run (default: scan)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG level logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)
    state = State.load()

    if args.command == "reset":
        _reset_config()
        return

    if args.command == "status":
        _show_status()
        return

    config = _load_config(state)
    if not config:
        return

    if args.command == "auth":
        authenticate_command(config)
        return

    if args.command == "setup":
        _run_setup(config)
        return

    if args.command == "scan":
        _run_scan(config, state)
