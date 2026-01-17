from __future__ import annotations

from dataclasses import dataclass
import time
import webbrowser

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, LoadingIndicator, Static

from kroget.core.product_display import product_display_fields
from kroget.core.recent_searches import RecentSearchEntry, load_recent_searches, record_recent_search
from kroget.core.staple_name import normalize_staple_name
from kroget.core.sent_items import (
    load_sent_sessions_with_cleanup,
    record_sent_session,
    session_from_apply_results,
)
from kroget.core.product_upc import extract_upcs
from kroget.core.proposal import (
    Proposal,
    ProposalAlternative,
    ProposalItem,
    apply_proposal_items,
)
from kroget.core.proposal_merge import merge_proposal_items
from kroget.core.storage import (
    ConfigStore,
    Staple,
    TokenStore,
    add_staple,
    create_list,
    delete_list,
    get_active_list,
    get_staples,
    list_names,
    load_kroger_config,
    move_item,
    remove_staple,
    rename_list,
    set_active_list,
    update_staple,
)
from kroget.kroger import auth
from kroget.kroger.client import KrogerAPIError, KrogerClient


@dataclass
class SelectionState:
    proposal_index: int | None = None
    alternative_index: int | None = None
    search_index: int | None = None
    sent_index: int | None = None


@dataclass
class AlternativesState:
    status: str
    error: str | None = None


def _apply_alternatives_to_item(
    item: ProposalItem,
    alternatives: list[ProposalAlternative],
) -> bool:
    item.alternatives = alternatives
    if not item.upc and alternatives:
        item.upc = alternatives[0].upc
        item.source = "search"
        return True
    return False


def _proposal_status_text(proposal: Proposal | None) -> str:
    if not proposal:
        return "Proposal: 0 items"
    sources = ", ".join(proposal.sources) if proposal.sources else "None"
    return f"Proposal: {len(proposal.items)} items | Sources: {sources}"


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str, yes_label: str = "Apply", no_label: str = "Cancel") -> None:
        super().__init__()
        self.message = message
        self.yes_label = yes_label
        self.no_label = no_label

    def compose(self) -> ComposeResult:
        yield Static(self.message, id="confirm_message")
        with Horizontal(id="confirm_buttons"):
            yield Button(self.yes_label, id="confirm_yes", variant="success")
            yield Button(self.no_label, id="confirm_no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm_yes")


