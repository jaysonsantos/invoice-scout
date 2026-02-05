"""OpenRouter API client for invoice extraction."""

import base64
import json
import logging
import os
import time
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


def build_invoice_prompt(required_keys: str) -> str:
    """Build the extraction prompt shared across model backends."""
    return f"""You are an expert invoice data extraction system. Analyze this invoice PDF and extract the required information. The invoice may be in English or German.

Important:
- If any field is not found, use "N/A"
- For German invoices, be aware of terms like "Rechnungsnummer", "Rechnungsdatum", "Gesamtbetrag", "MwSt", "USt"
- Extract numeric values only, remove currency symbols
- Total should be the final amount including taxes
- Tax amount is the VAT/sales tax paid
- invoice_date must be formatted as YYYY-MM-DD
- Return ONLY a JSON object with keys: {required_keys}
- Do not wrap the JSON in code fences
"""


class OpenRouterService:
    """Service for extracting data using OpenRouter."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "google/gemini-2.5-flash-lite"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        dump_enabled: bool = False,
        dump_dir: Path | None = None,
    ):
        self.api_key = api_key
        self.model = model or self.MODEL
        self.last_usage: dict | None = None
        self.last_headers: dict | None = None
        self.dump_enabled = dump_enabled
        self.dump_dir = dump_dir or Path("/tmp/invoice-scout")
        app_url = os.getenv(
            "OPENROUTER_APP_URL", "https://github.com/jaysonsantos/invoice-scout"
        )
        app_title = os.getenv("OPENROUTER_APP_TITLE", "InvoiceScout")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": app_url,
            "X-Title": app_title,
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
        self,
        pdf_content: bytes,
        file_name: str,
        extracted_text: str | None = None,
    ) -> InvoiceExtract:
        """Extract invoice data from PDF using OpenRouter."""
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

        prompt = build_invoice_prompt(required_keys)

        schema = InvoiceExtract.model_json_schema()

        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ]
        if extracted_text is not None:
            messages[0]["content"].append(
                {
                    "type": "text",
                    "text": f"Extracted text:\n{extracted_text}",
                }
            )
        else:
            pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")
            messages[0]["content"].append(
                {
                    "type": "file",
                    "file": {
                        "filename": file_name,
                        "file_data": f"data:application/pdf;base64,{pdf_base64}",
                    },
                }
            )

        max_tokens = 1000
        if self.model.startswith("openai/gpt-5"):
            max_tokens = 2000

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": schema,
            },
        }
        if self.model.startswith("openai/gpt-5"):
            payload["reasoning"] = {"effort": "minimal"}
        if self.model.startswith("mistralai/"):
            payload.pop("response_format", None)

        dump_paths = self._dump_input(file_name, prompt, schema, payload)
        result, headers = self._send_or_raise(payload)
        actual_model = result.get("model", "unknown")
        logger.info(f"OpenRouter used model: {actual_model} for {file_name}")
        self._log_usage(result.get("usage"), headers)
        self._dump_output(dump_paths, result, headers, actual_model)

        content = self._extract_content(result)
        finish_reason = self._extract_finish_reason(result)
        if finish_reason == "length":
            logger.warning("Finish reason was length; retrying with higher max_tokens")
            payload["max_tokens"] = max(payload["max_tokens"] * 2, 2000)
        if not content.strip() or finish_reason == "length":
            if not content.strip() and finish_reason != "length":
                logger.warning("Empty content received; retrying once")
            result, headers = self._send_or_raise(payload)
            actual_model = result.get("model", actual_model)
            logger.info(f"OpenRouter used model: {actual_model} for {file_name}")
            self._log_usage(result.get("usage"), headers)
            self._dump_output(dump_paths, result, headers, actual_model)
            content = self._extract_content(result)

        extracted_data = self._parse_response_json(content)
        normalized_data = self._normalize_extracted_data(extracted_data)
        return self._validate_invoice(normalized_data)

    def _send_request(self, payload: dict) -> tuple[dict, dict]:
        """Send request to OpenRouter API and return response dict and headers."""
        response = self.session.post(
            self.API_URL, headers=self.headers, json=payload, timeout=120
        )
        if not response.ok:
            logger.error(
                "OpenRouter error %s: %s", response.status_code, response.text.strip()
            )
        response.raise_for_status()
        return response.json(), dict(response.headers)

    def _send_or_raise(self, payload: dict) -> tuple[dict, dict]:
        """Send request and wrap transport errors."""
        try:
            result = self._send_request(payload)
            if isinstance(result, tuple):
                return result
            return result, {}
        except requests.RequestException as e:
            logger.exception(f"OpenRouter API error: {e}")
            raise ValueError(f"ERROR: {e}") from e

    def _extract_content(self, result: dict) -> str:
        """Extract content from OpenRouter response."""
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("NO_CHOICES")
        return choices[0]["message"]["content"]

    def _extract_finish_reason(self, result: dict) -> str | None:
        """Extract finish reason from OpenRouter response."""
        choices = result.get("choices", [])
        if not choices:
            return None
        return choices[0].get("finish_reason") or choices[0].get("native_finish_reason")

    def _log_usage(self, usage: dict | None, headers: dict) -> None:
        """Log cost/token usage info when provided by OpenRouter."""
        self.last_usage = usage
        self.last_headers = headers
        if usage:
            cost = usage.get("cost")
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            logger.info(
                "OpenRouter usage: cost=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                cost,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
        header_keys = [
            key
            for key in headers
            if key.lower().startswith("x-openrouter")
            or key.lower().startswith("x-usage")
            or key.lower().startswith("x-ratelimit")
        ]
        if header_keys:
            logged = {key: headers.get(key) for key in header_keys}
            logger.info("OpenRouter headers: %s", logged)

    def _parse_response_json(self, content: str) -> dict:
        """Parse JSON content from the model response."""
        if not content or not content.strip():
            logger.error("Raw content was empty or whitespace")
        try:
            return json.loads(strip_code_fences(content))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(
                "Raw content that failed parsing (length=%s):\n%r",
                len(content),
                content,
            )
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

    def _dump_input(
        self, file_name: str, prompt: str, schema: dict, payload: dict
    ) -> dict[str, Path] | None:
        """Optionally dump input payload to disk for debugging."""
        if not self.dump_enabled:
            return None

        timestamp = int(time.time())
        slug = self.model.replace("/", "-")
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        input_path = self._unique_dump_path(
            self.dump_dir / f"{timestamp}-input-{slug}.json"
        )

        try:
            with open(input_path, "w") as f:
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
            logger.debug(f"Could not dump input payload: {e}")
            return None

        output_path = self._unique_dump_path(
            self.dump_dir / f"{timestamp}-output-{slug}.json"
        )
        return {"input": input_path, "output": output_path}

    def _dump_output(
        self,
        dump_paths: dict[str, Path] | None,
        result: dict,
        headers: dict,
        actual_model: str,
    ) -> None:
        """Optionally dump output response to disk for debugging."""
        if not dump_paths:
            return
        try:
            with open(dump_paths["output"], "w") as f:
                json.dump(
                    {
                        "model": self.model,
                        "actual_model": actual_model,
                        "timestamp": datetime.now().isoformat(),
                        "response": result,
                        "headers": headers,
                    },
                    f,
                    indent=2,
                    default=str,
                )
        except (OSError, TypeError) as e:
            logger.debug(f"Could not dump output response: {e}")

    @staticmethod
    def _unique_dump_path(path: Path) -> Path:
        """Ensure the dump path is unique by appending a counter if needed."""
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while True:
            candidate = path.with_name(f"{stem}-{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

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
