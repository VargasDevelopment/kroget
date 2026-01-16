import pytest
from textual.widgets import DataTable

from kroget.core.storage import (
    Staple,
    add_staple,
    create_list,
    get_active_list,
    list_names,
    set_active_list,
)
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


@pytest.mark.asyncio
async def test_lists_view_preview_updates_on_highlight(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("KROGER_BASE_URL", "https://api.kroger.com")

    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    monkeypatch.setattr("kroget.core.storage._default_lists_path", lambda: lists_path)
    monkeypatch.setattr("kroget.core.storage._default_staples_path", lambda: staples_path)

    create_list("Weekly", lists_path=lists_path, staples_path=staples_path)
    create_list("Empty", lists_path=lists_path, staples_path=staples_path)
    set_active_list("Weekly", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="Milk", term="milk", quantity=2, preferred_upc="123", modality="PICKUP"),
        list_name="Weekly",
        lists_path=lists_path,
        staples_path=staples_path,
    )

    async with KrogetApp().run_test() as pilot:
        await pilot.app.push_screen(ListManagerScreen(pilot.app))
        await pilot.pause()
        screen = pilot.app.screen_stack[-1]
        list_table = screen.query_one("#list_table", DataTable)
        preview_table = screen.query_one("#list_preview", DataTable)
        names = list_names(lists_path=lists_path, staples_path=staples_path)

        assert list_table.row_count == len(names)

        weekly_index = names.index("Weekly")
        assert list_table.cursor_row == weekly_index
        row = preview_table.get_row_at(0)
        assert str(row[0]) == "Milk"
        assert str(row[1]) == "milk"
        assert str(row[2]) == "2"
        assert str(row[3]) == "123"
        assert str(row[4]) == "PICKUP"

        empty_index = names.index("Empty")
        steps = empty_index - weekly_index
        key = "down" if steps > 0 else "up"
        for _ in range(abs(steps)):
            await pilot.press(key)
        await pilot.pause()

        row = preview_table.get_row_at(0)
        assert str(row[0]) == "No items in this list."
