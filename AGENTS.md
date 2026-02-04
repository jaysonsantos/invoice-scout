# Agent Instructions for InvoiceScout

This document provides essential information for AI agents working on this codebase.

## Project Overview

A Python CLI tool that scans Google Drive for invoice PDFs, extracts data using LLMs (OpenRouter), and outputs to Google Sheets with OAuth2 authentication.

## Build/Run Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run main.py                    # Default: scan invoices
uv run main.py auth               # Authenticate with Google OAuth2
uv run main.py setup              # Interactive setup wizard
uv run main.py scan               # Scan and process invoices
uv run main.py status             # Show configuration
uv run main.py reset              # Reset saved configuration

# Alternative entry points
uv run scan-invoices              # Installed script
uv run python -m invoice_scanner  # As module
```

## Lint/Format Commands

```bash
# Check code quality
uv run ruff check invoice_scanner tests

# Auto-fix issues
uv run ruff check invoice_scanner tests --fix

# Format code
uv run ruff format invoice_scanner tests

# Check single file
uv run ruff check invoice_scanner/openrouter.py

# Format single file
uv run ruff format invoice_scanner/openrouter.py
```

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_openrouter.py -v

# Run a single test
uv run pytest tests/test_openrouter.py::TestOpenRouterService::test_model_constant -v
```

## Code Style Guidelines

### Formatting
- **Line length**: 100 characters (configured in pyproject.toml)
- **Quotes**: Double quotes for strings
- **Indent**: 4 spaces
- **Ruff target**: Python 3.10+

### Imports
```python
# Standard library first
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

# Third-party imports
import requests
from google.oauth2.credentials import Credentials

# Local imports (package modules)
from invoice_scanner.config import Config
from invoice_scanner.openrouter import OpenRouterService
```

### Type Annotations
- Use modern union syntax: `str | None` instead of `Optional[str]`
- Use `list[dict[str, str]]` instead of `List[Dict[str, str]]`
- Always annotate function parameters and return types

### Naming Conventions
- **Classes**: PascalCase (e.g., `GoogleDriveService`, `OAuth2Manager`)
- **Functions**: snake_case (e.g., `extract_invoice_data`, `interactive_folder_selection`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `STATE_FILE`, `OAUTH2_CALLBACK_PORT`)
- **Variables**: snake_case (e.g., `auth_code`, `pdf_content`)
- **Private methods**: Leading underscore (e.g., `_ensure_headers`, `_save_credentials`)

### Docstrings
- Use Google docstring convention
- All public classes and functions must have docstrings
- Keep descriptions concise but informative

Example:
```python
def extract_invoice_data(self, pdf_content: bytes, file_name: str) -> dict:
    """Extract invoice data from PDF using OpenRouter.
    
    Args:
        pdf_content: Raw bytes of the PDF file
        file_name: Name of the file for error reporting
        
    Returns:
        Dictionary containing extracted invoice fields
    """
```

### Error Handling
- Use specific exceptions when possible
- Log errors with `logger.error()` before raising
- Use `raise ... from e` for exception chaining
- Return standardized error responses for recoverable failures
- Keep `try/except` blocks tight and focused on a single operation; prefer helper methods to isolate I/O and API error handling

```python
try:
    result = some_operation()
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse JSON: {e}")
    return self._error_response("PARSE_ERROR")
except Exception as e:
    logger.error(f"Operation failed: {e}")
    raise ValueError(f"Operation failed: {e}") from e
```

### Logging
- Use the module-level logger: `logger = logging.getLogger(__name__)`
- Levels: DEBUG for detailed info, INFO for progress, ERROR for failures
- Use f-strings: `logger.info(f"Processing {file_name}")`

### Print Statements
- Use for user-facing CLI output
- Always flush when showing progress: `print("message", flush=True)`
- Use emojis sparingly for status indicators (✅, ❌, ⚠️, 🔄)

## Architecture Notes

- **Package layout**: `invoice_scanner/` contains app, config, oauth, drive, sheets, openrouter, cli
- **Shared utilities**: `invoice_scanner/utils.py` holds helpers like JSON fence stripping and sheet-name/year derivation; reuse these instead of duplicating logic
- **Google API clients**: `invoice_scanner/google_api.py` centralizes Drive/Sheets client creation; prefer these helpers over direct `build(...)` calls
- **Entry point**: `main.py` is a thin wrapper that calls `invoice_scanner.app.main`
- **State management**: Stored in `~/.invoice_scanner_state.json`
- **Authentication**: OAuth2 flow with local HTTP server callback
- **External APIs**: OpenRouter (LLM), Google Drive/Sheets API
- **Parallelism**: File processing runs via ThreadPoolExecutor (default 5 workers)
- **OpenRouter PDF inputs**: The Python SDK `chat.send()` currently does not accept `type: "file"` content; use the HTTP API for PDF uploads when needed.

## Ruff Rules Applied

- E, F, I, N, W, UP, B, C4, SIM
- Ignores E501 (line length handled by formatter)
- Auto-sort imports with isort

## Dependencies

Key dependencies (from pyproject.toml):
- google-api-python-client (Google APIs)
- requests (API calls)
- python-dotenv (env vars)
- ruff (dev dependency)
- pytest (dev dependency)
- pytest-cov (dev dependency)

## CI / Automation

- GitHub Actions: `.github/workflows/ci.yml` runs lint, format check, and tests with coverage via `devenv`
- GitHub Actions: `.github/workflows/release.yml` builds and pushes a container image to GHCR using Podman
- Codecov: coverage is uploaded from CI (`coverage.xml`)
- Renovate: `renovate.json` groups patch/minor updates and auto-merges when checks pass

Never add new dependencies without updating pyproject.toml and running `uv sync`.

## Git Commit Guidelines

### Semantic Commits
All commits must follow semantic commit convention: `type(scope): description`

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactoring without functional changes
- `style`: Code style changes (formatting, missing semicolons, etc.)
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `chore`: Maintenance tasks, dependency updates
- `perf`: Performance improvements
- `ci`: CI/CD configuration changes

**Scopes:**
- `deps`: Dependency-related changes
- `ci`: CI/CD changes
- `docs`: Documentation
- `auth`: Authentication-related
- `drive`: Google Drive integration
- `sheets`: Google Sheets integration
- `openrouter`: LLM service integration
- `cli`: Command-line interface
- `config`: Configuration management

### Imperative Language
Commit messages must use imperative mood (command form):

**Good:**
- `feat(auth): add OAuth2 token refresh logic`
- `fix(drive): resolve PDF parsing timeout`
- `refactor(sheets): extract duplicate validation logic`
- `docs(readme): update installation instructions`

**Bad:**
- `feat(auth): added OAuth2 token refresh logic`
- `fix(drive): fixed PDF parsing timeout`
- `refactor(sheets): refactored duplicate validation logic`
- `docs(readme): updated installation instructions`

### Commit Message Structure
```
type(scope): imperative description

Optional detailed explanation with bullet points:
- Reason for the change
- Approach taken
- Any breaking changes
```

Examples:
```
feat(openrouter): add invoice data extraction service

- Implement OpenRouter API integration
- Add PDF content parsing
- Support multiple invoice fields extraction
```

```
fix(deps): resolve uv dependency conflict

- Update pyproject.toml with compatible versions
- Remove conflicting package constraints
- Test with uv sync
```
