"""Google Sheets service wrapper."""

import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import InvoiceExtract


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
        self.service = build("sheets", "v4", credentials=credentials)

    def _ensure_sheet_exists(self, sheet_name: str) -> None:
        """Ensure the sheet exists, create it if not."""
        spreadsheet = (
            self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        sheets = spreadsheet.get("sheets", [])
        sheet_exists = any(
            sheet["properties"]["title"] == sheet_name for sheet in sheets
        )

        if not sheet_exists:
            batch_update_body = {
                "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
            }
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id, body=batch_update_body
            ).execute()

    def _ensure_headers(self, sheet_name: str) -> None:
        """Ensure the sheet has proper headers."""
        self._ensure_sheet_exists(sheet_name)
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A1:L1")
            .execute()
        )

        values = result.get("values", [])
        if not values or values[0] != self.HEADERS:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [self.HEADERS]},
            ).execute()

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
        year = "Unknown"
        if invoice_date and len(invoice_date) >= 4 and invoice_date[:4].isdigit():
            year = invoice_date[:4]

        sheet_name = f"Invoices {year}" if year != "Unknown" else "Invoices Unknown"
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

        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=sheet_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
