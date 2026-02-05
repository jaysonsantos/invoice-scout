from invoice_scanner import app
from invoice_scanner.openrouter import build_invoice_prompt


def test_format_pivot_includes_model_and_fields():
    results = [
        {
            "model": "test-model",
            "invoice": {
                "invoice_number": "INV-1",
                "invoice_date": "2025-01-01",
                "company": "Test Co",
                "product": "Widget",
                "total_value": "10.00",
                "currency": "USD",
                "taxes_paid": "1.00",
                "language": "en",
            },
            "usage": {"cost": 0.0001234},
        }
    ]

    table = app._format_pivot(results)
    lines = table.splitlines()

    header_cells = [cell.strip() for cell in lines[0].split("|")]
    assert header_cells[:3] == ["model", "invoice_number", "invoice_date"]
    assert "test-model" in lines[2]
    assert "0.000123" in lines[2]


def test_format_pivot_error_row():
    results = [{"model": "broken-model", "error": "boom"}]
    table = app._format_pivot(results)
    assert "ERROR: boom" in table


def test_build_invoice_prompt_contains_keys():
    prompt = build_invoice_prompt("invoice_number, invoice_date")
    assert "invoice_date must be formatted as YYYY-MM-DD" in prompt
    assert "invoice_number, invoice_date" in prompt
