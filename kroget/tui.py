from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from rich.text import Text
from textual.widgets import Button, DataTable, Footer, Header, Static

from kroget.core.proposal import Proposal, apply_proposal_items, generate_proposal
from kroget.core.storage import ConfigStore, KrogerConfig, Staple, TokenStore, load_staples, update_staple
from kroget.kroger import auth


@dataclass
class SelectionState:
    proposal_index: int | None = None
    alternative_index: int | None = None


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Static(self.message, id="confirm_message")
        with Horizontal(id="confirm_buttons"):
            yield Button("Apply", id="confirm_yes", variant="success")
            yield Button("Cancel", id="confirm_no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm_yes")


class KrogetApp(App):
    CSS = """
    #main {
        height: 1fr;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #status.error {
        color: $error;
    }

    #left, #center, #right {
        border: solid $panel;
        padding: 1;
        width: 1fr;
    }

    DataTable {
        height: 1fr;
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
        ("r", "refresh", "Regenerate"),
        ("p", "pin", "Pin UPC"),
        ("d", "delete", "Remove"),
        ("a", "apply", "Apply"),
        ("q", "quit", "Quit"),
    ]

    TITLE = "Kro-Get"

    def __init__(self) -> None:
        super().__init__()
        self.config = KrogerConfig.from_env()
        self.location_id = ConfigStore().load().default_location_id
        self.staples: list[Staple] = []
        self.proposal: Proposal | None = None
        self.pinned: dict[str, bool] = {}
        self.selection = SelectionState()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Mode: Dry-run", id="status")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("Staples")
                yield DataTable(id="staples")
            with Vertical(id="center"):
                yield Static("Proposal")
                yield DataTable(id="proposal")
            with Vertical(id="right"):
                yield Static("Alternatives")
                yield DataTable(id="alternatives")
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._update_header()
        self.refresh_data()

    def _setup_tables(self) -> None:
        staples_table = self.query_one("#staples", DataTable)
        staples_table.add_columns("Name", "Term", "Qty", "UPC", "Modality")

        proposal_table = self.query_one("#proposal", DataTable)
        proposal_table.add_columns("Name", "Qty", "UPC", "Modality", "Status")
        proposal_table.cursor_type = "row"

        alt_table = self.query_one("#alternatives", DataTable)
        alt_table.add_columns("UPC", "Description")
        alt_table.cursor_type = "row"

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        status.remove_class("error")
        if error:
            status.add_class("error")

    def _update_header(self) -> None:
        auth_status = "logged in" if TokenStore().load() else "not logged in"
        location = self.location_id or "none"
        self.sub_title = f"Location: {location} | Auth: {auth_status}"

    def refresh_data(self) -> None:
        self.staples = load_staples()
        if not self.staples:
            self.proposal = None
            self._populate_tables()
            self._set_status("No staples configured.", error=True)
            return
        if not self.location_id:
            self.proposal = None
            self._populate_tables()
            self._set_status("Default location is not set.", error=True)
            return

        try:
            self.proposal, self.pinned = generate_proposal(
                config=self.config,
                staples=self.staples,
                location_id=self.location_id,
                auto_pin=False,
                confirm_pin=None,
            )
            self._set_status("Mode: Dry-run (press 'a' to apply)")
        except Exception as exc:  # noqa: BLE001
            self.proposal = None
            self._set_status(f"Error generating proposal: {exc}", error=True)
        self._populate_tables()

    def _populate_tables(self) -> None:
        staples_table = self.query_one("#staples", DataTable)
        proposal_table = self.query_one("#proposal", DataTable)
        alt_table = self.query_one("#alternatives", DataTable)

        staples_table.clear()
        proposal_table.clear()
        alt_table.clear()

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
            pinned = self.pinned.get(item.name, False)
            if pinned:
                status = Text("pinned", style="green")
            elif item.upc:
                status = Text("auto", style="yellow")
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "proposal":
            if event.row_key is None:
                return
            self.selection.proposal_index = int(str(event.row_key))
            self._update_alternatives()
        elif event.data_table.id == "alternatives":
            if event.row_key is None:
                return
            self.selection.alternative_index = int(str(event.row_key))

    def _update_alternatives(self) -> None:
        alt_table = self.query_one("#alternatives", DataTable)
        alt_table.clear()
        if not self.proposal or self.selection.proposal_index is None:
            return
        item = self.proposal.items[self.selection.proposal_index]
        for index, alt in enumerate(item.alternatives):
            alt_table.add_row(
                alt.upc,
                alt.description or "",
                key=str(index),
            )

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_delete(self) -> None:
        if not self.proposal or self.selection.proposal_index is None:
            self._set_status("Select a proposal item to remove.", error=True)
            return
        del self.proposal.items[self.selection.proposal_index]
        self.selection.proposal_index = None
        self.selection.alternative_index = None
        self._populate_tables()
        self._set_status("Removed item from proposal.")

    def action_pin(self) -> None:
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
            update_staple(item.name, preferred_upc=chosen.upc)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return

        item.upc = chosen.upc
        item.source = "preferred"
        self.pinned[item.name] = True
        for staple in self.staples:
            if staple.name == item.name:
                staple.preferred_upc = chosen.upc
                break

        self._populate_tables()
        self._update_alternatives()
        self._set_status(f"Pinned UPC {chosen.upc} for {item.name}.")

    async def action_apply(self) -> None:
        if not self.proposal:
            self._set_status("No proposal to apply.", error=True)
            return
        self.push_screen(ConfirmScreen("Apply proposal to cart?"), self._handle_confirm)

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
        try:
            token = auth.load_user_token(self.config)
        except auth.KrogerAuthError as exc:
            self.call_from_thread(self._set_status, str(exc), error=True)
            return

        success, failed, errors = apply_proposal_items(
            config=self.config,
            token=token.access_token,
            items=self.proposal.items if self.proposal else [],
            stop_on_error=False,
        )
        if errors:
            message = errors[0]
            self.call_from_thread(self._set_status, message, error=True)
        summary = f"Applied: {success} succeeded, {failed} failed"
        self.call_from_thread(self._set_status, summary, error=failed > 0)


def run_tui() -> None:
    KrogetApp().run()
