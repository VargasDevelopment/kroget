import json
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
    """
    Create a StoredToken populated with deterministic test values and a one-hour expiry.
    
    Returns:
        StoredToken: token with access "access", refresh "refresh", token_type "bearer", expires_at one hour from now, obtained_at set to the current time, and scopes ["product.compact"].
    """
    now = int(time.time())
    return StoredToken(
        access_token="access",
        refresh_token="refresh",
        token_type="bearer",
        expires_at=now + 3600,
        obtained_at=now,
        scopes=["product.compact"],
    )


def _load_json_from_output(output: str) -> dict:
    """
    Extracts and parses the first JSON object found in a string.
    
    Parameters:
        output (str): Text containing a JSON payload (e.g., command output or captured logs).
    
    Returns:
        dict: The parsed JSON object.
    
    Raises:
        AssertionError: If no JSON payload (no '{' character) is found in the input.
    """
    start = output.find("{")
    if start == -1:
        raise AssertionError("No JSON payload found in output")
    return json.loads(output[start:])


def test_staples_propose_prefers_upc(monkeypatch, tmp_path):
    """
    Verify that proposing staples prefers a staple's preferred UPC and includes searched alternatives.
    
    Sets Kroger credentials and patches staples retrieval, authentication, and KrogerClient to simulate a single staple with preferred_upc "000111" and a search result with UPC "000222". Asserts that the proposal output uses "000111" as the primary item UPC, includes "000222" as an alternative, and that a single product search was performed.
    """
    staple = Staple(name="milk", term="milk", quantity=2, preferred_upc="000111")

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr("kroget.cli.get_staples", lambda **_: [staple])
    monkeypatch.setattr(
        "kroget.core.proposal.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )

    calls = {"search": 0}

    class DummyProduct:
        def __init__(self, upc: str, description: str) -> None:
            self.productId = f"id-{upc}"
            self.description = description
            self.items = [{"upc": upc}]

    class DummyResults:
        data = [DummyProduct("000222", "Alt Milk")]

    class DummyClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def products_search(self, *args, **kwargs):
            calls["search"] += 1
            return DummyResults()

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
    payload = _load_json_from_output(result.output)
    assert payload["items"][0]["upc"] == "000111"
    assert payload["items"][0]["alternatives"][0]["upc"] == "000222"
    assert calls["search"] == 1


def test_lists_items_propose_prefers_upc(monkeypatch, tmp_path):
    """
    Verifies the `lists items propose` CLI command prefers a staple's preferred UPC and includes alternatives from product search.
    
    Asserts the command exits successfully, the primary item UPC matches the staple's preferred_upc, the first alternative UPC matches the searched product UPC, the product search is invoked exactly once, and the requested list name is passed through as "Weekly".
    """
    staple = Staple(name="milk", term="milk", quantity=2, preferred_upc="000111")

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    calls = {"search": 0}
    requested = {}

    def _get_staples(**kwargs):
        """
        Return a single staple and record the requested list name for tests.
        
        Parameters:
            list_name (str | None): Optional list name to record in the shared `requested` dict.
        
        Returns:
            list: A one-element list containing the test `staple` object.
        """
        requested["list_name"] = kwargs.get("list_name")
        return [staple]

    monkeypatch.setattr("kroget.cli.get_staples", _get_staples)
    monkeypatch.setattr(
        "kroget.core.proposal.auth.get_client_credentials_token",
        lambda **_: _dummy_token(),
    )

    class DummyProduct:
        def __init__(self, upc: str, description: str) -> None:
            """
            Initialize the product instance with a UPC and description.
            
            Parameters:
                upc (str): The product's UPC code; used to build the internal `productId` and stored in the `items` list.
                description (str): Human-readable product description.
            
            Notes:
                - Sets `productId` to `f"id-{upc}"`.
                - Initializes `items` as a list containing a single dict with the key `"upc"` and the provided UPC.
            """
            self.productId = f"id-{upc}"
            self.description = description
            self.items = [{"upc": upc}]

    class DummyResults:
        data = [DummyProduct("000222", "Alt Milk")]

    class DummyClient:
        def __init__(self, base_url: str) -> None:
            """
            Initialize the client with the base URL used for API requests.
            
            Parameters:
                base_url (str): The base URL (including scheme and host) for the API endpoints this client will call.
            """
            self.base_url = base_url

        def __enter__(self):
            """
            Enter the runtime context and provide the context manager instance.
            
            Returns:
                self: The context manager instance to be used within the `with` block.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """
            Exit handler for the context manager that does not suppress exceptions.
            
            Called with the exception type, value, and traceback (or `None, None, None` if no exception occurred). This implementation does not suppress exceptions and returns `None`, allowing any raised exception to propagate.
            """
            return None

        def products_search(self, *args, **kwargs):
            """
            Simulate a product search by recording the invocation and returning a dummy result set.
            
            Increments the shared `calls["search"]` counter to record that a search was performed.
            
            Returns:
                DummyResults: A dummy search results container.
            """
            calls["search"] += 1
            return DummyResults()

    monkeypatch.setattr("kroget.core.proposal.KrogerClient", DummyClient)

    out_path = tmp_path / "proposal.json"
    result = CliRunner().invoke(
        app,
        [
            "lists",
            "items",
            "propose",
            "Weekly",
            "--location-id",
            "01400441",
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["items"][0]["upc"] == "000111"
    assert payload["items"][0]["alternatives"][0]["upc"] == "000222"
    assert calls["search"] == 1
    assert requested["list_name"] == "Weekly"


def test_staples_propose_searches(monkeypatch, tmp_path):
    staple = Staple(name="eggs", term="eggs", quantity=1, preferred_upc=None)

    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    monkeypatch.setattr("kroget.cli.get_staples", lambda **_: [staple])
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