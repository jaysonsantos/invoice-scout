"""OpenRouter API client for invoice extraction."""

import base64
import json
import logging
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


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

        prompt = """You are an expert invoice data extraction system. Analyze this invoice PDF and extract the following information in JSON format. The invoice may be in English or German.

Extract and return ONLY a JSON object with these exact keys:
{
    "invoice_number": "The invoice number/ID",
    "invoice_date": "The invoice date in YYYY-MM-DD format",
    "company": "The company/vendor name issuing the invoice",
    "product": "The main product or service description (first/main item if multiple)",
    "total_value": "The total amount as a number string (e.g., '1250.50')",
    "currency": "The currency code (e.g., 'USD', 'EUR', 'GBP')",
    "taxes_paid": "The total tax amount as a number string (e.g., '212.59')",
    "language": "The detected language: 'en' for English or 'de' for German"
}

Important:
- If any field is not found, use "N/A"
- For German invoices, be aware of terms like "Rechnungsnummer", "Rechnungsdatum", "Gesamtbetrag", "MwSt", "USt"
- Extract numeric values only, remove currency symbols
- Total should be the final amount including taxes
- Tax amount is the VAT/sales tax paid"""

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
            response = requests.post(self.API_URL, headers=self.headers, json=payload, timeout=120)
            response.raise_for_status()

            result = response.json()
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

            json_str = content.strip()
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()

            if json_str.startswith("{"):
                json_str = json_str[json_str.find("{") : json_str.rfind("}") + 1]

            extracted = json.loads(json_str)
            return extracted

        except json.JSONDecodeError:
            return self._error_response("PARSE_ERROR")
        except Exception:
            return self._error_response("ERROR")

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
