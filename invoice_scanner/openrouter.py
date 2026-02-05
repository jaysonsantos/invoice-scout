"""OpenRouter API client for invoice extraction."""

import base64
import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from pydantic import ValidationError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DATE_DD_MM_YYYY_RE, InvoiceExtract
from .utils import strip_code_fences

logger = logging.getLogger(__name__)

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


class OpenRouterService:
    """Service for extracting data using OpenRouter."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "mistralai/mistral-small-3.2-24b-instruct"

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or self.MODEL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        """Create a requests session with retry/backoff."""
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods={"POST"},
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def extract_invoice_data(
        self, pdf_content: bytes, file_name: str
    ) -> InvoiceExtract:
        """Extract invoice data from PDF using OpenRouter."""
        pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")

        required_keys = ", ".join(
            [
                "invoice_number",
                "invoice_date",
                "company",
                "product",
                "total_value",
                "currency",
                "taxes_paid",
                "language",
            ]
        )

        prompt = f"""You are an expert invoice data extraction system. Analyze this invoice PDF and extract the required information. The invoice may be in English or German.

Important:
- If any field is not found, use "N/A"
- For German invoices, be aware of terms like "Rechnungsnummer", "Rechnungsdatum", "Gesamtbetrag", "MwSt", "USt"
- Extract numeric values only, remove currency symbols
- Total should be the final amount including taxes
- Tax amount is the VAT/sales tax paid
- Return ONLY a JSON object with keys: {required_keys}
- Do not wrap the JSON in code fences
"""

        schema = InvoiceExtract.model_json_schema()

        payload = {
            "model": self.model,
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
        if self.model.startswith("mistralai/"):
            payload.pop("response_format", None)

        prompt_log_file = Path("/tmp/last_invoice_prompt.json")
        self._log_prompt(prompt_log_file, file_name, prompt, schema, payload)

        result = self._send_or_raise(payload)
        actual_model = result.get("model", "unknown")
        logger.info(f"OpenRouter used model: {actual_model} for {file_name}")
        self._update_prompt_log(prompt_log_file, actual_model)

        content = self._extract_content(result)

        extracted_data = self._parse_response_json(content)
        normalized_data = self._normalize_extracted_data(extracted_data)
        return self._validate_invoice(normalized_data)

    def _send_request(self, payload: dict) -> dict:
        """Send request to OpenRouter API and return response dict."""
        response = self.session.post(
            self.API_URL, headers=self.headers, json=payload, timeout=120
        )
        if not response.ok:
            logger.error(
                "OpenRouter error %s: %s", response.status_code, response.text.strip()
            )
        response.raise_for_status()
        return response.json()

    def _send_or_raise(self, payload: dict) -> dict:
        """Send request and wrap transport errors."""
        try:
            return self._send_request(payload)
        except requests.RequestException as e:
            logger.exception(f"OpenRouter API error: {e}")
            raise ValueError(f"ERROR: {e}") from e

    def _extract_content(self, result: dict) -> str:
        """Extract content from OpenRouter response."""
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("NO_CHOICES")
        return choices[0]["message"]["content"]

    def _parse_response_json(self, content: str) -> dict:
        """Parse JSON content from the model response."""
        try:
            return json.loads(strip_code_fences(content))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw content that failed parsing:\n{content}")
            raise ValueError("PARSE_ERROR") from e

    def _validate_invoice(self, extracted_data: dict) -> InvoiceExtract:
        """Validate parsed invoice data."""
        try:
            return InvoiceExtract.model_validate(extracted_data)
        except ValidationError as e:
            logger.exception(f"Validation error: {e}")
            logger.error(
                f"Raw response that failed validation:\n{json.dumps(extracted_data, indent=2)}"
            )
            raise

    def _log_prompt(
        self,
        prompt_log_file: Path,
        file_name: str,
        prompt: str,
        schema: dict,
        payload: dict,
    ) -> None:
        """Write prompt payload to a temp file for debugging."""
        try:
            with open(prompt_log_file, "w") as f:
                json.dump(
                    {
                        "model": self.model,
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
        except (OSError, TypeError) as e:
            logger.debug(f"Could not log prompt to file: {e}")

    def _update_prompt_log(self, prompt_log_file: Path, actual_model: str) -> None:
        """Update prompt log with the model selected by OpenRouter."""
        try:
            with open(prompt_log_file, "r+") as f:
                log_data = json.load(f)
                log_data["actual_model_used"] = actual_model
                f.seek(0)
                json.dump(log_data, f, indent=2, default=str)
                f.truncate()
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Could not update prompt log with model: {e}")

    def _normalize_extracted_data(self, extracted_data: dict) -> dict:
        """Normalize extracted data without introducing ambiguous fields."""
        normalized = dict(extracted_data)

        if not normalized.get("company"):
            vendor_name = normalized.get("vendor_name")
            if isinstance(vendor_name, str) and vendor_name.strip():
                normalized["company"] = vendor_name.strip()
            else:
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

        for key in ("total_value", "taxes_paid"):
            value = normalized.get(key)
            if value is not None and not isinstance(value, str):
                normalized[key] = str(value)

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
