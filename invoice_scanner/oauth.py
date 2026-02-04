"""OAuth2 authentication flow."""

import json
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .config import Config, State

OAUTH2_CALLBACK_PORT = 8080
OAUTH2_CALLBACK_PATH = "/oauth2callback"


class OAuth2CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth2 callback."""

    auth_code: str | None = None
    auth_error: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        if "favicon" not in str(args):
            return

    def do_GET(self) -> None:
        """Handle GET request with authorization code."""
        parsed = urlparse(self.path)

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == OAUTH2_CALLBACK_PATH:
            params = parse_qs(parsed.query)

            if "code" in params:
                OAuth2CallbackHandler.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                html_response = """<html>
                    <head><title>Authentication Complete</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1>Authentication successful!</h1>
                        <p>You can close this window and return to the terminal.</p>
                    </body>
                    </html>"""
                self.wfile.write(html_response.encode("utf-8"))
                return

            if "error" in params:
                OAuth2CallbackHandler.auth_error = params["error"][0]
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                html_response = f"""<html>
                    <head><title>Authentication Failed</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1>Authentication failed</h1>
                        <p>Error: {params["error"][0]}</p>
                    </body>
                    </html>"""
                self.wfile.write(html_response.encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()


class OAuth2Manager:
    """Manages OAuth2 authentication flow."""

    def __init__(self, config: Config, state: State):
        self.config = config
        self.state = state
        self.client_config = config.oauth2_client_config

        if not self.client_config:
            raise ValueError("OAuth2 client configuration not found")

        self.client_id = self.client_config["client_id"]
        self.client_secret = self.client_config["client_secret"]
        self.auth_uri = self.client_config.get(
            "auth_uri", "https://accounts.google.com/o/oauth2/auth"
        )
        self.token_uri = self.client_config.get(
            "token_uri", "https://oauth2.googleapis.com/token"
        )

    def authenticate(self) -> Credentials | None:
        """Authenticate and return credentials, using refresh token if available."""
        if self.state.refresh_token:
            creds = Credentials(
                token=self.state.access_token or "",
                refresh_token=self.state.refresh_token,
                token_uri=self.token_uri,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=self.config.get_oauth2_scopes(),
            )

            try:
                if creds.expired or not self.state.access_token:
                    creds.refresh(Request())
                    self._save_credentials(creds)
                return creds
            except Exception:
                return None

        return None

    def run_oauth2_flow(self) -> Credentials:
        """Run the OAuth2 authorization flow to get new tokens."""
        redirect_uri = f"http://localhost:{OAUTH2_CALLBACK_PORT}{OAUTH2_CALLBACK_PATH}"

        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.get_oauth2_scopes()),
            "access_type": "offline",
            "prompt": "consent",
            "response_type": "code",
        }

        auth_url = f"{self.auth_uri}?{urllib.parse.urlencode(auth_params)}"

        OAuth2CallbackHandler.auth_code = None
        OAuth2CallbackHandler.auth_error = None
        auth_event = threading.Event()

        server = HTTPServer(("localhost", OAUTH2_CALLBACK_PORT), OAuth2CallbackHandler)
        server.socket.settimeout(1.0)

        original_do_get = OAuth2CallbackHandler.do_GET

        def patched_do_get(self) -> None:
            original_do_get(self)
            if (
                OAuth2CallbackHandler.auth_code is not None
                or OAuth2CallbackHandler.auth_error is not None
            ):
                auth_event.set()

        OAuth2CallbackHandler.do_GET = patched_do_get

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        webbrowser.open(auth_url)

        while not auth_event.is_set():
            auth_event.wait(1.0)

        if OAuth2CallbackHandler.auth_error:
            raise ValueError(
                f"Authorization failed: {OAuth2CallbackHandler.auth_error}"
            )

        server.shutdown()
        sys.stdout.flush()

        auth_code = OAuth2CallbackHandler.auth_code
        if not auth_code:
            raise ValueError("Failed to get authorization code")

        token_data = {
            "code": auth_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        req = urllib.request.Request(
            self.token_uri,
            data=urllib.parse.urlencode(token_data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            token_response = json.loads(response.read().decode())

        if "error" in token_response:
            raise ValueError(f"Token exchange failed: {token_response['error']}")

        creds = Credentials(
            token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token"),
            token_uri=self.token_uri,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=self.config.get_oauth2_scopes(),
        )

        self._save_credentials(creds)
        return creds

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to state."""
        self.state.access_token = creds.token
        self.state.refresh_token = creds.refresh_token
        self.state.token_expiry = creds.expiry.isoformat() if creds.expiry else None
        self.state.save()

    def get_credentials(self) -> Credentials:
        """Get valid credentials, running auth flow if needed."""
        creds = self.authenticate()
        if creds and creds.valid:
            return creds
        return self.run_oauth2_flow()
