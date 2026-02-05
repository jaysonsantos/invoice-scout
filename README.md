# InvoiceScout

A Python application that scans Google Drive folders for invoice PDFs, extracts key data via OpenRouter, and stores results in Google Sheets with automatic tracking of processed files.

**New: OAuth2 Support** - Uses your personal Google account with secure OAuth2 authentication instead of service accounts!

## Features

- 🔐 **OAuth2 Authentication** - Securely authenticate with your Google account
- 🧙 **Interactive setup wizard** - pick folders and sheets from a list
- 💾 **Local state persistence** - remembers your selections and tokens
- 🔍 **Recursively scans** Google Drive folders for PDF invoices
- 🤖 **Extracts** using OpenRouter: invoice number, company, product, total, taxes, currency
- 🌍 **Supports** both English and German invoices
- 📊 **Outputs** to Google Sheets with automatic duplicate detection

## Prerequisites

1. **Google Cloud Project** with APIs enabled:
   - Google Drive API
   - Google Sheets API

2. **OpenRouter API Key**:
   - Sign up at https://openrouter.ai
   - Generate an API key

3. **Python 3.10+** and **uv**:
   - Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Setup

### 1. Install dependencies
```bash
uv sync
```

### 2. Set up Google Cloud OAuth2 credentials

The application uses OAuth2 to access your Google Drive and Sheets with your personal account.

1. Go to https://console.cloud.google.com
2. Create a new project or select existing one
3. **Enable APIs**:
   - Go to APIs & Services > Library
   - Enable "Google Drive API"
   - Enable "Google Sheets API"
4. **Create OAuth2 credentials**:
   - Go to APIs & Services > Credentials
   - Click "Create Credentials" > "OAuth client ID"
   - Select application type: "Desktop app"
   - Name it "InvoiceScout"
   - Click "Create"
   - Click "Download JSON" and save it as `credentials.json` in the project root

Your `credentials.json` should look like:
```json
{
  "installed": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "project_id": "your-project",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uris": ["http://localhost"]
  }
}
```

### 3. Configure OpenRouter API Key
```bash
cp .env.example .env
# Edit .env and add your OpenRouter API key:
# OPENROUTER_API_KEY=sk-or-...
```

### 4. Authenticate with Google
```bash
uv run main.py auth
```

