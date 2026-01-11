from kroget.core.storage import ConfigStore, UserConfig, load_kroger_config


def test_env_overrides_config(monkeypatch, tmp_path):
    store = ConfigStore(path=tmp_path / "config.json")
    store.save(
        UserConfig(
            kroger_client_id="file-id",
            kroger_client_secret="file-secret",
            kroger_redirect_uri="http://file/callback",
        )
    )

    monkeypatch.setenv("KROGER_CLIENT_ID", "env-id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("KROGER_REDIRECT_URI", "http://env/callback")

    config = load_kroger_config(store=store)
    assert config.client_id == "env-id"
    assert config.client_secret == "env-secret"
    assert config.redirect_uri == "http://env/callback"
