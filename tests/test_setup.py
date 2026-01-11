import os
import stat
import time

from typer.testing import CliRunner

from kroget.cli import app
from kroget.core.storage import ConfigStore
from kroget.kroger.models import StoredToken


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


def test_setup_creates_config_with_permissions(monkeypatch, tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "config.json"

    class _Store(ConfigStore):
        def __init__(self, path=None):
            super().__init__(path or config_path)

    monkeypatch.setattr("kroget.cli.ConfigStore", _Store)
    monkeypatch.setattr("kroget.core.storage.ConfigStore", _Store)
    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setattr("kroget.cli.typer.confirm", lambda *args, **kwargs: False)
    monkeypatch.setenv("KROGER_REDIRECT_URI", "")

    responses = iter(
        [
            "client-id",
            "client-secret",
            "http://localhost:8400/callback",
            "",
            "PICKUP",
        ]
    )

    def _prompt(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("kroget.cli.typer.prompt", _prompt)

    result = runner.invoke(app, ["setup", "--no-open-portal", "--no-run-login"])
    assert result.exit_code == 0
    assert config_path.exists()

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert mode == 0o600

    stored = ConfigStore(path=config_path).load()
    assert stored.kroger_client_id == "client-id"
    assert stored.kroger_client_secret == "client-secret"
    assert stored.kroger_redirect_uri == "http://localhost:8400/callback"
    assert stored.default_location_id is None
    assert stored.default_modality == "PICKUP"


def test_setup_prompts_can_use_env(monkeypatch, tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "config.json"

    class _Store(ConfigStore):
        def __init__(self, path=None):
            super().__init__(path or config_path)

    monkeypatch.setattr("kroget.cli.ConfigStore", _Store)
    monkeypatch.setattr("kroget.core.storage.ConfigStore", _Store)
    monkeypatch.setattr(
        "kroget.cli.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )
    monkeypatch.setenv("KROGER_CLIENT_ID", "env-id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("KROGER_REDIRECT_URI", "")

    monkeypatch.setattr("kroget.cli.typer.confirm", lambda *args, **kwargs: True)

    responses = iter(
        [
            "http://localhost:8400/callback",
            "",
            "PICKUP",
        ]
    )

    def _prompt(*args, **kwargs):
        try:
            return next(responses)
        except StopIteration:
            return "PICKUP"

    monkeypatch.setattr("kroget.cli.typer.prompt", _prompt)

    result = runner.invoke(app, ["setup", "--no-open-portal", "--no-run-login"])
    assert result.exit_code == 0

    stored = ConfigStore(path=config_path).load()
    assert stored.kroger_client_id == "env-id"
    assert stored.kroger_client_secret == "env-secret"
