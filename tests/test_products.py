import time

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
        return ProductsResponse(
            data=[
                Product(
                    productId="123",
                    description="Milk",
                    brand="Acme",
                    items=[{"upc": "000111"}],
                )
            ]
        )


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


def test_products_search_table(monkeypatch):
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
        app, ["products", "search", "milk", "--location-id", "01400441"]
    )
    assert result.exit_code == 0
    assert "Milk" in result.output


def test_products_search_json(monkeypatch):
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
        app, ["products", "search", "milk", "--location-id", "01400441", "--json"]
    )
    assert result.exit_code == 0
    assert "productId" in result.output
