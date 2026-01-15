import pytest
from textual.widgets import DataTable

from kroget.core.storage import create_list, get_active_list, list_names, set_active_list
from kroget.tui import KrogetApp, ListManagerScreen


@pytest.mark.asyncio
async def test_lists_view_preselects_active_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    monkeypatch.setattr("kroget.core.storage._default_lists_path", lambda: lists_path)
    monkeypatch.setattr("kroget.core.storage._default_staples_path", lambda: staples_path)

    create_list("Weekly", lists_path=lists_path, staples_path=staples_path)
    set_active_list("Weekly", lists_path=lists_path, staples_path=staples_path)

    async with KrogetApp().run_test() as pilot:
        await pilot.app.push_screen(ListManagerScreen(pilot.app))
        await pilot.pause()
        screen = pilot.app.screen_stack[-1]
        table = screen.query_one("#list_table", DataTable)
        names = list_names(lists_path=lists_path, staples_path=staples_path)
        active = get_active_list(lists_path=lists_path, staples_path=staples_path)

        assert table.has_focus
        assert table.cursor_row == names.index(active)
