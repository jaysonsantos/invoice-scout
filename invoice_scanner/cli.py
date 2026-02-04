"""Interactive CLI helpers for setup and status."""

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from .config import STATE_FILE, Config, State
from .drive import GoogleDriveService
from .google_api import build_drive_service, build_sheets_service
from .oauth import OAuth2Manager

logger = logging.getLogger(__name__)


def _list_spreadsheet_page(
    drive_service, page_token: str | None
) -> dict[str, list[dict[str, str]] | str | None] | None:
    """Fetch a single page of spreadsheets from Drive."""
    try:
        return (
            drive_service.files()
            .list(
                q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, modifiedTime)",
                pageToken=page_token,
                orderBy="name",
            )
            .execute()
        )
    except HttpError as e:
        logger.error(f"Failed to list spreadsheets: {e}")
        return None


def _create_spreadsheet(credentials: Credentials, name: str) -> tuple[str, str] | None:
    """Create a new spreadsheet and return (id, name)."""
    try:
        sheets_service = build_sheets_service(credentials)
        spreadsheet = {"properties": {"title": name}}
        result = sheets_service.spreadsheets().create(body=spreadsheet).execute()
        return result["spreadsheetId"], name
    except HttpError as e:
        print(f"❌ Failed to create spreadsheet: {e}")
        return None


def _get_spreadsheet_name(credentials: Credentials, spreadsheet_id: str) -> str | None:
    """Fetch a spreadsheet name from its ID."""
    try:
        sheets_service = build_sheets_service(credentials)
        result = (
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
    except HttpError as e:
        print(f"❌ Could not access spreadsheet: {e}")
        return None
    return result.get("properties", {}).get("title", "Unknown")


def interactive_folder_selection(drive_service: GoogleDriveService) -> tuple | None:
    """Interactive folder selection from Google Drive."""
    print("\n📁 Fetching accessible folders from Google Drive...")
    folders = drive_service.list_accessible_folders()

    if not folders:
        print("❌ No folders found. Make sure you have access to Drive folders.")
        return None

    print(f"\nFound {len(folders)} accessible folders:\n")
    print(f"{'#':<4} {'Folder Name':<40} {'Last Modified':<25}")
    print("-" * 75)

    for i, folder in enumerate(folders[:50], 1):
        print(f"{i:<4} {folder['name'][:38]:<40} {folder['modified'][:25]:<25}")

    if len(folders) > 50:
        print(
            f"\n... and {len(folders) - 50} more folders (use search in Google Drive)"
        )

    print("\nOptions:")
    print(f"  [1-{min(len(folders), 50)}] Select folder by number")
    print("  [s] Search folders by name")
    print("  [i] Enter folder ID manually")
    print("  [q] Quit")

    while True:
        choice = input("\nYour choice: ").strip().lower()

        if choice == "q":
            return None

        if choice == "s":
            search_term = input("Enter search term: ").strip().lower()
            matching = [f for f in folders if search_term in f["name"].lower()]
            if matching:
                print(f"\nFound {len(matching)} matching folders:")
                for i, folder in enumerate(matching[:20], 1):
                    print(f"{i}. {folder['name']} (ID: {folder['id']})")

                sub_choice = input("Select number or [b]ack: ").strip()
                if sub_choice.isdigit() and 1 <= int(sub_choice) <= len(matching):
                    selected = matching[int(sub_choice) - 1]
                    return (selected["id"], selected["name"])
            else:
                print("No folders match your search.")
            continue

        if choice == "i":
            folder_id = input("Enter folder ID: ").strip()
            if folder_id:
                folder_name = drive_service.get_folder_name(folder_id)
                return (folder_id, folder_name)
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(folders):
                selected = folders[idx]
                return (selected["id"], selected["name"])

        print("Invalid choice. Please try again.")


def interactive_sheet_selection(credentials: Credentials) -> tuple | None:
    """Interactive Google Sheet selection."""
    print("\n📊 Fetching accessible spreadsheets from Google Drive...")

    drive_service = build_drive_service(credentials)

    spreadsheets = []
    page_token = None

    while True:
        results = _list_spreadsheet_page(drive_service, page_token)
        if results is None:
            break

        for sheet in results.get("files", []):
            spreadsheets.append(
                {
                    "id": sheet["id"],
                    "name": sheet["name"],
                    "modified": sheet.get("modifiedTime", "unknown"),
                }
            )

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    if not spreadsheets:
        print("❌ No spreadsheets found. Make sure you have access to Google Sheets.")
        return None

    print(f"\nFound {len(spreadsheets)} accessible spreadsheets:\n")
    print(f"{'#':<4} {'Spreadsheet Name':<40} {'Last Modified':<25}")
    print("-" * 75)

    for i, sheet in enumerate(spreadsheets[:50], 1):
        print(f"{i:<4} {sheet['name'][:38]:<40} {sheet['modified'][:25]:<25}")

    if len(spreadsheets) > 50:
        print(f"\n... and {len(spreadsheets) - 50} more spreadsheets")

    print("\nOptions:")
    print(f"  [1-{min(len(spreadsheets), 50)}] Select spreadsheet by number")
    print("  [n] Create new spreadsheet")
    print("  [i] Enter spreadsheet ID manually")
    print("  [q] Quit")

    while True:
        choice = input("\nYour choice: ").strip().lower()

        if choice == "q":
            return None

        if choice == "n":
            name = input("Enter name for new spreadsheet: ").strip()
            if name:
                created = _create_spreadsheet(credentials, name)
                if created:
                    spreadsheet_id, created_name = created
                    print(f"✅ Created new spreadsheet: {created_name}")
                    print(f"   ID: {spreadsheet_id}")
                    return (spreadsheet_id, created_name)
            continue

        if choice == "i":
            spreadsheet_id = input("Enter spreadsheet ID: ").strip()
            if spreadsheet_id:
                name = _get_spreadsheet_name(credentials, spreadsheet_id)
                if name:
                    return (spreadsheet_id, name)
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(spreadsheets):
                selected = spreadsheets[idx]
                return (selected["id"], selected["name"])

        print("Invalid choice. Please try again.")


def setup_wizard(config: Config) -> State:
    """Interactive setup wizard to select folder and sheet."""
    state = config.state

    if not config.has_oauth2_config():
        raise ValueError("OAuth2 credentials not found")

    oauth2_manager = OAuth2Manager(config, state)
    credentials = oauth2_manager.get_credentials()

    drive_service = GoogleDriveService(credentials)

    if state.drive_folder_id:
        change = input("Change folder? [y/N]: ").strip().lower()
        if change == "y":
            result = interactive_folder_selection(drive_service)
            if result:
                state.drive_folder_id, state.drive_folder_name = result
    else:
        result = interactive_folder_selection(drive_service)
        if result:
            state.drive_folder_id, state.drive_folder_name = result

    if not state.drive_folder_id:
        raise ValueError("No folder selected. Setup aborted.")

    if state.spreadsheet_id:
        change = input("Change spreadsheet? [y/N]: ").strip().lower()
        if change == "y":
            result = interactive_sheet_selection(credentials)
            if result:
                state.spreadsheet_id, state.spreadsheet_name = result
    else:
        result = interactive_sheet_selection(credentials)
        if result:
            state.spreadsheet_id, state.spreadsheet_name = result

    if not state.spreadsheet_id:
        raise ValueError("No spreadsheet selected. Setup aborted.")

    state.save()
    print(f"Configuration saved to {STATE_FILE}")
    return state
