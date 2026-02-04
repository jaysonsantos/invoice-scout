"""Main application logic for invoice scanning."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from concurrent.futures import as_completed
from datetime import datetime

from google.oauth2.credentials import Credentials

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
        try:
            pdf_content = self.drive_service.download_pdf(file_info["id"])
            extracted = self.openrouter_service.extract_invoice_data(
                pdf_content, file_info["name"]
            )

            invoice = extracted.model_copy(
                update={
                    "file_id": file_info["id"],
                    "file_name": file_info["name"],
                    "file_url": file_info.get("webViewLink", ""),
                    "extraction_date": datetime.now().isoformat(),
                }
            )
            return invoice
        except Exception:
            logger.exception(f"Failed to process {file_info['name']}")
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

                try:
                    self.sheets_service.append_invoice(invoice, invoice.invoice_date)
                    processed_count += 1

                    # Track total value
                    try:
                        value = float(str(invoice.total_value).replace(",", "."))
                        total_value += value
                    except Exception:
                        pass

                    logger.info(f"Successfully processed: {file_info['name']}")
                except Exception:
                    logger.exception(f"Failed to append invoice {file_info['name']}")

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
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return False


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
        if state:
            state.save()
        return

    if args.command == "status":
        print("Configuration loaded.")
        return

    try:
        config = Config(state)
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nRun 'uv run main.py setup' to configure.")
        return

    if args.command == "auth":
        authenticate_command(config)
        return

    if args.command == "setup":
        try:
            setup_wizard(config)
            print("\n🎉 Setup complete! You can now run 'uv run main.py scan'")
        except ValueError as e:
            print(f"\n❌ Setup failed: {e}")
        return

    if args.command == "scan":
        if not config.drive_folder_id or not config.spreadsheet_id:
            print("❌ Missing configuration. Run 'uv run main.py setup' first.")
            return

        oauth2_manager = OAuth2Manager(config, state)
        try:
            credentials = oauth2_manager.get_credentials()
        except ValueError as e:
            print(f"❌ Authentication failed: {e}")
            return

        processor = InvoiceProcessor(config, credentials)
        processor.run()
