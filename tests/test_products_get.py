import time

from typer.testing import CliRunner

from kroget.cli import app
from kroget.kroger.models import StoredToken


class DummyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get_product(self, token, product_id, location_id):
        return {
            "data": {
                "productId": product_id,
                "description": "Test Product",
                "brand": "Brand",
                "items": [{"upc": "000111"}],
            }
        }


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


def test_products_get_shows_upcs(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setattr("kroget.cli.KrogerClient", DummyClient)

    result = runner.invoke(
        app, ["products", "get", "123", "--location-id", "01400441"]
    )
    assert result.exit_code == 0
    assert "000111" in result.output