class QuantityScreen(ModalScreen[int | None]):
    def __init__(self, default: int, title: str) -> None:
        super().__init__()
        self.default = default
        self.title = title
        self._ready = False

    def compose(self) -> ComposeResult:
        yield Static(self.title, id="confirm_message")
        yield Input(value=str(self.default), id="quantity_input")
        with Horizontal(id="confirm_buttons"):
            yield Button("Continue", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_mount(self) -> None:
        self.query_one("#quantity_input", Input).focus()
        self.set_timer(0.05, self._enable_submit)

    def _enable_submit(self) -> None:
        self._ready = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        value = self.query_one("#quantity_input", Input).value.strip()
        try:
            quantity = int(value)
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss(quantity if quantity > 0 else None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "quantity_input":
            return
        if not self._ready:
            return
        value = event.value.strip()
        try:
            quantity = int(value)
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss(quantity if quantity > 0 else None)


def _normalize_modality(value: str | None) -> str:
    if not value:
        return "PICKUP"
    cleaned = value.strip().upper()
    return cleaned if cleaned in {"PICKUP", "DELIVERY"} else "PICKUP"


class StapleScreen(ModalScreen[tuple[str, int] | None]):
    def __init__(
        self,
        default_name: str,
        default_term: str,
        default_quantity: int,
        default_modality: str,
    ) -> None:
        super().__init__()
        self.default_name = default_name
        self.default_term = default_term
        self.default_quantity = default_quantity
        self.modality = _normalize_modality(default_modality)
        self._ready = False

    def compose(self) -> ComposeResult:
        yield Static("Save item to list", id="confirm_message")
        yield Input(value=self.default_name, id="staple_name")
        yield Input(value=self.default_term, id="staple_term")
        yield Input(value=str(self.default_quantity), id="staple_quantity")
        yield Button(self._modality_label(), id="staple_modality", variant="primary")
        with Horizontal(id="confirm_buttons"):
            yield Button("Save", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_mount(self) -> None:
        self.query_one("#staple_name", Input).focus()
        self.set_timer(0.05, self._enable_submit)

    def _enable_submit(self) -> None:
        self._ready = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "staple_modality":
            self.modality = "DELIVERY" if self.modality == "PICKUP" else "PICKUP"
            event.button.label = self._modality_label()
            event.button.refresh()
            return
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        name = self.query_one("#staple_name", Input).value.strip()
        term = self.query_one("#staple_term", Input).value.strip()
        qty_value = self.query_one("#staple_quantity", Input).value.strip()
        if not name:
            self.dismiss(None)
            return
        try:
            quantity = int(qty_value)
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss((name, term or name, quantity if quantity > 0 else 1, self.modality))

    def _modality_label(self) -> str:
        return f"Modality: {self.modality}"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id not in {"staple_name", "staple_term", "staple_quantity"}:
            return
        if not self._ready:
            return
        name = self.query_one("#staple_name", Input).value.strip()
        term = self.query_one("#staple_term", Input).value.strip()
        qty_value = self.query_one("#staple_quantity", Input).value.strip()
        if not name:
            self.dismiss(None)
            return
        try:
            quantity = int(qty_value)
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss((name, term or name, quantity if quantity > 0 else 1, self.modality))


class UPCSelectScreen(ModalScreen[str | None]):
    def __init__(self, upcs: list[str]) -> None:
        super().__init__()
        self.upcs = upcs
        self.selection = 0

    def compose(self) -> ComposeResult:
        yield Static("Select a UPC", id="confirm_message")
        table = DataTable(id="upc_table")
        table.add_columns("UPC")
        for index, upc in enumerate(self.upcs):
            table.add_row(upc, key=str(index))
        yield table
        with Horizontal(id="confirm_buttons"):
            yield Button("Use UPC", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_mount(self) -> None:
        self.query_one("#upc_table", DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "upc_table":
            self.selection = event.cursor_row

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        if 0 <= self.selection < len(self.upcs):
            self.dismiss(self.upcs[self.selection])
        else:
            self.dismiss(None)


class ListNameScreen(ModalScreen[str | None]):
    def __init__(self, title: str, default_name: str = "") -> None:
        super().__init__()
        self.title = title
        self.default_name = default_name

    def compose(self) -> ComposeResult:
        yield Static(self.title, id="confirm_message")
        yield Input(value=self.default_name, id="list_name")
        with Horizontal(id="confirm_buttons"):
            yield Button("Save", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_mount(self) -> None:
        self.query_one("#list_name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        name = self.query_one("#list_name", Input).value.strip()
        self.dismiss(name if name else None)


class ListSelectScreen(ModalScreen[str | None]):
    def __init__(self, title: str, lists: list[str]) -> None:
        super().__init__()
        self.title = title
        self.lists = lists
        self.selection = 0

    def compose(self) -> ComposeResult:
        yield Static(self.title, id="confirm_message")
        table = DataTable(id="list_select")
        table.add_columns("List")
        table.cursor_type = "row"
        for index, name in enumerate(self.lists):
            table.add_row(name, key=str(index))
        yield table
        with Horizontal(id="confirm_buttons"):
            yield Button("Select", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_mount(self) -> None:
        self.query_one("#list_select", DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "list_select":
            self.selection = event.cursor_row

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        if 0 <= self.selection < len(self.lists):
            self.dismiss(self.lists[self.selection])
        else:
            self.dismiss(None)


class ListManagerScreen(ModalScreen[None]):
    def __init__(self, app_ref: "KrogetApp") -> None:
        super().__init__()
        self.app_ref = app_ref

    def compose(self) -> ComposeResult:
        yield Static("Manage Lists", id="confirm_message")
        with Horizontal(id="list_manager_tables"):
            with Vertical(id="list_panel"):
                yield Static("Lists")
                table = DataTable(id="list_table")
                table.add_columns("Active", "Name")
                table.cursor_type = "row"
                yield table
            with Vertical(id="list_preview_panel"):
                yield Static("Items Preview", id="list_preview_title")
                preview = DataTable(id="list_preview")
                preview.add_columns("Name", "Term", "Qty", "UPC", "Modality")
                preview.cursor_type = "row"
                yield preview
        with Horizontal(id="confirm_buttons"):
            yield Button("Set Active", id="list_set", variant="success")
            yield Button("Add to Proposal", id="list_add", variant="primary")
            yield Button("Create", id="list_create", variant="primary")
            yield Button("Rename", id="list_rename", variant="primary")
            yield Button("Delete", id="list_delete", variant="error")
            yield Button("Close", id="confirm_no", variant="default")

    def on_mount(self) -> None:
        self._refresh()
        self.query_one("#list_table", DataTable).focus()

    def _update_preview(self, list_name: str | None) -> None:
        table = self.query_one("#list_preview", DataTable)
        title = self.query_one("#list_preview_title", Static)
        table.clear()
        if not list_name:
            title.update("Items Preview")
            table.add_row("No lists available.", "", "", "", "")
            return
        title.update(f"Items: {list_name}")
        try:
            staples = get_staples(list_name=list_name)
        except ValueError:
            title.update("Items Preview")
            table.add_row("No lists available.", "", "", "", "")
            return
        if not staples:
            table.add_row("No items in this list.", "", "", "", "")
            return
        for staple in staples:
            table.add_row(
                staple.name,
                staple.term,
                str(staple.quantity),
                staple.preferred_upc or "",
                staple.modality,
            )

    def _refresh(self) -> None:
        table = self.query_one("#list_table", DataTable)
        table.clear()
        names = list_names()
        active = get_active_list()
        if not names:
            table.add_row("", "No lists available.")
            self._update_preview(None)
            return
        for index, name in enumerate(names):
            marker = "●" if name == active else ""
            table.add_row(marker, name, key=str(index))
        if active in names:
            table.move_cursor(row=names.index(active), column=0)
        self._update_preview(self._selected_name())

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "list_table":
            return
        self._update_preview(self._selected_name())

    def _selected_name(self) -> str | None:
        names = list_names()
        if not names:
            return None
        table = self.query_one("#list_table", DataTable)
        index = table.cursor_row
        if index >= len(names):
            return None
        return names[index]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_no":
            self.dismiss(None)
            return
        if event.button.id == "list_set":
            name = self._selected_name()
            if not name:
                return
            try:
                set_active_list(name)
                self.app_ref.on_list_changed()
                self._refresh()
            except ValueError as exc:
                self.app_ref._set_status(str(exc), error=True)
            return
        if event.button.id == "list_add":
            name = self._selected_name()
            if not name:
                return
            self.app_ref.add_list_to_proposal(name)
            return
        if event.button.id == "list_create":
            self.app_ref.push_screen(
                ListNameScreen("Create list"),
                lambda name: self._handle_create(name),
            )
            return
        if event.button.id == "list_rename":
            current = self._selected_name() or ""
            self.app_ref.push_screen(
                ListNameScreen("Rename list", default_name=current),
                lambda name: self._handle_rename(current, name),
            )
            return
        if event.button.id == "list_delete":
            name = self._selected_name()
            if not name:
                return
            self.app_ref.push_screen(
                ConfirmScreen(f"Delete list '{name}'?", yes_label="Delete", no_label="Cancel"),
                lambda confirmed: self._handle_delete(name, confirmed),
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key.lower() == "a":
            name = self._selected_name()
            if name:
                self.app_ref.add_list_to_proposal(name)
                event.stop()

    def _handle_create(self, name: str | None) -> None:
        if not name:
            return
        try:
            create_list(name)
            self.app_ref.on_list_changed()
            self._refresh()
        except ValueError as exc:
            self.app_ref._set_status(str(exc), error=True)

    def _handle_rename(self, old: str, new: str | None) -> None:
        if not new:
            return
        try:
            rename_list(old, new)
            self.app_ref.on_list_changed()
            self._refresh()
        except ValueError as exc:
            self.app_ref._set_status(str(exc), error=True)

    def _handle_delete(self, name: str, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            delete_list(name)
            self.app_ref.on_list_changed()
            self._refresh()
        except ValueError as exc:
            self.app_ref._set_status(str(exc), error=True)


class KrogetApp(App):
    CSS = """
    #main {
        height: 1fr;
    }

    #nav {
        height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #status.error {
        color: $error;
    }

    #proposal_status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #alternatives_status {
        height: 1;
        padding: 0 1;
        content-align: center middle;
        color: $text-muted;
    }

    #alternatives_status.error {
        color: $error;
    }

    #left, #center, #right {
        border: solid $panel;
        padding: 1;
        width: 1fr;
    }

    #planner_view {
        height: 1fr;
    }

    #search_view {
        height: 1fr;
        display: none;
        border: solid $panel;
        padding: 1;
    }

    .search-active #planner_view {
        display: none;
    }

    .search-active #search_view {
        display: block;
    }

    #sent_view {
        height: 1fr;
        display: none;
        border: solid $panel;
        padding: 1;
    }

    .sent-active #planner_view {
        display: none;
    }

    .sent-active #sent_view {
        display: block;
    }

    #search_controls {
        height: 3;
    }

    #search_loading {
        display: none;
        height: 1;
    }

    DataTable {
        height: 1fr;
    }

    #list_manager_tables {
        height: 1fr;
    }

    #list_panel, #list_preview_panel {
        width: 1fr;
    }

    #confirm_message {
        padding: 1 2;
        text-align: center;
    }

    #confirm_buttons {
        width: 100%;
        content-align: center middle;
        padding: 1 0 2 0;
        height: auto;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("p", "pin", "Use alternative"),
        ("d", "delete", "Remove"),
        ("m", "move", "Move"),
        ("a", "apply", "Apply"),
        ("s", "save_staple", "Save item"),
        ("l", "lists", "Lists"),
        ("c", "clear_proposal", "Clear"),
        ("o", "open_cart", "Open cart"),
        ("/", "focus_search", "Search"),
        ("escape", "back", "Back"),
        ("q", "quit", "Quit"),
    ]

    TITLE = "Kro-Get"

    def __init__(
        self,
        *,
        initial_proposal: Proposal | None = None,
        startup_message: str | None = None,
    ) -> None:
        super().__init__()
        self.config = load_kroger_config()
        self.user_config = ConfigStore().load()
        self.location_id = self.user_config.default_location_id
        self.default_modality = _normalize_modality(self.user_config.default_modality)
        self.active_list = get_active_list()
        self.staples: list[Staple] = []
        self.proposal: Proposal | None = initial_proposal
        if not self.location_id and initial_proposal and initial_proposal.location_id:
            self.location_id = initial_proposal.location_id
        self.pinned: dict[str, bool] = {}
        self.search_results: list = []
        self.search_term = ""
        self.active_view = "planner"
        self.recent_entries: list[RecentSearchEntry] = []
        self.search_mode = "recent"
        self.preselect_upc: str | None = None
        self.search_inflight = False
        self.sent_sessions: list[SentSession] = []
        self.selection = SelectionState()
        self.alternatives_state: dict[int, AlternativesState] = {}
        self.proposal_terms: dict[tuple[str, str], str] = {}
        self.startup_message = startup_message

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Mode: Dry-run", id="status")
        yield Static("", id="proposal_status")
        with Horizontal(id="nav"):
            yield Button("Planner", id="nav_planner")
            yield Button("Search", id="nav_search")
            yield Button("Sent", id="nav_sent")
        with Vertical(id="planner_view"):
            with Horizontal(id="main"):
                with Vertical(id="left"):
                    yield Static("Staples", id="staples_title")
                    yield DataTable(id="staples")
                with Vertical(id="center"):
                    yield Static("Proposal")
                    yield DataTable(id="proposal")
                with Vertical(id="right"):
                    yield Static("Alternatives")
                    yield Static("", id="alternatives_status")
                    yield DataTable(id="alternatives")
        with Vertical(id="search_view"):
            yield Static("Search")
            with Horizontal(id="search_controls"):
                yield Input(placeholder="Search Kroger products...", id="search_input")
            yield LoadingIndicator(id="search_loading")
            yield DataTable(id="search_results")
        with Vertical(id="sent_view"):
            yield Static("Sent to Kroger (local history)")
            with Horizontal():
                yield DataTable(id="sent_sessions")
                yield DataTable(id="sent_items")
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._update_header()
        self.refresh_data()
        if self.startup_message:
            self._set_status(self.startup_message)
            self.set_timer(3, self._set_mode_status)

    def _setup_tables(self) -> None:
        staples_table = self.query_one("#staples", DataTable)
        staples_table.add_columns("Name", "Term", "Qty", "UPC", "Modality")
        staples_table.cursor_type = "row"

        proposal_table = self.query_one("#proposal", DataTable)
        proposal_table.add_columns("Name", "Qty", "UPC", "Modality", "Status")
        proposal_table.cursor_type = "row"

        alt_table = self.query_one("#alternatives", DataTable)
        alt_table.add_columns("UPC", "Description")
        alt_table.cursor_type = "row"

        results_table = self.query_one("#search_results", DataTable)
        results_table.add_columns("★", "Description", "Size", "Price", "UPC")
        results_table.cursor_type = "row"

        sessions_table = self.query_one("#sent_sessions", DataTable)
        sessions_table.add_columns("Started", "OK", "Failed", "Sources")
        sessions_table.cursor_type = "row"

        items_table = self.query_one("#sent_items", DataTable)
        items_table.add_columns("Name", "Qty", "Status", "Error")
        items_table.cursor_type = "row"

    def _set_alternatives_status(self, message: str | None, *, error: bool = False) -> None:
        status = self.query_one("#alternatives_status", Static)
        status.update(message or "")
        status.remove_class("error")
        if error:
            status.add_class("error")
        status.styles.display = "block" if message else "none"

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        status.remove_class("error")
        if error:
            status.add_class("error")

    def _set_mode_status(self) -> None:
        if not self.location_id:
            self._set_status("Default location is not set.", error=True)
        else:
            self._set_status("Mode: Dry-run (press 'a' to apply)")

    def _update_header(self) -> None:
        auth_status = "logged in" if TokenStore().load() else "not logged in"
        location = self.location_id or "none"
        self.active_list = get_active_list()
        self.sub_title = f"List: {self.active_list} | Location: {location} | Auth: {auth_status}"
        self._update_staples_title()

    def _update_staples_title(self) -> None:
        title = self.query_one("#staples_title", Static)
        title.update(self.active_list or "Staples")

    def refresh_data(self) -> None:
        self.active_list = get_active_list()
        self.staples = get_staples(list_name=self.active_list)
        if not self.proposal:
            self.proposal = Proposal(
                version="1",
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                location_id=self.location_id,
                items=[],
                sources=[],
            )
        self._set_mode_status()
        self._refresh_proposal_ui()

    def on_list_changed(self) -> None:
        self._update_header()
        self.refresh_data()

    def add_list_to_proposal(self, list_name: str) -> None:
        try:
            staples = get_staples(list_name=list_name)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        if not staples:
            self._set_status(f"No staples found in {list_name}.")
            return
        if not self.proposal:
            self.proposal = Proposal(
                version="1",
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                location_id=self.location_id,
                items=[],
                sources=[],
            )
        for staple in staples:
            self.proposal_terms[(staple.name, staple.modality)] = staple.term
        incoming = [
            ProposalItem(
                name=staple.name,
                quantity=staple.quantity,
                modality=staple.modality,
                upc=staple.preferred_upc,
                source="preferred" if staple.preferred_upc else "search",
                sources=[list_name],
            )
            for staple in staples
        ]
        merged_items, added, merged = merge_proposal_items(
            self.proposal.items,
            incoming,
            source=list_name,
        )
        self.proposal.items = merged_items
        sources = set(self.proposal.sources)
        sources.add(list_name)
        self.proposal.sources = sorted(sources)
        self.alternatives_state = {}
        self._refresh_proposal_ui()
        self._set_status(f"Added list {list_name} (+{added} items, {merged} merged).")

    def _refresh_proposal_ui(self, selected_item_id: int | None = None) -> None:
        self._populate_tables()
        self._update_proposal_status()
        if selected_item_id is not None:
            self._restore_proposal_selection(selected_item_id)
        if not self.proposal or not self.proposal.items:
            self.selection.proposal_index = None
        elif (
            self.selection.proposal_index is not None
            and self.selection.proposal_index >= len(self.proposal.items)
        ):
            self.selection.proposal_index = None
        self._update_alternatives()

    def _populate_tables(self) -> None:
        staples_table = self.query_one("#staples", DataTable)
        proposal_table = self.query_one("#proposal", DataTable)
        alt_table = self.query_one("#alternatives", DataTable)

        staples_table.clear()
        proposal_table.clear()
        alt_table.clear()
        self._set_alternatives_status(None)

        for staple in self.staples:
            staples_table.add_row(
                staple.name,
                staple.term,
                str(staple.quantity),
                staple.preferred_upc or "",
                staple.modality,
            )

        if not self.proposal:
            return

        for index, item in enumerate(self.proposal.items):
            if item.upc:
                status = Text("staged", style="green")
            else:
                status = Text("missing", style="red")
            proposal_table.add_row(
                item.name,
                str(item.quantity),
                item.upc or "",
                item.modality,
                status,
                key=str(index),
            )

    def _populate_search_results(self) -> None:
        table = self.query_one("#search_results", DataTable)
        table.clear()
        recent_upcs = {entry.upc for entry in self.recent_entries}
        if self.search_mode == "recent":
            for index, entry in enumerate(self.recent_entries):
                table.add_row(
                    "★",
                    entry.description or entry.term,
                    "",
                    "",
                    entry.upc,
                    key=str(index),
                )
        else:
            for index, product in enumerate(self.search_results):
                fields = product_display_fields(product)
                star = "★" if fields["upc"] in recent_upcs else ""
                table.add_row(
                    star,
                    fields["description"],
                    fields["size"],
                    fields["price"],
                    fields["upc"],
                    key=str(index),
                )

    def _populate_sent(self) -> None:
        sessions_table = self.query_one("#sent_sessions", DataTable)
        items_table = self.query_one("#sent_items", DataTable)
        sessions_table.clear()
        items_table.clear()
        for index, session in enumerate(self.sent_sessions):
            ok = sum(1 for item in session.items if item.status == "success")
            failed = sum(1 for item in session.items if item.status == "failed")
            sources = ", ".join(session.sources)
            sessions_table.add_row(
                session.started_at,
                str(ok),
                str(failed),
                sources,
                key=str(index),
            )
        if self.sent_sessions:
            sessions_table.cursor_coordinate = (0, 0)
            self.selection.sent_index = 0
            self._update_sent_items()

    def _update_proposal_status(self) -> None:
        status = self.query_one("#proposal_status", Static)
        status.update(_proposal_status_text(self.proposal))

    def _update_sent_items(self) -> None:
        items_table = self.query_one("#sent_items", DataTable)
        items_table.clear()
        if self.selection.sent_index is None:
            return
        if self.selection.sent_index >= len(self.sent_sessions):
            return
        session = self.sent_sessions[self.selection.sent_index]
        for item in session.items:
            items_table.add_row(
                item.name,
                str(item.quantity),
                item.status,
                item.error or "",
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "proposal":
            self.selection.proposal_index = event.cursor_row
            self._update_alternatives()
        elif event.data_table.id == "alternatives":
            self.selection.alternative_index = event.cursor_row
        elif event.data_table.id == "search_results":
            self.selection.search_index = event.cursor_row
            if self.search_mode == "recent":
                entry = self._current_recent_entry()
                if entry:
                    self.preselect_upc = entry.upc
                    self._start_search(entry.term)
        elif event.data_table.id == "sent_sessions":
            self.selection.sent_index = event.cursor_row
            self._update_sent_items()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "proposal":
            self.selection.proposal_index = event.cursor_row
            self._update_alternatives()
        elif event.data_table.id == "alternatives":
            self.selection.alternative_index = event.cursor_row
        elif event.data_table.id == "search_results":
            self.selection.search_index = event.cursor_row
        elif event.data_table.id == "sent_sessions":
            self.selection.sent_index = event.cursor_row
            self._update_sent_items()

    def _update_alternatives(self) -> None:
        alt_table = self.query_one("#alternatives", DataTable)
        alt_table.clear()
        if not self.proposal or self.selection.proposal_index is None:
            self._set_alternatives_status(None)
            return
        item = self.proposal.items[self.selection.proposal_index]
        item_id = id(item)
        state = self.alternatives_state.get(item_id)
        if state and state.status == "loading":
            self._set_alternatives_status("Loading alternatives...")
            return
        if state and state.status == "error":
            self._set_alternatives_status(state.error or "Failed to load alternatives.", error=True)
            return
        if item.alternatives:
            self._set_alternatives_status(None)
            for index, alt in enumerate(item.alternatives):
                alt_table.add_row(
                    alt.upc,
                    alt.description or "",
                    key=str(index),
                )
            return
        if state and state.status == "loaded":
            self._set_alternatives_status("No alternatives found.")
            return
        self._start_alternatives_fetch(item)

    def _start_alternatives_fetch(self, item: ProposalItem) -> None:
        if not self.location_id:
            self._set_alternatives_status("Set a default location to load alternatives.", error=True)
            return
        item_id = id(item)
        term = self.proposal_terms.get((item.name, item.modality), item.name)
        self.alternatives_state[item_id] = AlternativesState(status="loading")
        self._set_alternatives_status("Loading alternatives...")
        self.selection.alternative_index = None
        self.run_worker(
            lambda: self._alternatives_worker(item_id, term),
            group=f"alternatives-{item_id}",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _alternatives_worker(self, item_id: int, term: str) -> None:
        try:
            token = auth.get_client_credentials_token(
                base_url=self.config.base_url,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scopes=["product.compact"],
            )
            with KrogerClient(self.config.base_url) as client:
                results = client.products_search(
                    token.access_token,
                    term=term,
                    location_id=self.location_id or "",
                    limit=5,
                )
                alternatives = self._build_alternatives(
                    client,
                    token.access_token,
                    results.data,
                )
            self.call_from_thread(self._handle_alternatives_result, item_id, alternatives, None)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._handle_alternatives_result, item_id, [], str(exc))

    def _build_alternatives(
        self,
        client: KrogerClient,
        token: str,
        products: list,
    ) -> list[ProposalAlternative]:
        alternatives: list[ProposalAlternative] = []
        for product in products[:3]:
            upcs = self._extract_product_upcs(client, token, product)
            if upcs:
                alternatives.append(
                    ProposalAlternative(
                        upc=upcs[0],
                        description=product.description,
                    )
                )
        return alternatives

    def _extract_product_upcs(self, client: KrogerClient, token: str, product: object) -> list[str]:
        upcs: list[str] = []
        items = getattr(product, "items", None)
        if items:
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("upc"), str):
                    upcs.append(item["upc"])
        if not upcs:
            product_id = getattr(product, "productId", None)
            if isinstance(product_id, str):
                try:
                    payload = client.get_product(
                        token,
                        product_id=product_id,
                        location_id=self.location_id or "",
                    )
                    upcs = extract_upcs(payload)
                except KrogerAPIError:
                    upcs = []
        return upcs

    def _handle_alternatives_result(
        self,
        item_id: int,
        alternatives: list[ProposalAlternative],
        error: str | None,
    ) -> None:
        if error:
            self.alternatives_state[item_id] = AlternativesState(
                status="error",
                error=f"Alternatives unavailable: {error}",
            )
        else:
            self.alternatives_state[item_id] = AlternativesState(status="loaded")
        item = self._find_item_by_id(item_id)
        updated_upc = False
        if item and not error:
            updated_upc = _apply_alternatives_to_item(item, alternatives)
        if updated_upc:
            self._refresh_proposal_ui(selected_item_id=item_id)
            return
        if self._selected_item_id() == item_id:
            self._update_alternatives()

    def _find_item_by_id(self, item_id: int) -> ProposalItem | None:
        if not self.proposal:
            return None
        for item in self.proposal.items:
            if id(item) == item_id:
                return item
        return None

    def _restore_proposal_selection(self, item_id: int) -> None:
        if not self.proposal:
            return
        proposal_table = self.query_one("#proposal", DataTable)
        for index, item in enumerate(self.proposal.items):
            if id(item) == item_id:
                self.selection.proposal_index = index
                proposal_table.cursor_coordinate = (index, 0)
                break

    def _selected_item_id(self) -> int | None:
        if not self.proposal or self.selection.proposal_index is None:
            return None
        if self.selection.proposal_index >= len(self.proposal.items):
            return None
        return id(self.proposal.items[self.selection.proposal_index])

    def action_refresh(self) -> None:
        if self.active_view == "planner":
            self.alternatives_state = {}
            self.refresh_data()
        elif self.active_view == "search" and self.search_term:
            self._start_search(self.search_term)
        elif self.active_view == "sent":
            self.sent_sessions, cleaned = load_sent_sessions_with_cleanup()
            self._populate_sent()
            if cleaned:
                self._set_status(f"Cleaned up {cleaned} seed history entries.")

    def action_delete(self) -> None:
        if self.active_view != "planner":
            self._set_status("Switch to Planner to remove items.", error=True)
            return
        staples_table = self.query_one("#staples", DataTable)
        proposal_table = self.query_one("#proposal", DataTable)
        if staples_table.has_focus:
            self._prompt_remove_staple()
            return
        if proposal_table.has_focus:
            if not self.proposal or self.selection.proposal_index is None:
                self._set_status("Select a proposal item to remove.", error=True)
                return
            del self.proposal.items[self.selection.proposal_index]
            self.selection.proposal_index = None
            self.selection.alternative_index = None
            self._refresh_proposal_ui()
            self._set_status("Removed item from proposal.")
            return
        self._set_status("Select a staple or proposal item to remove.", error=True)

    def action_move(self) -> None:
        if self.active_view != "planner":
            self._set_status("Switch to Planner to move staples.", error=True)
            return
        staples_table = self.query_one("#staples", DataTable)
        if not staples_table.has_focus:
            self._set_status("Select a staple to move.", error=True)
            return
        if not self.staples:
            self._set_status("No staples to move.", error=True)
            return
        targets = [name for name in list_names() if name != self.active_list]
        if not targets:
            self._set_status("No other lists available.", error=True)
            return
        index = staples_table.cursor_row
        if index is None or index >= len(self.staples):
            self._set_status("Select a staple to move.", error=True)
            return
        staple = self.staples[index]
        self.push_screen(
            ListSelectScreen("Move to list", targets),
            lambda target: self._confirm_move_staple(staple, target),
        )

    def _prompt_remove_staple(self) -> None:
        if not self.staples:
            self._set_status("No staples to remove.", error=True)
            return
        table = self.query_one("#staples", DataTable)
        index = table.cursor_row
        if index is None or index >= len(self.staples):
            self._set_status("Select a staple to remove.", error=True)
            return
        staple = self.staples[index]
        message = f"Remove '{staple.name}' from list '{self.active_list}'?"
        self.push_screen(
            ConfirmScreen(message, yes_label="Remove", no_label="Cancel"),
            lambda confirmed: self._handle_remove_staple(confirmed, staple),
        )

    def _handle_remove_staple(self, confirmed: bool, staple: Staple) -> None:
        if not confirmed:
            self._set_status("Remove canceled.")
            return
        identifier = staple.preferred_upc or staple.name
        try:
            remove_staple(identifier, list_name=self.active_list)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self.staples = get_staples(list_name=self.active_list)
        self._populate_tables()
        self._set_status(f"Removed from {self.active_list}")

    def _confirm_move_staple(self, staple: Staple, target: str | None) -> None:
        if not target:
            self._set_status("Move canceled.")
            return
        message = f"Move '{staple.name}' from '{self.active_list}' to '{target}'?"
        self.push_screen(
            ConfirmScreen(message, yes_label="Move", no_label="Cancel"),
            lambda confirmed: self._handle_move_staple(confirmed, staple, target),
        )

    def _handle_move_staple(self, confirmed: bool, staple: Staple, target: str) -> None:
        if not confirmed:
            self._set_status("Move canceled.")
            return
        identifier = staple.preferred_upc or staple.name
        try:
            move_item(self.active_list, target, identifier)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self.staples = get_staples(list_name=self.active_list)
        self._populate_tables()
        self._set_status(f"Moved to {target}")


    def action_pin(self) -> None:
        if self.active_view == "search":
            if not self.query_one("#search_results", DataTable).has_focus:
                return
            self._start_pin_search_result()
        else:
            self._pin_proposal_alternative()

    async def action_apply(self) -> None:
        if self.active_view != "planner":
            self._set_status("Switch to Planner to apply proposal.", error=True)
            return
        if not self.proposal or not self.proposal.items:
            self._set_status("No proposal to apply.", error=True)
            return
        self.push_screen(ConfirmScreen("Apply proposal to cart?"), self._handle_confirm)

    def action_focus_search(self) -> None:
        self._show_search_view()
        self.query_one("#search_input", Input).focus()

    def action_save_staple(self) -> None:
        if self.active_view != "search":
            return
        if not self.query_one("#search_results", DataTable).has_focus:
            return
        self._save_search_as_staple()

    def action_lists(self) -> None:
        self.push_screen(ListManagerScreen(self))

    def action_back(self) -> None:
        if self.screen.is_modal:
            return
        if self.active_view in {"search", "sent"}:
            self._show_planner_view()
            self._set_status("Back to planner.")

    def action_clear_proposal(self) -> None:
        if not self.proposal or not self.proposal.items:
            self._set_status("Proposal is already empty.")
            return
        self.push_screen(
            ConfirmScreen("Clear proposal?", yes_label="Clear", no_label="Cancel"),
            self._handle_clear_confirm,
        )

    def action_open_cart(self) -> None:
        if self.active_view != "sent":
            return
        webbrowser.open("https://www.kroger.com/cart")

    def _handle_clear_confirm(self, confirmed: bool) -> None:
        if not confirmed:
            self._set_status("Clear canceled.")
            return
        if not self.proposal:
            return
        self.proposal.items = []
        self.proposal.sources = []
        self._refresh_proposal_ui()
        self._set_status("Proposal cleared.")

    def _handle_confirm(self, confirmed: bool) -> None:
        if not confirmed:
            self._set_status("Apply canceled.")
            return
        self.run_worker(
            self._apply_proposal,
            group="apply",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _apply_proposal(self) -> None:
        if not self.proposal or not self.proposal.items:
            self.call_from_thread(self._set_status, "No proposal to apply.", error=True)
            return
        try:
            token = auth.load_user_token(self.config)
        except auth.KrogerAuthError as exc:
            self.call_from_thread(self._set_status, str(exc), error=True)
            return
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        success, failed, errors, results = apply_proposal_items(
            config=self.config,
            token=token.access_token,
            items=self.proposal.items if self.proposal else [],
            stop_on_error=False,
        )
        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        session = session_from_apply_results(
            results,
            location_id=self.location_id,
            sources=self.proposal.sources if self.proposal else [],
            started_at=started_at,
            finished_at=finished_at,
        )
        record_sent_session(session)
        if errors:
            message = errors[0]
            self.call_from_thread(self._set_status, message, error=True)
        summary = f"Applied: {success} succeeded, {failed} failed"
        self.call_from_thread(self._set_status, summary, error=failed > 0)

    def _pin_proposal_alternative(self) -> None:
        if not self.proposal or self.selection.proposal_index is None:
            self._set_status("Select a proposal item.", error=True)
            return
        if self.selection.alternative_index is None:
            self._set_status("Select an alternative UPC to pin.", error=True)
            return

        item = self.proposal.items[self.selection.proposal_index]
        if self.selection.alternative_index >= len(item.alternatives):
            self._set_status("Invalid alternative selection.", error=True)
            return
        chosen = item.alternatives[self.selection.alternative_index]

        try:
            update_staple(item.name, preferred_upc=chosen.upc, list_name=self.active_list)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return

        item.upc = chosen.upc
        item.source = "preferred"
        self.pinned[item.name] = True
        item.alternatives = []
        self.alternatives_state.pop(id(item), None)
        for staple in self.staples:
            if staple.name == item.name:
                staple.preferred_upc = chosen.upc
                break

        self._refresh_proposal_ui(selected_item_id=id(item))
        self._set_status(f"Pinned UPC {chosen.upc} for {item.name}.")

    def _show_search_view(self) -> None:
        if self.active_view == "search":
            return
        self.active_view = "search"
        self.add_class("search-active")
        self.remove_class("sent-active")
        self._load_recent_entries("")

    def _show_planner_view(self) -> None:
        if self.active_view == "planner":
            return
        self.active_view = "planner"
        self.remove_class("search-active")
        self.remove_class("sent-active")

    def _show_sent_view(self) -> None:
        if self.active_view == "sent":
            return
        self.active_view = "sent"
        self.add_class("sent-active")
        self.remove_class("search-active")
        self.sent_sessions, cleaned = load_sent_sessions_with_cleanup()
        self._populate_sent()
        if cleaned:
            self._set_status(f"Cleaned up {cleaned} seed history entries.")
        else:
            self._set_status("Sent to Kroger (local history).")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_search":
            self._show_search_view()
            self.query_one("#search_input", Input).focus()
        elif event.button.id == "nav_planner":
            self._show_planner_view()
        elif event.button.id == "nav_sent":
            self._show_sent_view()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            term = event.value.strip()
            if not term:
                self._set_status("Enter a search term.", error=True)
                return
            self._start_search(term)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input":
            self._load_recent_entries(event.value)

    def _set_search_loading(self, loading: bool) -> None:
        indicator = self.query_one("#search_loading", LoadingIndicator)
        indicator.styles.display = "block" if loading else "none"

    def _load_recent_entries(self, query: str) -> None:
        entries = load_recent_searches()
        query = query.strip().lower()
        if query:
            entries = [
                entry
                for entry in entries
                if query in entry.term.lower() or query in entry.description.lower()
            ]
        self.recent_entries = entries
        self.search_mode = "recent"
        self._populate_search_results()

    def _start_search(self, term: str) -> None:
        if not self.location_id:
            self._set_status("Default location is not set.", error=True)
            return
        if self.search_inflight:
            return
        self.search_term = term
        self.search_mode = "results"
        self.search_inflight = True
        self._set_search_loading(True)
        self._set_status(f"Searching '{term}'...")
        self.run_worker(
            lambda: self._search_worker(term),
            group="search",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _search_worker(self, term: str) -> None:
        try:
            token = auth.get_client_credentials_token(
                base_url=self.config.base_url,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scopes=["product.compact"],
            )
            with KrogerClient(self.config.base_url) as client:
                results = client.products_search(
                    token.access_token,
                    term=term,
                    location_id=self.location_id or "",
                    limit=25,
                )
            self.call_from_thread(self._handle_search_results, results.data, None)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._handle_search_results, [], str(exc))

    def _handle_search_results(self, results, error: str | None) -> None:
        self.search_results = results
        self._set_search_loading(False)
        self.search_inflight = False
        if error:
            self._set_status(f"Search failed: {error}", error=True)
        else:
            self._set_status(f"Found {len(results)} result(s).")
        self._populate_search_results()
        if results:
            self.query_one("#search_results", DataTable).focus()
            if self.preselect_upc:
                self._preselect_upc_row(self.preselect_upc)
                self.preselect_upc = None

    def _preselect_upc_row(self, upc: str) -> None:
        table = self.query_one("#search_results", DataTable)
        for index, product in enumerate(self.search_results):
            fields = product_display_fields(product)
            if fields["upc"] == upc:
                table.cursor_coordinate = (index, 0)
                self.selection.search_index = index
                return

    def _current_search_product(self):
        if self.selection.search_index is None:
            self._set_status("Select a search result.", error=True)
            return None
        if self.selection.search_index >= len(self.search_results):
            self._set_status("Invalid search selection.", error=True)
            return None
        return self.search_results[self.selection.search_index]

    def _current_recent_entry(self) -> RecentSearchEntry | None:
        if self.selection.search_index is None:
            return None
        if self.selection.search_index >= len(self.recent_entries):
            return None
        return self.recent_entries[self.selection.search_index]

    def _resolve_upc_for_product(self, product) -> str | None:
        fields = product_display_fields(product)
        if fields["upc"]:
            return fields["upc"]
        try:
            token = auth.get_client_credentials_token(
                base_url=self.config.base_url,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scopes=["product.compact"],
            )
            with KrogerClient(self.config.base_url) as client:
                payload = client.get_product(
                    token.access_token,
                    product_id=product.productId,
                    location_id=self.location_id or "",
                )
            upcs = extract_upcs(payload)
            return upcs[0] if upcs else None
        except KrogerAPIError:
            return None

    def _start_add_to_cart_flow(self) -> None:
        product = self._current_search_product()
        if not product:
            return
        self.push_screen(
            QuantityScreen(default=1, title="Add to cart quantity"),
            lambda qty: self._handle_cart_quantity(qty, product),
        )

    def _handle_cart_quantity(self, quantity: int | None, product) -> None:
        if not quantity:
            self._set_status("Add to cart canceled.")
            return
        self.push_screen(
            ConfirmScreen(f"Add {quantity} to cart?"),
            lambda confirmed: self._confirm_add_to_cart(confirmed, product, quantity),
        )

    def _confirm_add_to_cart(self, confirmed: bool, product, quantity: int) -> None:
        if not confirmed:
            self._set_status("Add to cart canceled.")
            return
        self._set_status("Adding to cart...")
        self.run_worker(
            lambda: self._add_to_cart_worker(product, quantity),
            group="cart-add",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _add_to_cart_worker(self, product, quantity: int) -> None:
        try:
            token = auth.load_user_token(self.config)
            upc = self._resolve_upc_for_product(product)
            if not upc:
                self.call_from_thread(self._set_status, "No UPC found for item.", error=True)
                return
            item = ProposalItem(
                name=product.description or "item",
                quantity=quantity,
                modality="PICKUP",
                upc=upc,
            )
            started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            success, failed, errors, results = apply_proposal_items(
                config=self.config,
                token=token.access_token,
                items=[item],
                stop_on_error=False,
            )
            finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            session = session_from_apply_results(
                results,
                location_id=self.location_id,
                sources=[],
                kind="quick_add",
                started_at=started_at,
                finished_at=finished_at,
            )
            record_sent_session(session)
            if errors:
                self.call_from_thread(self._set_status, errors[0], error=True)
            else:
                record_recent_search(
                    term=self.search_term or product.description or "",
                    upc=upc,
                    description=product.description or "",
                )
                self.call_from_thread(
                    self._set_status,
                    f"Added to cart ({success} ok, {failed} failed).",
                )
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._set_status, f"Add to cart failed: {exc}", error=True)

    def _save_search_as_staple(self) -> None:
        product = self._current_search_product()
        if not product:
            return
        self._set_status("Resolving UPC...")
        self.run_worker(
            lambda: self._resolve_upcs_worker(product),
            group="staple-upc",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _resolve_upcs_worker(self, product) -> None:
        fields = product_display_fields(product)
        if fields["upc"]:
            self.call_from_thread(self._handle_resolved_upcs, product, [fields["upc"]])
            return
        try:
            token = auth.get_client_credentials_token(
                base_url=self.config.base_url,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scopes=["product.compact"],
            )
            with KrogerClient(self.config.base_url) as client:
                payload = client.get_product(
                    token.access_token,
                    product_id=product.productId,
                    location_id=self.location_id or "",
                )
            upcs = extract_upcs(payload)
            self.call_from_thread(self._handle_resolved_upcs, product, upcs)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._set_status, f"UPC lookup failed: {exc}", error=True)

    def _handle_resolved_upcs(self, product, upcs: list[str]) -> None:
        if not upcs:
            self._set_status("No UPC found for item.", error=True)
            return
        if len(upcs) == 1:
            self._prompt_staple_details(product, upcs[0])
            return
        self.push_screen(
            UPCSelectScreen(upcs),
            lambda selected: self._handle_upc_selection(product, selected),
        )

    def _handle_upc_selection(self, product, selected: str | None) -> None:
        if not selected:
            self._set_status("UPC selection canceled.")
            return
        self._prompt_staple_details(product, selected)

    def _prompt_staple_details(self, product, upc: str) -> None:
        default_name = normalize_staple_name(product.description or self.search_term or "staple")
        default_term = self.search_term or product.description or default_name
        self.push_screen(
            StapleScreen(
                default_name=default_name,
                default_term=default_term,
                default_quantity=1,
                default_modality=self.default_modality,
            ),
            lambda result: self._handle_save_staple(result, upc),
        )

    def _handle_save_staple(self, result, upc: str) -> None:
        if result is None:
            self._set_status("Save item canceled.")
            return
        name, term, quantity, modality = result
        exists = any(staple.name == name for staple in self.staples)
        if exists:
            self.push_screen(
                ConfirmScreen(
                    f"Staple '{name}' exists. Overwrite?",
                    yes_label="Overwrite",
                    no_label="Cancel",
                ),
                lambda confirmed: self._handle_overwrite_confirm(
                    confirmed, name, term, quantity, modality, upc
                ),
            )
            return
        self._save_staple_record(name, term, quantity, modality, upc, overwrite=False)

    def _handle_overwrite_confirm(
        self,
        confirmed: bool,
        name: str,
        term: str,
        quantity: int,
        modality: str,
        upc: str,
    ) -> None:
        if not confirmed:
            self._set_status("Save item canceled.")
            return
        self._save_staple_record(name, term, quantity, modality, upc, overwrite=True)

    def _save_staple_record(
        self,
        name: str,
        term: str,
        quantity: int,
        modality: str,
        upc: str,
        overwrite: bool,
    ) -> None:
        self._set_status("Saving item...")
        self.run_worker(
            lambda: self._save_staple_worker(name, term, quantity, modality, upc, overwrite),
            group="staple-save",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _save_staple_worker(
        self,
        name: str,
        term: str,
        quantity: int,
        modality: str,
        upc: str,
        overwrite: bool,
    ) -> None:
        try:
            if overwrite:
                update_staple(
                    name,
                    term=term,
                    quantity=quantity,
                    preferred_upc=upc,
                    modality=modality,
                    list_name=self.active_list,
                )
            else:
                add_staple(
                    Staple(
                        name=name,
                        term=term,
                        quantity=quantity,
                        preferred_upc=upc,
                        modality=modality,
                    ),
                    list_name=self.active_list,
                )
            record_recent_search(term=term, upc=upc, description=name)
            self.call_from_thread(self._set_status, f"Saved item '{name}'.")
            self.call_from_thread(self.refresh_data)
            self.call_from_thread(
                lambda: self.push_screen(
                    ConfirmScreen(
                        "Regenerate proposal now?",
                        yes_label="Regenerate",
                        no_label="Later",
                    ),
                    lambda confirmed: self._maybe_regenerate(confirmed),
                )
            )
        except ValueError as exc:
            self.call_from_thread(self._set_status, str(exc), error=True)

    def _maybe_regenerate(self, confirmed: bool) -> None:
        if confirmed:
            self.refresh_data()

    def _pin_search_result(self) -> None:
        product = self._current_search_product()
        if not product:
            return
        self._set_status("Pinning UPC...")
        self.run_worker(
            lambda: self._pin_search_worker(product),
            group="pin",
            exclusive=True,
            exit_on_error=False,
            thread=True,
        )

    def _pin_search_worker(self, product) -> None:
        upc = self._resolve_upc_for_product(product)
        if not upc:
            self.call_from_thread(self._set_status, "No UPC found for item.", error=True)
            return
        match = None
        term = (self.search_term or "").lower()
        for staple in self.staples:
            if staple.name.lower() == term or staple.term.lower() == term:
                match = staple
                break
        if not match:
            self.call_from_thread(self._set_status, "No matching staple to pin.", error=True)
            return
        try:
            update_staple(match.name, preferred_upc=upc, list_name=self.active_list)
        except ValueError as exc:
            self.call_from_thread(self._set_status, str(exc), error=True)
            return
        self.call_from_thread(self._set_status, f"Pinned UPC {upc} to staple '{match.name}'.")
        self.call_from_thread(self.refresh_data)

    def on_key(self, event) -> None:
        if self.screen.is_modal:
            return
        if self.active_view != "search":
            return
        if not self.query_one("#search_results", DataTable).has_focus:
            return
        if event.key in {"enter", "return"}:
            if self.search_mode == "recent":
                entry = self._current_recent_entry()
                if entry:
                    self.preselect_upc = entry.upc
                    self._start_search(entry.term)
                elif self.search_term:
                    self._start_search(self.search_term)
            else:
                self._start_add_to_cart_flow()
            event.stop()


def run_tui(
    *,
    initial_proposal: Proposal | None = None,
    startup_message: str | None = None,
) -> None:
    KrogetApp(initial_proposal=initial_proposal, startup_message=startup_message).run()
