from typer.testing import CliRunner

from kroget.cli import app


def test_proposal_apply_missing_file_is_friendly(tmp_path):
    runner = CliRunner()
    missing = tmp_path / "proposal.json"

    result = runner.invoke(
        app,
        ["proposal", "apply", str(missing), "--apply", "--yes"],
    )

    assert result.exit_code != 0
    assert "File not found" in result.output
    assert "proposal.json" in result.output
    assert "Traceback (most recent call last)" not in result.output


def test_proposal_apply_invalid_json_is_friendly(tmp_path):
    runner = CliRunner()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text("{invalid", encoding="utf-8")

    result = runner.invoke(
        app,
        ["proposal", "apply", str(proposal_path), "--apply", "--yes"],
    )

    assert result.exit_code != 0
    assert "Invalid JSON in" in result.output
    assert "proposal.json" in result.output
    assert "Traceback (most recent call last)" not in result.output


def test_proposal_apply_invalid_format_is_friendly(tmp_path):
    runner = CliRunner()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text('{"version": "1"}', encoding="utf-8")

    result = runner.invoke(
        app,
        ["proposal", "apply", str(proposal_path), "--apply", "--yes"],
    )

    assert result.exit_code != 0
    assert "Invalid proposal format in" in result.output
    assert "proposal.json" in result.output
    assert "validation error" not in result.output.lower()
    assert "Traceback (most recent call last)" not in result.output


def test_lists_list_invalid_json_is_friendly(monkeypatch, tmp_path):
    runner = CliRunner()
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    lists_path.write_text("{invalid", encoding="utf-8")

    monkeypatch.setattr("kroget.core.storage._default_lists_path", lambda: lists_path)
    monkeypatch.setattr("kroget.core.storage._default_staples_path", lambda: staples_path)

    result = runner.invoke(app, ["lists", "list"])

    assert result.exit_code != 0
    assert "Invalid JSON in" in result.output
    assert "lists.json" in result.output
    assert "Traceback (most recent call last)" not in result.output


def test_tui_load_missing_file_is_friendly(tmp_path):
    runner = CliRunner()
    missing = tmp_path / "proposal.json"

    result = runner.invoke(app, ["tui", "--load", str(missing)])

    assert result.exit_code != 0
    assert "File not found" in result.output
    assert "proposal.json" in result.output
    assert "Traceback (most recent call last)" not in result.output


def test_tui_load_invalid_json_is_friendly(tmp_path):
    runner = CliRunner()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text("{invalid", encoding="utf-8")

    result = runner.invoke(app, ["tui", "--load", str(proposal_path)])

    assert result.exit_code != 0
    assert "Invalid JSON in" in result.output
    assert "proposal.json" in result.output
    assert "Traceback (most recent call last)" not in result.output


def test_tui_load_invalid_format_is_friendly(tmp_path):
    runner = CliRunner()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text('{"version": "1"}', encoding="utf-8")

    result = runner.invoke(app, ["tui", "--load", str(proposal_path)])

    assert result.exit_code != 0
    assert "Invalid proposal format in" in result.output
    assert "proposal.json" in result.output
    assert "validation error" not in result.output.lower()
    assert "Traceback (most recent call last)" not in result.output
