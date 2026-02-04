"""Tests for OpenRouter service."""

import json
from unittest.mock import patch

import pytest


class TestOpenRouterService:
    """Test cases for the OpenRouterService class."""

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_success(self, mock_send):
        """Test successful invoice data extraction."""
        from invoice_scanner import OpenRouterService

        # Mock successful response
        mock_send.return_value = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "invoice_number": "INV-001",
                                "invoice_date": "2024-03-15",
                                "company": "Test Corp",
                                "product": "Test Product",
                                "total_value": "100.00",
                                "currency": "EUR",
                                "taxes_paid": "19.00",
                                "language": "en",
                            }
                        )
                    }
                }
            ],
        }

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result.invoice_number == "INV-001"
        assert result.invoice_date == "2024-03-15"
        assert result.company == "Test Corp"
        assert result.language == "en"
        mock_send.assert_called_once()

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_with_schema(self, mock_send):
        """Test that schema is included in the request payload."""
        from invoice_scanner import OpenRouterService

        mock_send.return_value = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "invoice_number": "INV-002",
                                "invoice_date": "2024-04-20",
                                "company": "Another Corp",
                                "product": "Another Product",
                                "total_value": "200.00",
                                "currency": "USD",
                                "taxes_paid": "0.00",
                                "language": "de",
                            }
                        )
                    }
                }
            ],
        }

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result.invoice_number == "INV-002"
        assert result.language == "de"

        call_args, call_kwargs = mock_send.call_args
        payload = call_args[0] if call_args else call_kwargs.get("payload", {})
        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_schema"
        assert "json_schema" in payload["response_format"]
        schema = payload["response_format"]["json_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_german_date_format(self, mock_send):
        """Test that German date format DD.MM.YYYY is normalized to YYYY-MM-DD."""
        from invoice_scanner import OpenRouterService

        mock_send.return_value = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "invoice_number": "INV-003",
                                "invoice_date": "06.01.2026",
                                "company": "German Corp",
                                "product": "Service",
                                "total_value": "100.00",
                                "currency": "EUR",
                                "taxes_paid": "19.00",
                                "language": "de",
                            }
                        )
                    }
                }
            ],
        }

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result.invoice_number == "INV-003"
        assert result.invoice_date == "2026-01-06"
        assert result.company == "German Corp"
        assert result.language == "de"

        call_args, call_kwargs = mock_send.call_args
        payload = call_args[0] if call_args else call_kwargs.get("payload", {})
        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_schema"
        assert "json_schema" in payload["response_format"]
        schema = payload["response_format"]["json_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_no_choices(self, mock_send):
        """Test handling of response with no choices."""
        from invoice_scanner import OpenRouterService

        mock_send.return_value = {"model": "test-model", "choices": []}

        service = OpenRouterService("test-key")
        with pytest.raises(ValueError, match="NO_CHOICES"):
            service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_invalid_json(self, mock_send):
        """Test handling of invalid JSON response."""
        from invoice_scanner import OpenRouterService

        mock_send.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "This is not valid JSON"}}],
        }

        service = OpenRouterService("test-key")
        with pytest.raises(ValueError, match="PARSE_ERROR"):
            service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

    @patch("invoice_scanner.openrouter.OpenRouterService._send_request")
    def test_extract_invoice_data_api_error(self, mock_send):
        """Test handling of API error."""
        import requests

        from invoice_scanner import OpenRouterService

        mock_send.side_effect = requests.RequestException("API Error")

        service = OpenRouterService("test-key")
        with pytest.raises(ValueError, match="ERROR: API Error"):
            service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

    def test_model_constant(self):
        """Test that MODEL constant is set correctly."""
        from invoice_scanner import OpenRouterService

        assert OpenRouterService.MODEL == "google/gemini-2.5-flash-lite"
