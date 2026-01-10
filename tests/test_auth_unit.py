import time

from kroget.core.storage import TokenStore
from kroget.kroger import auth
from kroget.kroger.models import StoredToken


def test_build_authorize_url():
    url = auth.build_authorize_url(
        base_url="https://api.kroger.com",
        client_id="client",
        redirect_uri="http://localhost:8400/callback",
        scopes=["profile.compact", "cart.basic:write"],
        state="state123",
    )
    assert "client_id=client" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8400%2Fcallback" in url
    assert "scope=profile.compact+cart.basic%3Awrite" in url
    assert "state=state123" in url


def test_token_expiry(monkeypatch):
    token = StoredToken(
        access_token="access",
        refresh_token="refresh",
        token_type="bearer",
        expires_at=100,
        obtained_at=0,
        scopes=["product.compact"],
    )
    monkeypatch.setattr(auth.time, "time", lambda: 200)
    assert auth.is_token_expired(token)


def test_token_store_roundtrip(tmp_path):
    store = TokenStore(path=tmp_path / "tokens.json")
    now = int(time.time())
    token = StoredToken(
        access_token="access",
        refresh_token="refresh",
        token_type="bearer",
        expires_at=now + 3600,
        obtained_at=now,
        scopes=["product.compact"],
    )
    store.save(token)
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == token.access_token
