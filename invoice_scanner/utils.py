"""Shared utility helpers for invoice processing."""

from __future__ import annotations


def strip_code_fences(content: str) -> str:
    """Remove optional markdown code fences around JSON content."""
    if not content:
        return content

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    stripped = stripped.strip()

    if "{" in stripped and "}" in stripped:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < end:
            stripped = stripped[start : end + 1]

    return stripped.strip()


def extract_year(invoice_date: str | None) -> str:
    """Extract a 4-digit year from an invoice date or return 'Unknown'."""
    if not invoice_date or len(invoice_date) < 4:
        return "Unknown"

    year = invoice_date[:4]
    return year if year.isdigit() else "Unknown"


def sheet_name_for_date(invoice_date: str | None) -> str:
    """Build the target sheet name for a given invoice date."""
    year = extract_year(invoice_date)
    return f"Invoices {year}" if year != "Unknown" else "Invoices Unknown"
