#!/usr/bin/env python3
"""
InvoiceScout Entry Point

Commands:
  uv run main.py setup    # Run interactive setup to select folder and sheet
  uv run main.py scan     # Scan invoices (default)
  uv run main.py status   # Show current configuration
  uv run main.py reset    # Reset saved configuration

Examples:
  uv run main.py              # Same as 'uv run main.py scan'
  uv run main.py setup        # First time setup
  uv run main.py scan         # Process new invoices
"""

import sys

from invoice_scanner import main

if __name__ == "__main__":
    sys.exit(main() or 0)
