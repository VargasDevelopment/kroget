import json

import pytest
from textual.widgets import DataTable

from kroget.core.proposal import Proposal
from kroget.tui import KrogetApp


@pytest.mark.asyncio
async def test_tui_loads_proposal_into_planner(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    proposal_path = tmp_path / "proposal.json"
    payload = {
        "version": "1",
        "created_at": "2024-01-01T00:00:00Z",
        "location_id": "123",
        "items": [
            {"name": "Milk", "quantity": 2, "modality": "PICKUP", "upc": "000111"},
            {"name": "Eggs", "quantity": 1, "modality": "DELIVERY", "upc": None},
        ],
        "sources": ["UnitTest"],
    }
    proposal_path.write_text(json.dumps(payload), encoding="utf-8")
    proposal = Proposal.load(proposal_path)

    async with KrogetApp(initial_proposal=proposal).run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#proposal", DataTable)

        assert table.row_count == 2
        row = table.get_row_at(0)
        assert str(row[0]) == "Milk"
        assert str(row[1]) == "2"
        assert str(row[2]) == "000111"
        assert str(row[3]) == "PICKUP"
        assert str(row[4]) == "staged"

        row = table.get_row_at(1)
        assert str(row[0]) == "Eggs"
        assert str(row[1]) == "1"
        assert str(row[2]) == ""
        assert str(row[3]) == "DELIVERY"
        assert str(row[4]) == "missing"
