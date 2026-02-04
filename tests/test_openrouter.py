"""Tests for OpenRouter service."""

import json
from unittest.mock import Mock, patch


class TestOpenRouterService:
    """Test cases for the OpenRouterService class."""

    def test_error_response_format(self):
        """Test that _error_response returns correct format."""
        from invoice_scanner import OpenRouterService

        service = OpenRouterService("test-key")
        error = service._error_response("TEST_ERROR")

        assert error["invoice_number"] == "TEST_ERROR"
        assert error["company"] == "TEST_ERROR"
        assert error["product"] == "TEST_ERROR"
        assert error["total_value"] == "TEST_ERROR"
        assert error["currency"] == "TEST_ERROR"
        assert error["taxes_paid"] == "TEST_ERROR"
        assert error["language"] == "unknown"

    @patch("invoice_scanner.openrouter.requests.post")
    def test_extract_invoice_data_success(self, mock_post):
        """Test successful invoice data extraction."""
        from invoice_scanner import OpenRouterService

        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
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
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result["invoice_number"] == "INV-001"
        assert result["invoice_date"] == "2024-03-15"
        assert result["company"] == "Test Corp"
        assert result["language"] == "en"
        mock_post.assert_called_once()

    @patch("invoice_scanner.openrouter.requests.post")
    def test_extract_invoice_data_with_code_blocks(self, mock_post):
        """Test extraction when response is wrapped in code blocks."""
        from invoice_scanner import OpenRouterService

        mock_response = Mock()
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        + json.dumps(
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
                        + "\n```"
                    }
                }
            ],
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result["invoice_number"] == "INV-002"
        assert result["language"] == "de"

    @patch("invoice_scanner.openrouter.requests.post")
    def test_extract_invoice_data_no_choices(self, mock_post):
        """Test handling of response with no choices."""
        from invoice_scanner import OpenRouterService

        mock_response = Mock()
        mock_response.json.return_value = {"model": "test-model", "choices": []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result["invoice_number"] == "NO_CHOICES"

    @patch("invoice_scanner.openrouter.requests.post")
    def test_extract_invoice_data_invalid_json(self, mock_post):
        """Test handling of invalid JSON response."""
        from invoice_scanner import OpenRouterService

        mock_response = Mock()
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "This is not valid JSON"}}],
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result["invoice_number"] == "PARSE_ERROR"

    @patch("invoice_scanner.openrouter.requests.post")
    def test_extract_invoice_data_api_error(self, mock_post):
        """Test handling of API error."""
        from invoice_scanner import OpenRouterService

        mock_post.side_effect = Exception("API Error")

        service = OpenRouterService("test-key")
        result = service.extract_invoice_data(b"fake-pdf-content", "invoice.pdf")

        assert result["invoice_number"] == "ERROR"

    def test_model_constant(self):
        """Test that MODEL constant is set correctly."""
        from invoice_scanner import OpenRouterService

        assert OpenRouterService.MODEL == "google/gemini-2.5-flash-lite"
