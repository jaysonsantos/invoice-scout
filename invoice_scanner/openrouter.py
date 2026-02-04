"""OpenRouter API client for invoice extraction."""

import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import requests
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DATE_DD_MM_YYYY_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
DATE_YYYY_MM_DD_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
ALLOWED_SCHEMA_KEYS = {
    "invoice_number",
    "invoice_date",
    "company",
    "product",
    "total_value",
    "currency",
    "taxes_paid",
    "language",
}
EXTRA_FIELDS_KEY = "extra_fields"


class InvoiceExtract(BaseModel):
    """Pydantic model for invoice extraction response."""

    model_config = {
        "extra": "ignore",
    }

    invoice_number: str
    invoice_date: str
    language: str
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

        return value

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


class OpenRouterService:
    """Service for extracting data using OpenRouter."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "google/gemini-2.5-flash-lite"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def extract_invoice_data(self, pdf_content: bytes, file_name: str) -> dict:
        """Extract invoice data from PDF using OpenRouter."""
        pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")

        prompt = """You are an expert invoice data extraction system. Analyze this invoice PDF and extract the required information. The invoice may be in English or German.

Important:
- If any field is not found, use "N/A"
- For German invoices, be aware of terms like "Rechnungsnummer", "Rechnungsdatum", "Gesamtbetrag", "MwSt", "USt"
- Extract numeric values only, remove currency symbols
- Total should be the final amount including taxes
- Tax amount is the VAT/sales tax paid
"""

        schema = InvoiceExtract.model_json_schema()

        payload = {
            "model": self.MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "file",
                            "file": {
                                "filename": file_name,
                                "file_data": f"data:application/pdf;base64,{pdf_base64}",
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
            "response_format": {
                "type": "json_schema",
                "json_schema": schema,
            },
        }

        prompt_log_file = Path("/tmp/last_invoice_prompt.json")
        try:
            with open(prompt_log_file, "w") as f:
                json.dump(
                    {
                        "model": self.MODEL,
                        "file_name": file_name,
                        "timestamp": datetime.now().isoformat(),
                        "prompt": prompt,
                        "schema": schema,
                        "payload": payload,
                    },
                    f,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            logger.debug(f"Could not log prompt to file: {e}")

        content = None
        try:
            result = self._send_request(payload)
            actual_model = result.get("model", "unknown")
            logger.info(f"OpenRouter used model: {actual_model} for {file_name}")
            try:
                with open(prompt_log_file, "r+") as f:
                    log_data = json.load(f)
                    log_data["actual_model_used"] = actual_model
                    f.seek(0)
                    json.dump(log_data, f, indent=2, default=str)
                    f.truncate()
            except Exception as e:
                logger.debug(f"Could not update prompt log with model: {e}")

            if "choices" not in result or not result["choices"]:
                return self._error_response("NO_CHOICES")

            content = result["choices"][0]["message"]["content"]

        except Exception as e:
            logger.exception(f"OpenRouter API error: {e}")
            return self._error_response(f"ERROR: {e}")

        try:
            extracted_data = json.loads(self._strip_code_fences(content))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw content that failed parsing:\n{content}")
            return self._error_response("PARSE_ERROR")

        extracted_data = self._normalize_extracted_data(extracted_data)

        try:
            invoice = InvoiceExtract.model_validate(extracted_data)
            data = invoice.model_dump()
            return data
        except Exception as e:
            logger.exception(f"Validation error: {e}")
            logger.error(
                f"Raw response that failed validation:\n{json.dumps(extracted_data, indent=2)}"
            )
            return self._error_response(f"ERROR: {e}")

    def _send_request(self, payload: dict) -> dict:
        """Send request to OpenRouter API and return response dict."""
        response = requests.post(
            self.API_URL, headers=self.headers, json=payload, timeout=120
        )
        response.raise_for_status()
        return response.json()

    def _normalize_extracted_data(self, extracted_data: dict) -> dict:
        """Normalize extracted data without introducing ambiguous fields."""
        normalized = dict(extracted_data)

        if not normalized.get("company"):
            vendor_details = normalized.get("vendor_details")
            if isinstance(vendor_details, dict) and vendor_details.get("name"):
                normalized["company"] = vendor_details.get("name")

        if not normalized.get("product"):
            line_items = normalized.get("line_items")
            if isinstance(line_items, list) and line_items:
                first_item = line_items[0]
                if isinstance(first_item, dict) and first_item.get("description"):
                    normalized["product"] = first_item.get("description")

        if (
            not normalized.get("total_value")
            and normalized.get("total_amount") is not None
        ):
            normalized["total_value"] = str(normalized.get("total_amount"))

        if (
            not normalized.get("taxes_paid")
            and normalized.get("tax_amount") is not None
        ):
            normalized["taxes_paid"] = str(normalized.get("tax_amount"))

        if not normalized.get("language"):
            invoice_date = normalized.get("invoice_date", "")
            if isinstance(invoice_date, str) and DATE_DD_MM_YYYY_RE.match(invoice_date):
                normalized["language"] = "de"
            else:
                normalized["language"] = "en"

        currency = normalized.get("currency")
        if isinstance(currency, str) and currency.strip() in {"€", "EURO", "Euro"}:
            normalized["currency"] = "EUR"

        normalized[EXTRA_FIELDS_KEY] = {
            key: value
            for key, value in normalized.items()
            if key not in ALLOWED_SCHEMA_KEYS | {EXTRA_FIELDS_KEY}
        }

        return normalized

    def _strip_code_fences(self, content: str) -> str:
        """Remove optional markdown code fences around JSON."""
        if not content:
            return content

        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped[3:]
            if stripped.startswith("json"):
                stripped = stripped[4:]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()

    def _error_response(self, error_type: str) -> dict:
        """Return a standardized error response."""
        return {
            "invoice_number": error_type,
            "invoice_date": error_type,
            "company": error_type,
            "product": error_type,
            "total_value": error_type,
            "currency": error_type,
            "taxes_paid": error_type,
            "language": "unknown",
        }
