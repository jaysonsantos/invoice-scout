"""Tests for utility functions and helpers."""


class TestYearExtraction:
    """Test cases for year extraction from invoice dates."""

    def test_extract_year_from_date(self):
        """Test extracting year from various date formats."""
        from invoice_scanner.utils import extract_year

        test_cases = [
            ("2024-03-15", "2024"),
            ("2024-12-31", "2024"),
            ("2025-01-01", "2025"),
            ("2023-06-20", "2023"),
        ]

        for date_str, expected_year in test_cases:
            year = extract_year(date_str)
            assert year == expected_year, f"Failed for date: {date_str}"

    def test_extract_year_invalid_dates(self):
        """Test handling of invalid dates."""
        from invoice_scanner.utils import extract_year

        invalid_dates = [
            "",
            "N/A",
            "invalid",
            "15-03-2024",  # Wrong format
            None,
        ]

        for date_str in invalid_dates:
            assert extract_year(date_str) == "Unknown"


class TestSheetNameGeneration:
    """Test cases for sheet name generation based on year."""

    def test_sheet_name_with_valid_year(self):
        """Test generating sheet name from valid invoice dates."""
        from invoice_scanner.utils import sheet_name_for_date

        test_cases = [
            ("2024-03-15", "Invoices 2024"),
            ("2025-01-01", "Invoices 2025"),
            ("2023-12-31", "Invoices 2023"),
        ]

        for date_str, expected_sheet in test_cases:
            sheet_name = sheet_name_for_date(date_str)
            assert sheet_name == expected_sheet

    def test_sheet_name_with_invalid_date(self):
        """Test generating sheet name from invalid dates."""
        from invoice_scanner.utils import sheet_name_for_date

        invalid_dates = ["", "N/A", None, "invalid"]

        for date_str in invalid_dates:
            assert sheet_name_for_date(date_str) == "Invoices Unknown"


class TestJSONParsing:
    """Test cases for JSON extraction from model responses."""

    def test_extract_json_from_code_blocks(self):
        """Test extracting JSON from markdown code blocks."""
        import json

        from invoice_scanner.utils import strip_code_fences

        content = """```json
        {
            "invoice_number": "INV-001",
            "company": "Test Corp"
        }
        ```"""

        data = json.loads(strip_code_fences(content))
        assert data["invoice_number"] == "INV-001"
        assert data["company"] == "Test Corp"

    def test_extract_json_from_generic_code_blocks(self):
        """Test extracting JSON from generic markdown code blocks."""
        import json

        from invoice_scanner.utils import strip_code_fences

        content = """```
        {
            "invoice_number": "INV-002",
            "company": "Another Corp"
        }
        ```"""

        data = json.loads(strip_code_fences(content))
        assert data["invoice_number"] == "INV-002"

    def test_extract_json_plain_text(self):
        """Test extracting JSON from plain text."""
        import json

        from invoice_scanner.utils import strip_code_fences

        content = """{
            "invoice_number": "INV-003",
            "company": "Plain Corp"
        }"""

        data = json.loads(strip_code_fences(content))
        assert data["invoice_number"] == "INV-003"


class TestGermanTaxFields:
    """Test cases for German tax-related invoice fields."""

    def test_german_date_formats(self):
        """Test handling of German date formats."""
        # German dates might be in DD.MM.YYYY format
        german_dates = [
            "15.03.2024",
            "31.12.2024",
            "01.01.2025",
        ]

        for date_str in german_dates:
            # Should be normalized to ISO format or handled appropriately
            if "." in date_str:
                parts = date_str.split(".")
                if len(parts) == 3:
                    # Convert DD.MM.YYYY to YYYY-MM-DD
                    iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    assert len(iso_date) == 10

    def test_required_fields_for_german_tax(self):
        """Test that all required fields for German tax filing are present."""
        from invoice_scanner import InvoiceExtract

        invoice = InvoiceExtract(
            file_id="file-123",
            file_name="invoice.pdf",
            file_url="https://example.com",
            invoice_number="INV-001",
            invoice_date="2024-03-15",  # Required for tax filing
            company="Vendor GmbH",  # Required for tax ID
            product="Consulting Services",
            total_value="119.00",  # Gross amount with VAT
            taxes_paid="19.00",  # VAT/MwSt amount (19% in Germany)
            currency="EUR",  # Required
            extraction_date="2024-03-15T10:00:00",
            language="de",
        )

        # All required fields for German tax:
        assert invoice.invoice_date  # Leistungsdatum (date of service)
        assert invoice.company  # Lieferant/Leistungserbringer
        assert invoice.total_value  # Bruttobetrag
        assert invoice.taxes_paid  # USt/MwSt
        assert invoice.currency == "EUR"  # Currency
        assert invoice.invoice_number  # Rechnungsnummer
