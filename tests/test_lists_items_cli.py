import json

from typer.testing import CliRunner

from kroget.cli import app


def _patch_storage_paths(monkeypatch, tmp_path):
    """
    Configure the application's storage path resolvers to use temporary JSON files and return those paths.
    
    Parameters:
        monkeypatch: pytest monkeypatch fixture used to override attribute resolvers.
        tmp_path: Path-like temporary directory in which `lists.json` and `staples.json` are created.
    
    Returns:
        (lists_path, staples_path): Tuple of Path objects for the temporary `lists.json` and `staples.json` files.
    """
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    monkeypatch.setattr("kroget.core.storage._default_lists_path", lambda: lists_path)
    monkeypatch.setattr("kroget.core.storage._default_staples_path", lambda: staples_path)
    return lists_path, staples_path


def test_lists_items_crud(monkeypatch, tmp_path):
    """
    End-to-end CLI test for creating, updating, moving, and removing items within lists.
    
    Performs the following flow:
    - Creates a list "Weekly" and sets it active.
    - Adds an item "Milk" (term "milk") with quantity 2 to the active list and verifies via JSON output.
    - Updates "Milk" quantity to 3.
    - Creates a list "Pantry", moves "Milk" to "Pantry", sets "Pantry" active, and verifies quantity remains 3.
    - Removes "Milk" and verifies the items list is empty.
    """
    _patch_storage_paths(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["lists", "create", "Weekly"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "set-active", "Weekly"])
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "lists",
            "items",
            "add",
            "Milk",
            "--term",
            "milk",
            "--qty",
            "2",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "items", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["items"][0]["name"] == "Milk"
    assert payload["items"][0]["quantity"] == 2

    result = runner.invoke(app, ["lists", "items", "set", "Milk", "--qty", "3"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "create", "Pantry"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "items", "move", "Milk", "--to", "Pantry"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "set-active", "Pantry"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "items", "list", "--json"])
    payload = json.loads(result.output)
    assert payload["items"][0]["quantity"] == 3

    result = runner.invoke(app, ["lists", "items", "remove", "Milk"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["lists", "items", "list", "--json"])
    payload = json.loads(result.output)
    assert payload["items"] == []


def test_staples_deprecated_still_works(monkeypatch, tmp_path):
    """
    Verify the deprecated `staples` command emits a deprecation warning and still adds an item to the Staples list.
    
    Asserts that invoking `staples add Milk --term milk` succeeds and produces a deprecation warning, and that listing items for "Staples" returns the added "Milk" item.
    """
    _patch_storage_paths(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["staples", "add", "Milk", "--term", "milk"])
    assert result.exit_code == 0
    warning_output = f"{getattr(result, 'stderr', '')}{result.output}"
    assert "deprecated" in warning_output

    result = runner.invoke(app, ["lists", "items", "list", "Staples", "--json"])
    payload = json.loads(result.output)
    assert payload["items"][0]["name"] == "Milk"