This will:
- Open your browser to authorize the application
- Ask for permission to access Drive and Sheets
- Save the refresh token locally (you won't need to do this again)

### 5. Run the setup wizard
```bash
uv run main.py setup
```

This interactive wizard will:
- Show you all your Google Drive folders
- Let you pick the folder containing your invoices
- Show you all your Google Sheets
- Let you pick (or create) a spreadsheet for output
- Save these selections to local state

## Usage

### CLI help
```bash
uv run invoice-scout --help
```
```text
Usage: invoice-scout [OPTIONS] COMMAND [ARGS]...

  InvoiceScout - Extract data from PDF invoices in Google Drive

Options:
  -v, --verbose  Enable DEBUG level logging
  --help         Show this message and exit.

Commands:
  auth    Authenticate with Google (OAuth2).
  reset   Reset saved configuration.
  scan    Scan invoices after setup.
  setup   Run interactive setup wizard.
  status  Show current configuration.
```

### First time setup
```bash
# 1. Authenticate (one-time)
uv run main.py auth

# 2. Run setup wizard (to pick folder/sheet)
uv run main.py setup
```

### Scan invoices
```bash
uv run main.py scan      # or just: uv run main.py
```

### Extract from a local PDF (no Sheets writes)
```bash
uv run invoice-scout local /path/to/invoice.pdf
```
```bash
uv run invoice-scout local /path/to/invoice.pdf --model mistralai/mistral-small-3.2-24b-instruct
```

### Check configuration
```bash
uv run main.py status
```

### Reset configuration
```bash
uv run main.py reset
```

### Alternative entrypoints
```bash
uv run invoice-scout setup    # After installing the package
uv run python -m invoice_scanner setup
uv run invoice-scout --help
```

## How It Works

### Authentication Flow
1. **OAuth2 Setup**: The first time you run `uv run main.py auth`, it will:
   - Start a local web server on port 8080
   - Open your browser to Google's OAuth2 consent screen
   - Ask you to authorize access to Drive and Sheets
   - Receive the authorization code via callback
   - Exchange it for access and refresh tokens
   - Save the refresh token for future use

2. **Token Storage**: Tokens are securely stored in:
   - `~/.invoice_scanner_state.json` (refresh token, access token, expiry)
   - You only need to authenticate once
   - Tokens are automatically refreshed when expired

### Scanning Process
1. **Load Configuration** - folder/sheet selections from local state
2. **Authenticate** - use stored refresh token or run OAuth2 flow
3. **Find PDFs** - recursively search the configured Drive folder
4. **Check Existing** - compare with already-processed files in the Sheet
5. **Extract Data** - send new PDFs to OpenRouter
6. **Store Results** - append to the configured Google Sheet

### Authentication Command (`auth`)
Run this when:
- First time setup
- Tokens expired and auto-refresh failed
- You want to switch to a different Google account

```bash
uv run main.py auth
```

## Output Format

The Google Sheet will have these columns:
| Column | Description |
|--------|-------------|
| File ID | Google Drive file identifier |
| File Name | PDF filename |
| File URL | Link to view in Drive |
| Invoice Number | Extracted invoice # |
| Company | Vendor/company name |
| Product | Product/service description |
| Total Value | Total amount (numeric) |
| Currency | USD, EUR, GBP, etc. |
| Taxes Paid | Tax/VAT amount |
| Language | en (English) or de (German) |
| Extraction Date | When processed |

## Language Support

The application handles both English and German invoices:
- **English**: Standard invoice terminology
- **German**: Recognizes terms like:
  - "Rechnungsnummer" = Invoice number
  - "Gesamtbetrag" = Total amount
  - "MwSt" / "USt" = VAT/Tax
  - "Rechnung" = Invoice

## Local State File

Configuration is stored in `~/.invoice_scanner_state.json`:
```json
{
  "drive_folder_id": "1BxiMVs0XRA5n...",
  "drive_folder_name": "Invoices 2024",
  "spreadsheet_id": "1dZ2i0x...",
  "spreadsheet_name": "Invoice Data",
  "sheet_name": "Invoices",
  "last_run": "2024-01-15T10:30:00",
  "processed_count": 42,
  "refresh_token": "1//0dx...",
  "access_token": "SOME_KEY",
  "token_expiry": "2024-01-15T11:30:00"
}
```

**Security Note**: The state file contains OAuth2 tokens. Keep it secure:
- Located at `~/.invoice_scanner_state.json`
- File permissions are handled by your OS
- Delete with `uv run main.py reset` if needed

## Rate Limits & Costs

- **OpenRouter**: Check current pricing at openrouter.ai
- **Google APIs**: Standard OAuth2 quota limits apply (typically 1000 requests/100 seconds)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No folders found" | Your Google account needs to have access to Drive folders. Check you're signed in with the right account during OAuth |
| "No spreadsheets found" | Your Google account needs access to Sheets |
| "Authentication failed" | Check your `credentials.json` file. Make sure it has the "installed" or "web" section |
| "OPENROUTER_API_KEY required" | Add your API key to `.env` file |
| "Port 8080 in use" | Another app is using port 8080. Close it or change `OAUTH2_CALLBACK_PORT` in the code |
| "Browser didn't open" | Manually copy the auth URL shown in the terminal |

### Revoking Access

To revoke the app's access to your Google account:
1. Go to https://myaccount.google.com/permissions
2. Find "InvoiceScout" (or whatever you named it)
3. Click "Remove access"
4. Then run `uv run main.py auth` again to re-authenticate

## License

MIT

## Docker

Build locally with Podman:
```bash
podman build -t invoicescout:latest .
```

Run:
```bash
podman run --rm invoicescout:latest --help
```
