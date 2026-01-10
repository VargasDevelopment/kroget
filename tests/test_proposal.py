import time
from pathlib import Path

from typer.testing import CliRunner

from kroget.cli import app
from kroget.core.proposal import Proposal, ProposalItem
from kroget.core.storage import Staple
from kroget.kroger.models import StoredToken


def test_proposal_serialize_roundtrip(tmp_path):
    proposal = Proposal(
        version="1",
        created_at="2024-01-01T00:00:00Z",
        location_id="01400441",
        items=[
            ProposalItem(
                name="milk",
                quantity=2,
                modality="PICKUP",
                upc="000111",
            )
        ],
    )
    path = tmp_path / "proposal.json"
    proposal.save(path)
    loaded = Proposal.load(path)
    assert loaded.location_id == "01400441"
    assert loaded.items[0].upc == "000111"


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


def test_staples_propose_prefers_upc(monkeypatch, tmp_path):
    staple = Staple(name="milk", term="milk", quantity=2, preferred_upc="000111")

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr("kroget.cli.load_staples", lambda: [staple])
    monkeypatch.setattr(
        "kroget.core.proposal.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )

    class DummyClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def products_search(self, *args, **kwargs):
            raise AssertionError("products_search should not be called")

    monkeypatch.setattr("kroget.core.proposal.KrogerClient", DummyClient)

    out_path = tmp_path / "proposal.json"
    result = CliRunner().invoke(
        app,
        [
            "staples",
            "propose",
            "--location-id",
            "01400441",
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert "000111" in result.output


def test_staples_propose_searches(monkeypatch, tmp_path):
    staple = Staple(name="eggs", term="eggs", quantity=1, preferred_upc=None)

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr("kroget.cli.load_staples", lambda: [staple])
    monkeypatch.setattr(
        "kroget.core.proposal.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )

    class DummyProduct:
        def __init__(self):
            self.productId = "123"
            self.description = "Eggs"
            self.items = None

    class DummyResults:
        data = [DummyProduct()]

    class DummyClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def products_search(self, *args, **kwargs):
            return DummyResults()

        def get_product(self, *args, **kwargs):
            return {"data": {"items": [{"upc": "000222"}]}}

    monkeypatch.setattr("kroget.core.proposal.KrogerClient", DummyClient)
    monkeypatch.setattr("kroget.core.proposal.update_staple", lambda *args, **kwargs: None)

    out_path = tmp_path / "proposal.json"
    result = CliRunner().invoke(
        app,
        [
            "staples",
            "propose",
            "--location-id",
            "01400441",
            "--out",
            str(out_path),
            "--json",
            "--auto-pin",
        ],
    )
    assert result.exit_code == 0
    assert "000222" in result.output


def test_proposal_apply_calls_cart(monkeypatch, tmp_path):
    proposal = Proposal(
        version="1",
        created_at="2024-01-01T00:00:00Z",
        location_id="01400441",
        items=[
            ProposalItem(name="milk", quantity=1, modality="PICKUP", upc="000111"),
            ProposalItem(name="eggs", quantity=2, modality="DELIVERY", upc="000222"),
        ],
    )
    path = tmp_path / "proposal.json"
    proposal.save(path)

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr("kroget.cli.auth.load_user_token", lambda *args, **kwargs: _dummy_token())

    calls = {"count": 0}

    class DummyClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def add_to_cart(self, *args, **kwargs):
            calls["count"] += 1
            return {}

    monkeypatch.setattr("kroget.core.proposal.KrogerClient", DummyClient)

    result = CliRunner().invoke(
        app,
        ["proposal", "apply", str(path), "--apply", "--yes"],
    )
    assert result.exit_code == 0
    assert calls["count"] == 2
