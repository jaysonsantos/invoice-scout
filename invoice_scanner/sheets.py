"""Google Sheets service wrapper."""

import re
import time

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from .config import InvoiceExtract
from .google_api import build_sheets_service
from .utils import sheet_name_for_date


class GoogleSheetsService:
    """Service for interacting with Google Sheets."""

    HEADERS = [
        "File ID",
        "File Name",
        "File URL",
        "Invoice Number",
        "Invoice Date",
        "Company",
        "Product",
        "Total Value",
        "Currency",
        "Taxes Paid",
        "Language",
        "Extraction Date",
    ]

    def __init__(self, credentials: Credentials, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.service = build_sheets_service(credentials)
        self._sheet_titles: set[str] | None = None
        self._headers_checked: set[str] = set()

    def _execute_with_retry(self, request, action: str) -> dict:
        """Execute a Sheets request with retry/backoff on rate limits."""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                return request.execute()
            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status not in {429, 500, 502, 503, 504} or attempt == max_attempts:
                    raise
                backoff = 0.5 * (2 ** (attempt - 1))
                time.sleep(backoff)
        raise RuntimeError(f"Failed to {action} after retries")

    def _load_sheet_titles(self) -> set[str]:
        """Load and cache sheet titles for this spreadsheet."""
        if self._sheet_titles is None:
            spreadsheet = self._execute_with_retry(
                self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id),
                "load spreadsheet",
            )
            sheets = spreadsheet.get("sheets", [])
            self._sheet_titles = {sheet["properties"]["title"] for sheet in sheets}
        return self._sheet_titles

    def _ensure_sheet_exists(self, sheet_name: str) -> None:
        """Ensure the sheet exists, create it if not."""
        titles = self._load_sheet_titles()
        if sheet_name not in titles:
            batch_update_body = {
                "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
            }
            self._execute_with_retry(
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body=batch_update_body
                ),
                "create sheet",
            )
            titles.add(sheet_name)

    def _ensure_headers(self, sheet_name: str) -> None:
        """Ensure the sheet has proper headers."""
        self._ensure_sheet_exists(sheet_name)
        if sheet_name in self._headers_checked:
            return
        self._execute_with_retry(
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [self.HEADERS]},
            ),
            "ensure headers",
        )
        self._headers_checked.add(sheet_name)

    def get_processed_file_ids(self) -> set:
        """Get set of already processed file IDs from all year sheets."""
        all_file_ids = set()
        spreadsheet = (
            self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        sheets = spreadsheet.get("sheets", [])

        invoice_sheets = []
        for sheet in sheets:
            title = sheet["properties"]["title"]
            if re.match(r"^Invoices \d{4}$", title) or title == "Invoices Unknown":
                invoice_sheets.append(title)

        for sheet_name in invoice_sheets:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:A")
                .execute()
            )
            values = result.get("values", [])
            all_file_ids.update({row[0] for row in values[1:] if row})

        return all_file_ids

    def append_invoice(self, invoice: InvoiceExtract, invoice_date: str) -> None:
        """Append invoice data to the appropriate year-specific sheet."""
        sheet_name = sheet_name_for_date(invoice_date)
        self._ensure_headers(sheet_name)

        row = [
            invoice.file_id,
            invoice.file_name,
            invoice.file_url,
            invoice.invoice_number,
            invoice.invoice_date,
            invoice.company,
            invoice.product,
            invoice.total_value,
            invoice.currency,
            invoice.taxes_paid,
            invoice.language,
            invoice.extraction_date,
        ]

        self._execute_with_retry(
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=sheet_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ),
            "append invoice",
        )

    def append_invoices_batch(self, invoices: list[InvoiceExtract]) -> set[str]:
        """Append invoices grouped by sheet and return appended file IDs."""
        grouped: dict[str, list[InvoiceExtract]] = {}
        for invoice in invoices:
            sheet_name = sheet_name_for_date(invoice.invoice_date)
            grouped.setdefault(sheet_name, []).append(invoice)

        appended: set[str] = set()
        for sheet_name, items in grouped.items():
            self._ensure_headers(sheet_name)
            rows = [
                [
                    invoice.file_id,
                    invoice.file_name,
                    invoice.file_url,
                    invoice.invoice_number,
                    invoice.invoice_date,
                    invoice.company,
                    invoice.product,
                    invoice.total_value,
                    invoice.currency,
                    invoice.taxes_paid,
                    invoice.language,
                    invoice.extraction_date,
                ]
                for invoice in items
            ]
            self._execute_with_retry(
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=sheet_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                ),
                "append invoice batch",
            )
            appended.update({invoice.file_id for invoice in items if invoice.file_id})

        return appended
