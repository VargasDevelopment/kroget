from __future__ import annotations

import importlib.metadata
import json
import os
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import httpx
import typer
from dotenv import load_dotenv
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from typer.core import TyperGroup

from kroget.core.product_upc import extract_upcs, pick_upc
from kroget.core.proposal import Proposal, ProposalItem, apply_proposal_items, generate_proposal
from kroget.core.paths import data_dir
from kroget.core.sent_items import load_sent_sessions, record_sent_session, session_from_apply_results
from kroget.core.storage import (
    ConfigError,
    ConfigStore,
    KrogerConfig,
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

console = Console()


def _format_validation_fields(exc: ValidationError, limit: int = 2) -> list[str]:
    fields: list[str] = []
    for error in exc.errors():
        loc = error.get("loc")
        if not loc:
            continue
        field = ".".join(str(part) for part in loc if part is not None)
        if field and field not in fields:
            fields.append(field)
        if len(fields) >= limit:
            break
    return fields


def _format_path(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _tip_for_path(path: str | None) -> str | None:
    if not path:
        return "Check the path and try again."
    lowered = path.lower()
    if "proposal" in lowered:
        return "Generate it with `kroget proposal ...` or the TUI."
    return "Check the path and try again."


def _emit_cli_error(message: str, *, tip: str | None = None, detail: str | None = None) -> None:
    console.print(f"[red]{message}[/red]")
    if detail:
        console.print(f"[yellow]{detail}[/yellow]")
    if tip:
        console.print(f"[yellow]Tip:[/yellow] {tip}")


def _handle_cli_exception(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        path = _format_path(getattr(exc, "filename", None))
        _emit_cli_error(
            f"File not found: {path or 'unknown'}",
            tip=_tip_for_path(path),
        )
        return
    if isinstance(exc, (IsADirectoryError, NotADirectoryError)):
        path = _format_path(getattr(exc, "filename", None))
        _emit_cli_error(
            f"Invalid path: {path or 'unknown'}",
            tip="Check the path and try again.",
        )
        return
    if isinstance(exc, json.JSONDecodeError):
        path = _format_path(getattr(exc, "path", None))
        tip = "Delete and regenerate this file."
        if path and "proposal" in path.lower():
            tip = "Regenerate proposal using `kroget proposal ...` or the TUI."
        _emit_cli_error(
            f"Invalid JSON in {path or 'file'}",
            tip=tip,
        )
        return
    if isinstance(exc, ValidationError):
        path = _format_path(getattr(exc, "path", None))
        fields = _format_validation_fields(exc)
        detail = f"Fields: {', '.join(fields)}" if fields else None
        tip = "Check the input and try again."
        message = f"Invalid data format in {path or 'input'}"
        if path and "proposal" in path.lower():
            message = f"Invalid proposal format in {path}"
            tip = "Regenerate proposal using `kroget proposal ...` or the TUI."
        _emit_cli_error(
            message,
            tip=tip,
            detail=detail,
        )
        return
    if isinstance(exc, KrogerAPIError):
        if exc.status_code in {401, 403}:
            _emit_cli_error(
                "Not authenticated or token expired.",
                tip="Run `kroget auth login`.",
            )
            return
        _emit_cli_error(
            f"Network/API error: {exc}",
            tip="Run `kroget doctor` to validate connectivity/auth.",
        )
        return
    if isinstance(exc, auth.KrogerAuthError):
        message = str(exc)
        if "401" in message or "403" in message:
            _emit_cli_error(
                "Not authenticated or token expired.",
                tip="Run `kroget auth login`.",
            )
            return
        _emit_cli_error(
            f"Network/API error: {exc}",
            tip="Run `kroget doctor` to validate connectivity/auth.",
        )
        return
    if isinstance(exc, httpx.RequestError):
        _emit_cli_error(
            f"Network/API error: {exc}",
            tip="Run `kroget doctor` to validate connectivity/auth.",
        )
        return
    _emit_cli_error(
        f"Unexpected error: {exc.__class__.__name__}",
        tip="Please open an issue and include the command you ran.",
    )


class SafeTyperGroup(TyperGroup):
    def main(self, *args, **kwargs):  # type: ignore[override]
        try:
            return super().main(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            _handle_cli_exception(exc)
            raise SystemExit(1) from exc


app = typer.Typer(
    help="Kroger shopping CLI",
    cls=SafeTyperGroup,
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
)
products_app = typer.Typer(help="Product search commands")
auth_app = typer.Typer(help="Authentication commands")
cart_app = typer.Typer(help="Cart commands")
locations_app = typer.Typer(help="Location commands")
staples_app = typer.Typer(
    help="Deprecated (removed in v1.0.0); use `kroget lists items`"
)
proposal_app = typer.Typer(help="Proposal commands")
lists_app = typer.Typer(help="List management commands")
lists_items_app = typer.Typer(help="List item commands")
sent_app = typer.Typer(help="Sent items history commands")

app.add_typer(products_app, name="products")
app.add_typer(auth_app, name="auth")
app.add_typer(cart_app, name="cart")
app.add_typer(locations_app, name="locations")
app.add_typer(staples_app, name="staples")
app.add_typer(proposal_app, name="proposal")
app.add_typer(lists_app, name="lists")
app.add_typer(sent_app, name="sent")

lists_app.add_typer(lists_items_app, name="items")

DEFAULT_REDIRECT_URI = "http://localhost:8400/callback"
KROGER_PORTAL_URL = "https://developer.kroger.com/"


def _warn_staples_deprecated() -> None:
    """
    Print a deprecation warning for the "staples" commands.
    
    Prints a message to stderr stating that `kroget staples` is deprecated and will be removed in v1.0.0 and advising to use `kroget lists items ...` instead.
    """
    typer.echo(
        "kroget staples is deprecated and will be removed in v1.0.0; "
        "use `kroget lists items ...`",
        err=True,
    )


def _resolve_list_name(list_name: str | None) -> str:
    """
    Resolve a list name, using the active list when none is provided.
    
    Parameters:
        list_name (str | None): Optional list name to use.
    
    Returns:
        list_name (str): The provided list name, or the currently active list if `list_name` is None.
    """
    return list_name or get_active_list()


def _resolve_list_and_value(
    list_name: str | None,
    value: str | None,
    *,
    value_label: str,
) -> tuple[str, str]:
    """
    Resolve a list name and an associated value, using the active list as a fallback.
    
    If `value` is provided, returns (list_name_or_active, value). If `value` is None but `list_name` is provided, treats the provided `list_name` as the value and returns (active_list, list_name). If both `list_name` and `value` are None, prints an error and exits with code 1.
    
    Parameters:
        value_label (str): Human-readable label for `value` used in the error message when both inputs are missing.
    
    Returns:
        tuple[str, str]: A pair (resolved_list_name, resolved_value).
    """
    if value is None:
        if list_name is None:
            console.print(f"[red]{value_label} required.[/red]")
            raise typer.Exit(code=1)
        return get_active_list(), list_name
    return list_name or get_active_list(), value


def _print_version(value: bool) -> None:
    """
    Print the application version and exit if the version option is enabled.
    
    Parameters:
        value (bool): If enabled, prints "kroget <version>" (or "kroget unknown" if package metadata is unavailable) and exits the program.
    """
    if not value:
        return
    try:
        version = importlib.metadata.version("kroget")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    typer.echo(f"kroget {version}")
    raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show the kroget version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    return


def _load_config() -> KrogerConfig:
    try:
        return load_kroger_config()
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _load_user_config(store: ConfigStore | None = None) -> UserConfig:
    return (store or ConfigStore()).load()


def _resolve_location_id(location_id: str | None) -> str | None:
    if location_id:
        return location_id
    config = _load_user_config()
    return config.default_location_id


def _run_doctor_checks(
    *,
    config: KrogerConfig,
    location_id: str | None,
    term: str,
) -> None:
    console.print("[bold]Kroger API doctor[/bold]")
    try:
        token = auth.get_client_credentials_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=["product.compact"],
        )
        console.print("[green]OK[/green] client credentials token acquired")
    except auth.KrogerAuthError as exc:
        console.print(f"[red]FAIL[/red] token request failed: {exc}")
        raise

    resolved_location_id = _resolve_location_id(location_id)

    if resolved_location_id:
        try:
            with KrogerClient(config.base_url) as client:
                results = client.products_search(
                    token.access_token, term=term, location_id=resolved_location_id, limit=1
                )
            count = len(results.data)
            console.print(
                f"[green]OK[/green] product search returned {count} item(s) for '{term}'"
            )
        except KrogerAPIError as exc:
            console.print(f"[red]FAIL[/red] product search failed: {exc}")
            raise
    else:
        console.print(
            "[yellow]SKIP[/yellow] product search (no --location-id or default set)"
        )


def _format_products_table(products):
    table = Table(title="Kroger Products")
    table.add_column("Product ID", style="bold")
    table.add_column("Description")
    table.add_column("Brand")
    table.add_column("UPC")

    for product in products:
        upc = None
        if product.items:
            first_item = product.items[0] or {}
            upc = first_item.get("upc")
        table.add_row(
            product.productId,
            product.description or "",
            product.brand or "",
            upc or "",
        )
    return table


def _format_locations_table(locations):
    """
    Builds a Rich Table summarizing Kroger location records.
    
    Parameters:
        locations (iterable[dict]): An iterable of mapping objects representing Kroger locations (as returned by the API). Each mapping may include top-level keys like "locationId" and "name", and an "address" sub-mapping with "addressLine1", "city", "state", and "zipCode".
    
    Returns:
        table (rich.table.Table): A Rich Table with columns "Location ID", "Name", "Address", "City", "State", and "Zip", containing one row per provided location. Empty or missing fields are rendered as empty strings.
    """
    table = Table(title="Kroger Locations")
    table.add_column("Location ID", style="bold")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("City")
    table.add_column("State")
    table.add_column("Zip")

    for location in locations:
        address = location.get("address", {}) if isinstance(location, dict) else {}
        table.add_row(
            str(location.get("locationId", "")),
            str(location.get("name", "")),
            str(address.get("addressLine1", "")),
            str(address.get("city", "")),
            str(address.get("state", "")),
            str(address.get("zipCode", "")),
        )
    return table


def _format_items_table(staples: list[Staple], list_name: str | None = None) -> Table:
    """
    Builds a Rich Table representing a list of staples (items), suitable for console display.
    
    Parameters:
        staples (list[Staple]): Sequence of Staple objects to render as rows.
        list_name (str | None): Optional list name used in the table title; when provided the title becomes "Items (<list_name>)".
    
    Returns:
        table (rich.table.Table): A table with columns "Name", "Term", "Qty", "UPC", and "Modality" and a title of "Items" or "Items (<list_name>)".
    """
    title = "Items"
    if list_name:
        title = f"Items ({list_name})"
    table = Table(title=title)
    table.add_column("Name", style="bold")
    table.add_column("Term")
    table.add_column("Qty")
    table.add_column("UPC")
    table.add_column("Modality")
    for staple in staples:
        table.add_row(
            staple.name,
            staple.term,
            str(staple.quantity),
            staple.preferred_upc or "",
            staple.modality,
        )
    return table


def _format_proposal_table(items: list[ProposalItem], pinned: dict[str, bool]) -> Table:
    table = Table(title="Proposal")
    table.add_column("Name", style="bold")
    table.add_column("Qty")
    table.add_column("UPC")
    table.add_column("Pinned")
    table.add_column("Confidence")
    for item in items:
        is_pinned = pinned.get(item.name, False)
        confidence = "pinned" if is_pinned else ("auto" if item.upc else "missing")
        table.add_row(
            item.name,
            str(item.quantity),
            item.upc or "",
            "yes" if is_pinned else "no",
            confidence,
        )
    return table


@app.command()
def doctor(
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    term: str = typer.Option("milk", "--term", help="Search term for product test"),
) -> None:
    """Validate Kroger API connectivity and credentials."""
    config = _load_config()
    try:
        _run_doctor_checks(config=config, location_id=location_id, term=term)
    except (auth.KrogerAuthError, KrogerAPIError) as exc:
        raise typer.Exit(code=1) from exc


@app.command()
def setup(
    client_id: str | None = typer.Option(None, "--client-id", help="Kroger client ID"),
    client_secret: str | None = typer.Option(
        None, "--client-secret", help="Kroger client secret"
    ),
    redirect_uri: str | None = typer.Option(
        None, "--redirect-uri", help="OAuth redirect URI"
    ),
    location_id: str | None = typer.Option(
        None, "--location-id", help="Default location ID"
    ),
    open_portal: bool | None = typer.Option(
        None,
        "--open-portal/--no-open-portal",
        help="Open Kroger developer portal",
    ),
    run_login: bool | None = typer.Option(
        None,
        "--run-login/--no-run-login",
        help="Run kroget auth login after setup",
    ),
    yes: bool = typer.Option(False, "--yes", help="Accept defaults and skip confirmations"),
) -> None:
    """Guided setup for Kroger API credentials.

    Examples:
      kroget setup
      kroget setup --client-id ... --client-secret ... --redirect-uri http://localhost:8400/callback
      kroget setup --client-id ... --client-secret ... --redirect-uri http://localhost:8400/callback --location-id 01400441
    """
    load_dotenv()
    store = ConfigStore()
    config = store.load()

    env_client_id = os.getenv("KROGER_CLIENT_ID")
    env_client_secret = os.getenv("KROGER_CLIENT_SECRET")
    env_redirect_uri = os.getenv("KROGER_REDIRECT_URI")

    has_client_id = bool(client_id or config.kroger_client_id or env_client_id)
    has_client_secret = bool(client_secret or config.kroger_client_secret or env_client_secret)
    missing_creds = not (has_client_id and has_client_secret)

    if missing_creds:
        console.print("[bold]Kroger developer app setup[/bold]")
        console.print("1) Create a Kroger developer app (Production).")
        console.print("2) Enable Products (Public) + Cart (Public) + Profile (Public)+ Location (Public).")
        console.print("3) Set redirect URI to:")
        console.print(f"   {redirect_uri or config.kroger_redirect_uri or DEFAULT_REDIRECT_URI}")

    if open_portal is None:
        open_portal = missing_creds
    if open_portal:
        should_open = yes or typer.confirm(
            "Open Kroger developer portal in your browser?", default=True
        )
        if should_open:
            opened = webbrowser.open(KROGER_PORTAL_URL)
            if not opened:
                console.print("Open this URL to continue:")
                console.print(KROGER_PORTAL_URL)

    if client_id is not None:
        config.kroger_client_id = client_id.strip() or None
    elif not config.kroger_client_id and env_client_id and not yes:
        if typer.confirm("Use KROGER_CLIENT_ID from environment for config.json?", default=False):
            config.kroger_client_id = env_client_id
    if not config.kroger_client_id:
        if yes:
            console.print("[red]Missing required client ID. Pass --client-id or run without --yes.[/red]")
            raise typer.Exit(code=1)
        value = typer.prompt("Kroger Client ID")
        config.kroger_client_id = value.strip() or None

    if client_secret is not None:
        config.kroger_client_secret = client_secret.strip() or None
    elif not config.kroger_client_secret and env_client_secret and not yes:
        if typer.confirm(
            "Use KROGER_CLIENT_SECRET from environment for config.json?", default=False
        ):
            config.kroger_client_secret = env_client_secret
    if not config.kroger_client_secret:
        if yes:
            console.print(
                "[red]Missing required client secret. Pass --client-secret or run without --yes.[/red]"
            )
            raise typer.Exit(code=1)
        value = typer.prompt("Kroger Client Secret", hide_input=True)
        config.kroger_client_secret = value.strip() or None

    default_redirect = config.kroger_redirect_uri or DEFAULT_REDIRECT_URI
    if redirect_uri is not None:
        config.kroger_redirect_uri = redirect_uri.strip() or None
    elif not config.kroger_redirect_uri and env_redirect_uri and not yes:
        if typer.confirm(
            "Use KROGER_REDIRECT_URI from environment for config.json?", default=False
        ):
            config.kroger_redirect_uri = env_redirect_uri
    if not config.kroger_redirect_uri:
        if yes:
            config.kroger_redirect_uri = default_redirect
        else:
            value = typer.prompt("Redirect URI", default=default_redirect)
            config.kroger_redirect_uri = value.strip() or None

    if location_id is not None:
        config.default_location_id = location_id.strip() or None
    elif not yes:
        value = typer.prompt(
            "Default location ID (optional)",
            default=config.default_location_id or "",
            show_default=bool(config.default_location_id),
        )
        config.default_location_id = value.strip() or None

    if config.default_modality is None:
        if yes:
            config.default_modality = "PICKUP"
        else:
            value = typer.prompt(
                "Default modality (PICKUP or DELIVERY)",
                default=config.default_modality or "PICKUP",
            ).strip().upper()
            if value not in {"PICKUP", "DELIVERY"}:
                console.print("[red]Invalid modality. Use PICKUP or DELIVERY.[/red]")
                raise typer.Exit(code=1)
            config.default_modality = value

    store.save(config)
    console.print(f"[green]Saved config:[/green] {data_dir() / 'config.json'}")

    try:
        validated = load_kroger_config(store=store)
        _run_doctor_checks(
            config=validated,
            location_id=config.default_location_id,
            term="milk",
        )
    except (ConfigError, auth.KrogerAuthError, KrogerAPIError) as exc:
        console.print(f"[red]Setup validation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if run_login is None:
        if yes:
            run_login = False
        else:
            run_login = typer.confirm(
                "Do you want to log in now to enable cart actions?", default=False
            )
    if run_login:
        auth_login()
    else:
        console.print("Run `kroget auth login` when you're ready.")

@products_app.command("search")
def products_search(
    term: str = typer.Argument(..., help="Search term"),
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Search products by term and location ID."""
    config = _load_config()

    try:
        token = auth.get_client_credentials_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=["product.compact"],
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    resolved_location_id = _resolve_location_id(location_id)
    if not resolved_location_id:
        console.print("[red]Location ID required.[/red] Use --location-id or set default.")
        raise typer.Exit(code=1)

    try:
        with KrogerClient(config.base_url) as client:
            results = client.products_search(
                token.access_token,
                term=term,
                location_id=resolved_location_id,
                limit=limit,
            )
    except KrogerAPIError as exc:
        console.print(f"[red]Search failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(results.model_dump()))
    else:
        table = _format_products_table(results.data)
        console.print(table)


@products_app.command("get")
def products_get(
    product_id: str = typer.Argument(..., help="Product ID"),
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """
    Display details for a Kroger product identified by product_id.
    
    If --json is provided, prints the raw API payload; otherwise prints product ID, description, brand, and UPCs if present. Requires a resolved location ID (passed via --location-id or set as default); on missing location, authentication failure, or API error the command prints an error and exits with code 1.
    
    Parameters:
        location_id (str | None): Location ID to scope the product lookup; if None the default location from user config will be used.
        as_json (bool): When true, output the raw JSON payload instead of formatted fields.
    """
    config = _load_config()
    resolved_location_id = _resolve_location_id(location_id)
    if not resolved_location_id:
        console.print("[red]Location ID required.[/red] Use --location-id or set default.")
        raise typer.Exit(code=1)

    try:
        token = auth.get_client_credentials_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=["product.compact"],
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        with KrogerClient(config.base_url) as client:
            payload = client.get_product(
                token.access_token,
                product_id=product_id,
                location_id=resolved_location_id,
            )
    except KrogerAPIError as exc:
        console.print(f"[red]Product get failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(payload))
        return

    upcs = extract_upcs(payload)
    data = payload.get("data")
    product = None
    if isinstance(data, list) and data:
        product = data[0]
    elif isinstance(data, dict):
        product = data

    if isinstance(product, dict):
        description = product.get("description", "")
        brand = product.get("brand", "")
        console.print(f"[bold]Product ID:[/bold] {product_id}")
        console.print(f"[bold]Description:[/bold] {description}")
        console.print(f"[bold]Brand:[/bold] {brand}")
    if upcs:
        console.print(f"[bold]UPCs:[/bold] {', '.join(upcs)}")
    else:
        console.print("[yellow]No UPCs found in response.[/yellow]")


def _normalize_modality(modality: str) -> str:
    """
    Normalize and validate a modality string to its canonical uppercase form.
    
    Parameters:
        modality (str): Input modality; expected values are "PICKUP" or "DELIVERY" (case-insensitive).
    
    Returns:
        str: The normalized modality, either "PICKUP" or "DELIVERY".
    
    Raises:
        typer.Exit: Exits with code 1 if the provided modality is not "PICKUP" or "DELIVERY".
    """
    normalized = modality.upper()
    if normalized not in {"PICKUP", "DELIVERY"}:
        console.print("[red]Invalid modality.[/red] Use PICKUP or DELIVERY.")
        raise typer.Exit(code=1)
    return normalized


def _items_add(
    *,
    list_name: str,
    name: str,
    term: str,
    quantity: int,
    upc: str | None,
    modality: str,
    label: str,
) -> None:
    """
    Add an item to the specified list and persist it to storage.
    
    Parameters:
        list_name (str): Name of the list to add the item to.
        name (str): Human-readable name of the item.
        term (str): Search term or canonical descriptor associated with the item.
        quantity (int): Desired quantity for the item.
        upc (str | None): Preferred UPC for the item, if available.
        modality (str): Fulfillment modality, e.g., "PICKUP" or "DELIVERY"; will be normalized and validated.
        label (str): Label used in user-facing messages (e.g., "item" or "staple").
    
    Raises:
        typer.Exit: Exits with code 1 if the item cannot be added due to a ValueError from storage.
    """
    normalized_modality = _normalize_modality(modality)
    staple = Staple(
        name=name,
        term=term,
        quantity=quantity,
        preferred_upc=upc,
        modality=normalized_modality,
    )
    try:
        add_staple(staple, list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Added {label}:[/green] {name}")


def _items_list(
    *,
    list_name: str,
    as_json: bool,
    json_key: str,
) -> None:
    """
    Print items from a named list either as JSON or as a formatted table.
    
    If `as_json` is true, emits a JSON object whose top-level key is `json_key`
    and whose value is a list of item dictionaries. Otherwise renders and prints
    a table of items for `list_name`.
    
    Parameters:
        list_name (str): Name of the list to load items from.
        as_json (bool): When true, output the items as JSON instead of a table.
        json_key (str): Top-level key to use in the emitted JSON payload.
    
    Raises:
        typer.Exit: If loading the list fails (propagates a non-recoverable error).
    """
    try:
        staples = get_staples(list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if as_json:
        payload = {json_key: [staple.to_dict() for staple in staples]}
        console.print_json(json.dumps(payload))
        return
    table = _format_items_table(staples, list_name)
    console.print(table)


def _items_remove(*, list_name: str, identifier: str, label: str) -> None:
    """
    Remove an entry identified by `identifier` from the specified list and print a success message.
    
    Parameters:
        list_name (str): Name of the list to remove the entry from.
        identifier (str): Identifier of the entry to remove (e.g., name, id, or UPC).
        label (str): Human-readable label used in the success message (e.g., "item" or "staple").
    
    Raises:
        typer.Exit: Exits with code 1 if removal fails (propagates when underlying storage raises ValueError).
    """
    try:
        remove_staple(identifier, list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Removed {label}:[/green] {identifier}")


def _items_move(
    *,
    source_list: str,
    target_list: str,
    identifier: str,
    label: str,
) -> None:
    """
    Move an item from one list to another and print a success message.
    
    Parameters:
        source_list (str): Name of the list to move the item from.
        target_list (str): Name of the list to move the item to.
        identifier (str): Identifier of the item to move (name, id, or matching key).
        label (str): Human-readable label used in success/output messages.
    
    Raises:
        typer.Exit: Exits with code 1 if the underlying move operation fails.
    """
    try:
        move_item(source_list, target_list, identifier)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Moved {label} to:[/green] {target_list}")


def _items_set(
    *,
    list_name: str,
    name: str,
    term: str | None,
    quantity: int | None,
    upc: str | None,
    modality: str | None,
    label: str,
) -> None:
    """
    Update an item (staple) in a named list with the provided fields.
    
    Updates the stored staple matching `name` in `list_name` with any supplied `term`, `quantity`, `preferred_upc`, and `modality`. If `modality` is provided it is normalized to the canonical value (e.g., "PICKUP" or "DELIVERY"). On validation or storage errors the command prints an error and exits with code 1.
    
    Parameters:
        list_name (str): Name of the list containing the item to update.
        name (str): Identifier/name of the item to update.
        term (str | None): Optional search term or description to store for the item.
        quantity (int | None): Optional desired quantity for the item.
        upc (str | None): Optional preferred UPC to associate with the item.
        modality (str | None): Optional fulfillment modality; will be normalized if provided.
        label (str): Human-readable label used in success messages (e.g., "item" or "staple").
    """
    if modality is not None:
        modality = _normalize_modality(modality)
    try:
        update_staple(
            name,
            term=term,
            quantity=quantity,
            preferred_upc=upc,
            modality=modality,
            list_name=list_name,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Updated {label}:[/green] {name}")


def _items_propose(
    *,
    list_name: str,
    location_id: str | None,
    out: Path,
    as_json: bool,
    auto_pin: bool,
    empty_message: str,
    item_label: str,
) -> None:
    """
    Generate a proposal from a list of staples/items for a resolved location and persist it to disk.
    
    Generates a shopping proposal for the given list_name using the resolved location_id, optionally prompting to pin UPCs (unless auto_pin is true), saves the proposal to the specified output path, and prints either JSON or a formatted table along with status messages.
    
    Parameters:
    	list_name (str): Name of the list to generate a proposal from.
    	location_id (str | None): Explicit location ID to use; if None the function will attempt to use the configured default.
    	out (Path): Filesystem path where the generated proposal will be saved.
    	as_json (bool): If true, print the proposal as JSON; otherwise print a formatted proposal table and a saved message.
    	auto_pin (bool): If true, automatically pin UPCs without prompting; otherwise prompt per item.
    	empty_message (str): Message to display when the list contains no items/staples.
    	item_label (str): Label to use in prompts/messages for each list entry (e.g., "item" or "staple").
    
    Raises:
    	typer.Exit: Exits with code 1 if no location_id can be resolved, if loading the list fails, if the list is empty, or if an authentication error occurs while generating the proposal.
    """
    config = _load_config()
    resolved_location_id = _resolve_location_id(location_id)
    if not resolved_location_id:
        console.print("[red]Location ID required.[/red] Use --location-id or set default.")
        raise typer.Exit(code=1)

    try:
        staples = get_staples(list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not staples:
        console.print(f"[yellow]{empty_message}[/yellow]")
        raise typer.Exit(code=1)

    def confirm_pin(staple: Staple, upc: str) -> bool:
        """
        Prompt the user to confirm pinning a specific UPC to a staple.
        
        Parameters:
            staple (Staple): The staple whose name will be shown in the prompt.
            upc (str): The UPC value proposed to be pinned.
        
        Returns:
            bool: `true` if the user confirms pinning, `false` otherwise (prompt defaults to `false`).
        """
        return typer.confirm(f"Pin UPC {upc} for {item_label} '{staple.name}'?", default=False)

    try:
        proposal, pinned = generate_proposal(
            config=config,
            staples=staples,
            location_id=resolved_location_id,
            list_name=list_name,
            auto_pin=auto_pin,
            confirm_pin=None if auto_pin else confirm_pin,
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    proposal.save(out)

    if as_json:
        console.print_json(json.dumps(proposal.model_dump()))
    else:
        table = _format_proposal_table(proposal.items, pinned)
        console.print(table)
        console.print(f"[green]Proposal saved:[/green] {out}")


@lists_items_app.command("add")
def lists_items_add(
    list_name: str | None = typer.Argument(
        None, help="List name (defaults to active list)"
    ),
    name: str | None = typer.Argument(None, help="Item name"),
    term: str = typer.Option(..., "--term", help="Search term"),
    quantity: int = typer.Option(1, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str = typer.Option("PICKUP", "--modality", help="PICKUP or DELIVERY"),
) -> None:
    """
    Add an item to a list.
    
    Resolves a default list and item name when omitted, then records the item with the provided search term, quantity, optional UPC, and modality.
    
    Parameters:
        list_name (str | None): List name (defaults to the active list when omitted).
        name (str | None): Item name (resolved or prompted if omitted).
        term (str): Search term associated with the item.
        quantity (int): Quantity to add (must be >= 1).
        upc (str | None): Preferred UPC to associate with the item.
        modality (str): "PICKUP" or "DELIVERY".
    """
    list_name, name = _resolve_list_and_value(
        list_name,
        name,
        value_label="Item name",
    )
    _items_add(
        list_name=list_name,
        name=name,
        term=term,
        quantity=quantity,
        upc=upc,
        modality=modality,
        label="item",
    )


@lists_items_app.command("list")
def lists_items_list(
    list_name: str | None = typer.Argument(
        None, help="List name (defaults to active list)"
    ),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """
    List items from a named or the active list.
    
    Prints a formatted table of items for the resolved list, or outputs raw JSON when `as_json` is true.
    
    Parameters:
        list_name (str | None): Name of the list to show; if omitted, the current active list is used.
        as_json (bool): If true, emit the raw JSON payload instead of a formatted table.
    """
    _items_list(
        list_name=_resolve_list_name(list_name),
        as_json=as_json,
        json_key="items",
    )


@lists_items_app.command("remove")
def lists_items_remove(
    list_name: str | None = typer.Argument(
        None, help="List name (defaults to active list)"
    ),
    identifier: str | None = typer.Argument(None, help="Item name or preferred UPC"),
) -> None:
    """
    Remove an item from the specified list.
    
    Parameters:
        list_name (str | None): Name of the list to remove the item from. If omitted, the active list is used.
        identifier (str | None): Item name or preferred UPC that identifies the item to remove.
    """
    list_name, identifier = _resolve_list_and_value(
        list_name,
        identifier,
        value_label="Item identifier",
    )
    _items_remove(list_name=list_name, identifier=identifier, label="item")


@lists_items_app.command("move")
def lists_items_move(
    list_name: str | None = typer.Argument(
        None, help="Source list name (defaults to active list)"
    ),
    identifier: str | None = typer.Argument(None, help="Item name or preferred UPC"),
    to_list: str = typer.Option(..., "--to", help="Target list name"),
) -> None:
    """
    Move an item identified by name or UPC from a source list to a target list.
    
    Parameters:
        list_name (str | None): Source list name; uses the active list when omitted.
        identifier (str | None): Item name or preferred UPC to identify the item to move.
        to_list (str): Target list name to move the item into.
    """
    list_name, identifier = _resolve_list_and_value(
        list_name,
        identifier,
        value_label="Item identifier",
    )
    _items_move(
        source_list=list_name,
        target_list=to_list,
        identifier=identifier,
        label="item",
    )


@lists_items_app.command("set")
def lists_items_set(
    list_name: str | None = typer.Argument(
        None, help="List name (defaults to active list)"
    ),
    name: str | None = typer.Argument(None, help="Item name"),
    term: str | None = typer.Option(None, "--term", help="Search term"),
    quantity: int | None = typer.Option(None, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str | None = typer.Option(None, "--modality", help="PICKUP or DELIVERY"),
) -> None:
    """
    Update an item in a list.
    
    Parameters:
        list_name (str | None): List name; when None the active list is used.
        name (str): Name of the item to update.
        term (str | None): New search term for the item.
        quantity (int | None): New quantity (must be >= 1).
        upc (str | None): Preferred UPC to set for the item.
        modality (str | None): Delivery modality; either "PICKUP" or "DELIVERY".
    """
    list_name, name = _resolve_list_and_value(
        list_name,
        name,
        value_label="Item name",
    )
    _items_set(
        list_name=list_name,
        name=name,
        term=term,
        quantity=quantity,
        upc=upc,
        modality=modality,
        label="item",
    )


@lists_items_app.command("propose")
def lists_items_propose(
    list_name: str | None = typer.Argument(
        None, help="List name (defaults to active list)"
    ),
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    out: Path = typer.Option(Path("proposal.json"), "--out", help="Output proposal path"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
    auto_pin: bool = typer.Option(False, "--auto-pin", help="Auto-pin UPCs"),
) -> None:
    """
    Generate a proposal for the specified list and persist it to a file.
    
    Creates a proposal for the resolved list (uses the active list when none is provided) for the given location and writes it to `out`. When `as_json` is true, the raw proposal JSON is written to stdout; otherwise a human-readable table is displayed. When `auto_pin` is true, UPCs will be automatically pinned during proposal generation.
    
    Parameters:
        list_name (str | None): List name; defaults to the active list when omitted.
        location_id (str | None): Location identifier used to tailor the proposal.
        out (Path): File path where the proposal will be saved (default: "proposal.json").
        as_json (bool): If true, output the raw proposal JSON instead of formatted output.
        auto_pin (bool): If true, automatically pin UPCs during proposal generation.
    """
    _items_propose(
        list_name=_resolve_list_name(list_name),
        location_id=location_id,
        out=out,
        as_json=as_json,
        auto_pin=auto_pin,
        empty_message="No items configured.",
        item_label="item",
    )


@staples_app.command("add")
def staples_add(
    name: str = typer.Argument(..., help="Staple name"),
    term: str = typer.Option(..., "--term", help="Search term"),
    quantity: int = typer.Option(1, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str = typer.Option("PICKUP", "--modality", help="PICKUP or DELIVERY"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """
    Add a staple to a list (deprecated).
    
    This command adds a staple item with the given name, search term, quantity, preferred UPC, and modality to the specified list. Deprecated: use the `kroget lists items` commands instead.
    
    Parameters:
        name (str): Staple name.
        term (str): Search term used to identify the item.
        quantity (int): Quantity to add (must be >= 1).
        upc (str | None): Preferred UPC to associate with the staple, if any.
        modality (str): Either "PICKUP" or "DELIVERY".
        list_name (str | None): Optional list name to which the staple will be added; if omitted, the active list is used.
    """
    _warn_staples_deprecated()
    _items_add(
        list_name=list_name or get_active_list(),
        name=name,
        term=term,
        quantity=quantity,
        upc=upc,
        modality=modality,
        label="staple",
    )


@staples_app.command("list")
def staples_list(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """
    List staples from the configured staple list (deprecated; use `kroget lists items` instead).
    
    Parameters:
        as_json (bool): If true, print the raw JSON payload instead of a formatted table.
        list_name (str | None): Optional list name to use instead of the active list.
    """
    _warn_staples_deprecated()
    _items_list(
        list_name=list_name or get_active_list(),
        as_json=as_json,
        json_key="staples",
    )


@staples_app.command("remove")
def staples_remove(
    identifier: str = typer.Argument(..., help="Staple name or preferred UPC"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """
    Remove a staple by name or UPC from the specified staples list.
    
    Parameters:
        identifier (str): Staple name or preferred UPC to remove.
        list_name (str | None): Optional list name override; if omitted, the active list is used.
    """
    _warn_staples_deprecated()
    _items_remove(
        list_name=list_name or get_active_list(),
        identifier=identifier,
        label="staple",
    )


@staples_app.command("move")
def staples_move(
    identifier: str = typer.Argument(..., help="Staple name or preferred UPC"),
    to_list: str = typer.Option(..., "--to", help="Target list name"),
    from_list: str | None = typer.Option(None, "--from", help="Source list override"),
) -> None:
    """
    Move a staple from the active list (or a specified source list) to another list.
    
    Parameters:
        identifier (str): Staple name or preferred UPC to identify the item to move.
        to_list (str): Target list name.
        from_list (str | None): Optional source list override; if omitted, the active list is used.
    
    """
    _warn_staples_deprecated()
    _items_move(
        source_list=from_list or get_active_list(),
        target_list=to_list,
        identifier=identifier,
        label="staple",
    )


@staples_app.command("set")
def staples_set(
    name: str = typer.Argument(..., help="Staple name"),
    term: str | None = typer.Option(None, "--term", help="Search term"),
    quantity: int | None = typer.Option(None, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str | None = typer.Option(None, "--modality", help="PICKUP or DELIVERY"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """
    Update an existing staple in a list.
    
    Parameters:
    	name (str): The staple's name to identify which item to update.
    	term (str | None): Optional search term to associate with the staple.
    	quantity (int | None): Optional quantity to set; must be greater than or equal to 1.
    	upc (str | None): Optional preferred UPC to assign to the staple.
    	modality (str | None): Optional fulfillment modality; expected values are "PICKUP" or "DELIVERY".
    	list_name (str | None): Optional list name to target; when omitted, the active list is used.
    """
    _warn_staples_deprecated()
    _items_set(
        list_name=list_name or get_active_list(),
        name=name,
        term=term,
        quantity=quantity,
        upc=upc,
        modality=modality,
        label="staple",
    )


@staples_app.command("propose")
def staples_propose(
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    out: Path = typer.Option(Path("proposal.json"), "--out", help="Output proposal path"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
    auto_pin: bool = typer.Option(False, "--auto-pin", help="Auto-pin UPCs"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """
    Generate a proposal file from the configured staples and save it to the given path.
    
    Parameters:
        location_id (str | None): Override the store location to use for proposal generation; if omitted the active/default location is used when available.
        out (Path): Filesystem path where the proposal JSON will be written.
        as_json (bool): If true, print the raw proposal JSON to the console instead of formatted output.
        auto_pin (bool): If true, automatically pin UPCs for staples without prompting the user.
        list_name (str | None): Override which staples list to use; when omitted the active list is used.
    
    Deprecated:
        This command is deprecated; prefer the `lists items propose` command for equivalent functionality.
    """
    _warn_staples_deprecated()
    _items_propose(
        list_name=list_name or get_active_list(),
        location_id=location_id,
        out=out,
        as_json=as_json,
        auto_pin=auto_pin,
        empty_message="No staples configured.",
        item_label="staple",
    )


@locations_app.command("search")
def locations_search(
    zip_code: str | None = typer.Option(None, "--zip", help="ZIP code"),
    radius: int = typer.Option(10, "--radius", help="Radius in miles"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    chain: str | None = typer.Option(None, "--chain", help="Chain name"),
    lat: float | None = typer.Option(None, "--lat", help="Latitude"),
    lon: float | None = typer.Option(None, "--lon", help="Longitude"),
    lat_long: str | None = typer.Option(None, "--lat-long", help="Lat,long combined"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """
    Search for Kroger store locations near a given ZIP code or geographic coordinates.
    
    Requires either `zip_code`, `lat_long`, or both `lat` and `lon`. Results are printed as a formatted table by default or as raw JSON when `as_json` is true.
    
    Parameters:
        zip_code (str | None): ZIP code to search near.
        radius (int): Search radius in miles.
        limit (int): Maximum number of results to return.
        chain (str | None): Filter results to a specific store chain.
        lat (float | None): Latitude for proximity search (must be provided with `lon`).
        lon (float | None): Longitude for proximity search (must be provided with `lat`).
        lat_long (str | None): Combined "lat,lon" string for proximity search.
        as_json (bool): If true, print the raw JSON response instead of a table.
    """
    config = _load_config()

    if not any([zip_code, lat_long, (lat is not None and lon is not None)]):
        console.print(
            "[red]Provide --zip, --lat-long, or both --lat and --lon for location search.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        token = auth.get_client_credentials_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=["product.compact"],
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        with KrogerClient(config.base_url) as client:
            response = client.locations_search(
                token.access_token,
                zip_code_near=zip_code,
                lat_long_near=lat_long,
                lat_near=lat,
                lon_near=lon,
                radius_in_miles=radius,
                limit=limit,
                chain=chain,
            )
    except KrogerAPIError as exc:
        console.print(f"[red]Location search failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(response))
        return

    data = response.get("data", [])
    table = _format_locations_table(data if isinstance(data, list) else [])
    console.print(table)


@locations_app.command("get")
def locations_get(
    location_id: str = typer.Argument(..., help="Location ID"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Get location details by location ID."""
    config = _load_config()
    try:
        token = auth.get_client_credentials_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=["product.compact"],
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        with KrogerClient(config.base_url) as client:
            response = client.get_location(token.access_token, location_id)
    except KrogerAPIError as exc:
        console.print(f"[red]Location get failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(response))
        return

    data = response.get("data", {})
    if isinstance(data, dict):
        table = _format_locations_table([data])
        console.print(table)
    else:
        console.print_json(json.dumps(response))


@locations_app.command("set-default")
def locations_set_default(location_id: str = typer.Argument(..., help="Location ID")) -> None:
    """Set default location ID used by other commands."""
    store = ConfigStore()
    config = store.load()
    config.default_location_id = location_id
    store.save(config)
    console.print(f"[green]Default location set:[/green] {location_id}")



@lists_app.command("list")
def lists_list() -> None:
    """List all staple lists."""
    names = list_names()
    active = get_active_list()
    for name in names:
        marker = "*" if name == active else " "
        console.print(f"{marker} {name}")


@lists_app.command("create")
def lists_create(name: str = typer.Argument(..., help="List name")) -> None:
    """Create a new list."""
    try:
        create_list(name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Created list:[/green] {name}")


@lists_app.command("set-active")
def lists_set_active(name: str = typer.Argument(..., help="List name")) -> None:
    """Set the active list."""
    try:
        set_active_list(name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Active list:[/green] {name}")


@lists_app.command("rename")
def lists_rename(
    old_name: str = typer.Argument(..., help="Old list name"),
    new_name: str = typer.Argument(..., help="New list name"),
) -> None:
    """Rename a list."""
    try:
        rename_list(old_name, new_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Renamed list:[/green] {old_name} -> {new_name}")


@lists_app.command("delete")
def lists_delete(name: str = typer.Argument(..., help="List name")) -> None:
    """Delete a list."""
    try:
        delete_list(name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Deleted list:[/green] {name}")


@sent_app.command("list")
def sent_list(as_json: bool = typer.Option(False, "--json", help="Output raw JSON")) -> None:
    """List sent sessions."""
    sessions = load_sent_sessions()
    if as_json:
        payload = {"sessions": [session.to_dict() for session in sessions]}
        console.print_json(json.dumps(payload))
        return
    table = Table(title="Sent Sessions")
    table.add_column("Session ID", style="bold")
    table.add_column("Started")
    table.add_column("Finished")
    table.add_column("Location")
    table.add_column("OK")
    table.add_column("Failed")
    table.add_column("Sources")
    for session in sessions:
        ok = sum(1 for item in session.items if item.status == "success")
        failed = sum(1 for item in session.items if item.status == "failed")
        table.add_row(
            session.session_id,
            session.started_at,
            session.finished_at,
            session.location_id or "",
            str(ok),
            str(failed),
            ", ".join(session.sources),
        )
    console.print(table)


@sent_app.command("show")
def sent_show(session_id: str = typer.Argument(..., help="Session ID")) -> None:
    """Show a sent session."""
    sessions = load_sent_sessions()
    session = next((s for s in sessions if s.session_id == session_id), None)
    if not session:
        console.print(f"[red]Session not found:[/red] {session_id}")
        raise typer.Exit(code=1)
    table = Table(title=f"Sent Items ({session_id})")
    table.add_column("Name", style="bold")
    table.add_column("UPC")
    table.add_column("Qty")
    table.add_column("Modality")
    table.add_column("Status")
    table.add_column("Error")
    for item in session.items:
        table.add_row(
            item.name,
            item.upc,
            str(item.quantity),
            item.modality,
            item.status,
            item.error or "",
        )
    console.print(table)


@proposal_app.command("apply")
def proposal_apply(
    proposal_path: Path = typer.Argument(..., help="Proposal JSON file"),
    apply: bool = typer.Option(False, "--apply", help="Apply changes to cart"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
    stop_on_error: bool = typer.Option(False, "--stop-on-error", help="Stop on first error"),
) -> None:
    """Apply a proposal by adding items to cart."""
    config = _load_config()
    proposal = Proposal.load(proposal_path)

    if apply and not proposal.items:
        console.print("[yellow]No proposal to apply.[/yellow]")
        raise typer.Exit(code=1)

    try:
        token = auth.load_user_token(config, TokenStore())
    except auth.KrogerAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not apply:
        console.print("[yellow]Dry run.[/yellow] Use --apply to add to cart.")
        table = Table(title="Proposal Apply")
        table.add_column("Name", style="bold")
        table.add_column("UPC")
        table.add_column("Qty")
        table.add_column("Modality")
        for item in proposal.items:
            table.add_row(
                item.name,
                item.upc or "",
                str(item.quantity),
                item.modality,
            )
        console.print(table)
        return

    if not yes:
        confirmed = typer.confirm("Apply proposal to cart?", default=False)
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=1)

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    success, failed, errors, results = apply_proposal_items(
        config=config,
        token=token.access_token,
        items=proposal.items,
        stop_on_error=stop_on_error,
    )
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for error in errors:
        console.print(f"[red]{error}[/red]")

    session = session_from_apply_results(
        results,
        location_id=proposal.location_id,
        sources=proposal.sources,
        started_at=started_at,
        finished_at=finished_at,
    )
    record_sent_session(session)

    console.print(f"[green]Applied:[/green] {success} succeeded, {failed} failed")


@auth_app.command("login")
def auth_login(
    scopes: str = typer.Option(
        "profile.compact cart.basic:write product.compact",
        "--scopes",
        help="OAuth scopes",
    ),
    port: int = typer.Option(8400, "--port", help="Local callback port"),
) -> None:
    """Perform OAuth login to access user-scoped APIs."""
    config = _load_config()
    scope_list = auth.parse_scopes(scopes)
    redirect_uri = config.redirect_uri or f"http://localhost:{port}/callback"
    parsed = urlparse(redirect_uri)
    if parsed.port and parsed.port != port:
        console.print(
            f"[yellow]Port overridden to {parsed.port} to match redirect URI.[/yellow]"
        )
        port = parsed.port
    callback_path = parsed.path or "/callback"

    state = auth.generate_state()
    authorize_url = auth.build_authorize_url(
        base_url=config.base_url,
        client_id=config.client_id,
        redirect_uri=redirect_uri,
        scopes=scope_list,
        state=state,
    )

    console.print("Opening browser for Kroger login...")
    opened = webbrowser.open(authorize_url)
    if not opened:
        console.print("Open this URL to continue:")
        console.print(authorize_url)

    try:
        code = auth.wait_for_auth_code(port=port, path=callback_path, state=state)
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Auth failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        token = auth.exchange_auth_code_token(
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            code=code,
            redirect_uri=redirect_uri,
            scopes=scope_list,
        )
    except auth.KrogerAuthError as exc:
        console.print(f"[red]Token exchange failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    TokenStore().save(token)
    console.print("[green]Logged in.[/green]")

    if "profile.compact" in scope_list:
        try:
            with KrogerClient(config.base_url) as client:
                profile = client.profile(token.access_token)
            console.print("[green]Profile OK.[/green]")
            console.print_json(json.dumps(profile))
        except KrogerAPIError as exc:
            console.print(f"[yellow]Profile check failed:[/yellow] {exc}")


@cart_app.command("add")
def cart_add(
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    upc: str | None = typer.Option(None, "--upc", help="Item UPC"),
    product_id: str | None = typer.Option(None, "--product-id", help="Product ID"),
    quantity: int = typer.Option(1, "--quantity", min=1, help="Quantity"),
    modality: str = typer.Option("PICKUP", "--modality", help="PICKUP or DELIVERY"),
    apply: bool = typer.Option(False, "--apply", help="Apply changes to cart"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
    debug: bool = typer.Option(False, "--debug", help="Print request details on failure"),
) -> None:
    """Add an item to the user cart (requires explicit confirmation)."""
    config = _load_config()
    store = TokenStore()
    token = store.load()
    if not token or not token.refresh_token:
        console.print("[red]No user token found.[/red] Run 'kroget auth login' first.")
        raise typer.Exit(code=1)

    modality = modality.upper()
    if modality not in {"PICKUP", "DELIVERY"}:
        console.print("[red]Invalid modality.[/red] Use PICKUP or DELIVERY.")
        raise typer.Exit(code=1)

    if upc and product_id:
        console.print("[red]Provide either --upc or --product-id (not both).[/red]")
        raise typer.Exit(code=1)
    if not upc and not product_id:
        console.print("[red]Provide --upc or --product-id.[/red]")
        raise typer.Exit(code=1)

    if auth.is_token_expired(token):
        try:
            token = auth.refresh_access_token(
                base_url=config.base_url,
                client_id=config.client_id,
                client_secret=config.client_secret,
                refresh_token=token.refresh_token,
                scopes=token.scopes,
            )
        except auth.KrogerAuthError as exc:
            console.print(f"[red]Token refresh failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        store.save(token)

    resolved_upc = upc
    if not resolved_upc and product_id:
        resolved_location_id = _resolve_location_id(location_id)
        if not resolved_location_id:
            console.print(
                "[red]Location ID required to resolve product details.[/red] "
                "Use --location-id or set a default."
            )
            raise typer.Exit(code=1)
        try:
            with KrogerClient(config.base_url) as client:
                product_payload = client.get_product(
                    token.access_token,
                    product_id=product_id,
                    location_id=resolved_location_id,
                )
            upcs = extract_upcs(product_payload)
        except KrogerAPIError as exc:
            console.print(f"[red]Product detail failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if not upcs:
            console.print(
                "[red]No UPC found for product.[/red] "
                "Try `kroget products get <id> --json` to inspect the response."
            )
            raise typer.Exit(code=1)
        if product_id in upcs:
            resolved_upc = product_id
        else:
            resolved_upc = pick_upc(upcs)
        if len(upcs) > 1 and resolved_upc != product_id:
            console.print(
                f"[yellow]Multiple UPCs found; using {resolved_upc}. "
                "Use --upc to override.[/yellow]"
            )

    payload_preview = {
        "items": [{"upc": resolved_upc, "quantity": quantity, "modality": modality}],
    }

    if not apply:
        console.print("[yellow]Dry run.[/yellow] Use --apply to add to cart.")
        console.print_json(json.dumps(payload_preview))
        return

    if not yes:
        confirmed = typer.confirm("Add item to cart?", default=False)
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=1)

    try:
        with KrogerClient(config.base_url) as client:
            response = client.add_to_cart(
                token.access_token,
                product_id=resolved_upc,
                quantity=quantity,
                modality=modality,
                return_status=debug,
            )
        console.print("[green]Added to cart.[/green]")
        if debug and isinstance(response, dict) and "_status_code" in response:
            console.print(f"[yellow]Status:[/yellow] {response['_status_code']}")
        if response:
            response_to_print = dict(response)
            response_to_print.pop("_status_code", None)
            if response_to_print:
                console.print_json(json.dumps(response_to_print))
    except KrogerAPIError as exc:
        console.print(f"[red]Cart add failed:[/red] {exc}")
        if debug:
            console.print("[yellow]Debug request:[/yellow]")
            console.print_json(
                json.dumps(
                    {
                        "url": f"{config.base_url.rstrip('/')}/v1/cart/add",
                        "payload": payload_preview,
                        "error": str(exc),
                        "response_text": getattr(exc, "response_text", None),
                        "status_code": getattr(exc, "status_code", None),
                    }
                )
            )
        raise typer.Exit(code=1) from exc


@app.command()
def version() -> None:
    """Print CLI version."""
    from kroget import __version__

    console.print(__version__)


@app.command()
def tui(
    load: Path | None = typer.Option(
        None,
        "--load",
        help="Load a proposal JSON file before starting the TUI",
    ),
) -> None:
    """Launch the Textual TUI."""
    from kroget.tui import run_tui

    proposal: Proposal | None = None
    startup_message: str | None = None
    if load is not None:
        proposal_path = load.expanduser()
        proposal = Proposal.load(proposal_path)
        startup_message = f"Loaded proposal: {proposal_path} ({len(proposal.items)} items)"

    run_tui(initial_proposal=proposal, startup_message=startup_message)


if __name__ == "__main__":
    app()
