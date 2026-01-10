import os
import time

import pytest
from typer.testing import CliRunner

from kroget.cli import app
from kroget.kroger.models import Product, ProductsResponse, StoredToken


class DummyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def products_search(self, token, term, location_id, limit=1):
        return ProductsResponse(data=[Product(productId="123", description="Test")])


@pytest.fixture()
def runner():
    return CliRunner()


def _dummy_token():
    now = int(time.time())
    return StoredToken(
        access_token="access",
        refresh_token="refresh",
        token_type="bearer",
        expires_at=now + 3600,
        obtained_at=now,
        scopes=["product.compact"],
    )


def test_doctor_skips_search_without_location(monkeypatch, runner):
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    class _ConfigStore:
        def load(self):
            return type("C", (), {"default_location_id": None})()

    monkeypatch.setattr("kroget.cli.ConfigStore", _ConfigStore)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "SKIP" in result.output


def test_doctor_searches_when_location_provided(monkeypatch, runner):
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setattr("kroget.cli.KrogerClient", DummyClient)

    result = runner.invoke(app, ["doctor", "--location-id", "01400441"])
    assert result.exit_code == 0
    assert "product search returned" in result.output


@pytest.mark.integration
def test_doctor_live_token(monkeypatch, runner):
    if not ("KROGER_CLIENT_ID" in os.environ and "KROGER_CLIENT_SECRET" in os.environ):
        pytest.skip("Kroger creds not configured")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
