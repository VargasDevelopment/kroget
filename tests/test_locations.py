import time

from typer.testing import CliRunner

from kroget.cli import app
from kroget.core.storage import ConfigStore
from kroget.kroger.models import StoredToken


class DummyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def locations_search(self, token, **kwargs):
        return {
            "data": [
                {
                    "locationId": "01400441",
                    "name": "Test Store",
                    "address": {
                        "addressLine1": "123 Main",
                        "city": "Cincy",
                        "state": "OH",
                        "zipCode": "45202",
                    },
                }
            ]
        }

    def get_location(self, token, location_id):
        return {
            "data": {
                "locationId": location_id,
                "name": "Test Store",
                "address": {
                    "addressLine1": "123 Main",
                    "city": "Cincy",
                    "state": "OH",
                    "zipCode": "45202",
                },
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


def test_locations_search(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setattr("kroget.cli.KrogerClient", DummyClient)

    result = runner.invoke(app, ["locations", "search", "--zip", "45202"])
    assert result.exit_code == 0
    assert "01400441" in result.output


def test_locations_get(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setattr("kroget.cli.KrogerClient", DummyClient)

    result = runner.invoke(app, ["locations", "get", "01400441"])
    assert result.exit_code == 0
    assert "01400441" in result.output


def test_locations_set_default(monkeypatch, tmp_path):
    runner = CliRunner()

    def _store_factory():
        return ConfigStore(path=tmp_path / "config.json")

    monkeypatch.setattr("kroget.cli.ConfigStore", _store_factory)

    result = runner.invoke(app, ["locations", "set-default", "01400441"])
    assert result.exit_code == 0

    stored = ConfigStore(path=tmp_path / "config.json").load()
    assert stored.default_location_id == "01400441"


def test_locations_client_params():
    from kroget.kroger.client import KrogerClient

    client = KrogerClient("https://api.kroger.com")
    captured = {}

    def fake_request(method, path, headers=None, params=None, json=None, data=None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return {"data": []}

    client._request = fake_request  # type: ignore[assignment]

    client.locations_search(
        "token",
        zip_code_near="45202",
        radius_in_miles=5,
        limit=2,
        chain="Kroger",
    )

    assert captured["path"] == "/v1/locations"
    assert captured["params"]["filter.zipCode.near"] == "45202"
    assert captured["params"]["filter.radiusInMiles"] == 5
    assert captured["params"]["filter.limit"] == 2
    assert captured["params"]["filter.chain"] == "Kroger"
