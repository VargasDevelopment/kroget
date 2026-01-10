from __future__ import annotations

import base64
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx

from kroget.core.storage import KrogerConfig, TokenStore
from kroget.kroger.models import StoredToken, TokenResponse


class KrogerAuthError(RuntimeError):
    pass


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _token_request(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    data: dict[str, str],
    client: httpx.Client | None = None,
) -> TokenResponse:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": _basic_auth_header(client_id, client_secret),
    }
    url = f"{base_url.rstrip('/')}/v1/connect/oauth2/token"
    close_client = False
    if client is None:
        client = httpx.Client(timeout=10.0)
        close_client = True
    try:
        response = client.post(url, data=data, headers=headers)
    except httpx.RequestError as exc:
        raise KrogerAuthError(f"Token request failed: {exc}") from exc
    finally:
        if close_client:
            client.close()

    if response.status_code >= 400:
        message = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                message = payload.get("error_description") or payload.get("error")
        except ValueError:
            pass
        raise KrogerAuthError(f"Token request failed ({response.status_code}): {message}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise KrogerAuthError("Token response was not valid JSON") from exc
    return TokenResponse.model_validate(payload)


def parse_scopes(scope_str: str) -> list[str]:
    return [scope for scope in scope_str.split() if scope]


def get_client_credentials_token(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    client: httpx.Client | None = None,
) -> StoredToken:
    data = {
        "grant_type": "client_credentials",
        "scope": " ".join(scopes),
    }
    token = _token_request(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        data=data,
        client=client,
    )
    return StoredToken.from_token_response(token, scopes)


def exchange_auth_code_token(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    scopes: list[str],
    client: httpx.Client | None = None,
) -> StoredToken:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    token = _token_request(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        data=data,
        client=client,
    )
    return StoredToken.from_token_response(token, scopes)


def refresh_access_token(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: list[str],
    client: httpx.Client | None = None,
) -> StoredToken:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if scopes:
        data["scope"] = " ".join(scopes)
    token = _token_request(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        data=data,
        client=client,
    )
    stored = StoredToken.from_token_response(token, scopes)
    if not stored.refresh_token:
        stored.refresh_token = refresh_token
    return stored


def build_authorize_url(
    *,
    base_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }
    )
    return f"{base_url.rstrip('/')}/v1/connect/oauth2/authorize?{query}"


def is_token_expired(token: StoredToken, skew_seconds: int = 60) -> bool:
    return int(time.time()) >= token.expires_at - skew_seconds


def generate_state() -> str:
    return secrets.token_urlsafe(16)


def wait_for_auth_code(
    *,
    port: int,
    path: str,
    state: str,
    timeout_seconds: int = 180,
) -> str:
    result: dict[str, Any] = {"code": None, "error": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            received_state = params.get("state", [None])[0]

            if state and received_state != state:
                result["error"] = "state_mismatch"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. You can close this window.")
                return

            if not code:
                result["error"] = "missing_code"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code. You can close this window.")
                return

            result["code"] = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization received. You can close this window.")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer(("localhost", port), CallbackHandler)
    server.timeout = 1

    start = time.time()
    while time.time() - start < timeout_seconds and result["code"] is None:
        server.handle_request()

    server.server_close()

    if result["error"]:
        raise KrogerAuthError(f"Auth callback error: {result['error']}")
    if not result["code"]:
        raise KrogerAuthError("Timed out waiting for authorization code")
    return str(result["code"])


def load_user_token(config: KrogerConfig, store: TokenStore | None = None) -> StoredToken:
    token_store = store or TokenStore()
    token = token_store.load()
    if not token or not token.refresh_token:
        raise KrogerAuthError("No user token found. Run 'kroget auth login' first.")

    if is_token_expired(token):
        token = refresh_access_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=token.refresh_token,
            scopes=token.scopes,
        )
        token_store.save(token)
    return token
