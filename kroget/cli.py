from __future__ import annotations

import importlib.metadata
import json
import os
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from kroget.core.product_upc import extract_upcs, pick_upc
from kroget.core.proposal import Proposal, ProposalItem, apply_proposal_items, generate_proposal
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

app = typer.Typer(help="Kroger shopping CLI")
products_app = typer.Typer(help="Product search commands")
auth_app = typer.Typer(help="Authentication commands")
cart_app = typer.Typer(help="Cart commands")
locations_app = typer.Typer(help="Location commands")
openapi_app = typer.Typer(help="OpenAPI utilities")
staples_app = typer.Typer(help="Staples commands")
proposal_app = typer.Typer(help="Proposal commands")
lists_app = typer.Typer(help="List management commands")
sent_app = typer.Typer(help="Sent items history commands")

app.add_typer(products_app, name="products")
app.add_typer(auth_app, name="auth")
app.add_typer(cart_app, name="cart")
app.add_typer(locations_app, name="locations")
app.add_typer(openapi_app, name="openapi")
app.add_typer(staples_app, name="staples")
app.add_typer(proposal_app, name="proposal")
app.add_typer(lists_app, name="lists")
app.add_typer(sent_app, name="sent")

console = Console()

DEFAULT_REDIRECT_URI = "http://localhost:8400/callback"
KROGER_PORTAL_URL = "https://developer.kroger.com/"


def _print_version(value: bool) -> None:
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


def _format_staples_table(staples: list[Staple]) -> Table:
    table = Table(title="Staples")
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
    console.print("[green]Saved config:[/green] ~/.kroget/config.json")

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
    """Get product details by ID."""
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


@staples_app.command("add")
def staples_add(
    name: str = typer.Argument(..., help="Staple name"),
    term: str = typer.Option(..., "--term", help="Search term"),
    quantity: int = typer.Option(1, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str = typer.Option("PICKUP", "--modality", help="PICKUP or DELIVERY"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """Add a staple item."""
    modality = modality.upper()
    if modality not in {"PICKUP", "DELIVERY"}:
        console.print("[red]Invalid modality.[/red] Use PICKUP or DELIVERY.")
        raise typer.Exit(code=1)
    staple = Staple(
        name=name,
        term=term,
        quantity=quantity,
        preferred_upc=upc,
        modality=modality,
    )
    try:
        add_staple(staple, list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Added staple:[/green] {name}")


@staples_app.command("list")
def staples_list(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """List staples."""
    try:
        staples = get_staples(list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if as_json:
        payload = {"staples": [staple.to_dict() for staple in staples]}
        console.print_json(json.dumps(payload))
        return
    table = _format_staples_table(staples)
    console.print(table)


@staples_app.command("remove")
def staples_remove(
    identifier: str = typer.Argument(..., help="Staple name or preferred UPC"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """Remove a staple."""
    try:
        remove_staple(identifier, list_name=list_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Removed staple:[/green] {identifier}")


@staples_app.command("move")
def staples_move(
    identifier: str = typer.Argument(..., help="Staple name or preferred UPC"),
    to_list: str = typer.Option(..., "--to", help="Target list name"),
    from_list: str | None = typer.Option(None, "--from", help="Source list override"),
) -> None:
    """Move a staple to another list."""
    source_list = from_list or get_active_list()
    try:
        move_item(source_list, to_list, identifier)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Moved staple to:[/green] {to_list}")


@staples_app.command("set")
def staples_set(
    name: str = typer.Argument(..., help="Staple name"),
    term: str | None = typer.Option(None, "--term", help="Search term"),
    quantity: int | None = typer.Option(None, "--qty", min=1, help="Quantity"),
    upc: str | None = typer.Option(None, "--upc", help="Preferred UPC"),
    modality: str | None = typer.Option(None, "--modality", help="PICKUP or DELIVERY"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """Update a staple."""
    if modality is not None:
        modality = modality.upper()
        if modality not in {"PICKUP", "DELIVERY"}:
            console.print("[red]Invalid modality.[/red] Use PICKUP or DELIVERY.")
            raise typer.Exit(code=1)
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
    console.print(f"[green]Updated staple:[/green] {name}")


@staples_app.command("propose")
def staples_propose(
    location_id: str | None = typer.Option(None, "--location-id", help="Location ID"),
    out: Path = typer.Option(Path("proposal.json"), "--out", help="Output proposal path"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
    auto_pin: bool = typer.Option(False, "--auto-pin", help="Auto-pin UPCs"),
    list_name: str | None = typer.Option(None, "--list", help="List name override"),
) -> None:
    """Generate a proposal from staples."""
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
        console.print("[yellow]No staples configured.[/yellow]")
        raise typer.Exit(code=1)

    def confirm_pin(staple: Staple, upc: str) -> bool:
        return typer.confirm(f"Pin UPC {upc} for staple '{staple.name}'?", default=False)

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
    """Search Kroger locations."""
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


@openapi_app.command("check")
def openapi_check(
    spec_dir: Path = typer.Option(Path("openapi"), "--dir", help="Directory of specs"),
) -> None:
    """Check required OpenAPI operations exist."""
    required = {
        "kroger-location-openapi.json": {
            ("/v1/locations", "get"),
            ("/v1/locations/{locationId}", "get"),
        },
        "kroger-products-openapi.json": {
            ("/v1/products", "get"),
            ("/v1/products/{id}", "get"),
        },
        "kroger-cart-openapi.json": {
            ("/v1/cart/add", "put"),
        },
        "kroger-identity-openapi.json": {
            ("/v1/identity/profile", "get"),
        },
    }

    all_ok = True
    for filename, expected in required.items():
        path = spec_dir / filename
        if not path.exists():
            console.print(f"[red]FAIL[/red] {filename} missing")
            all_ok = False
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            console.print(f"[red]FAIL[/red] {filename} invalid JSON: {exc}")
            all_ok = False
            continue

        paths = payload.get("paths", {})
        missing = []
        for route, method in sorted(expected):
            methods = paths.get(route, {}) if isinstance(paths, dict) else {}
            if not isinstance(methods, dict) or method not in methods:
                missing.append(f"{method.upper()} {route}")

        if missing:
            console.print(f"[red]FAIL[/red] {filename} missing: {', '.join(missing)}")
            all_ok = False
        else:
            console.print(f"[green]OK[/green] {filename}")

    if not all_ok:
        raise typer.Exit(code=1)


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
def tui() -> None:
    """Launch the Textual TUI."""
    from kroget.tui import run_tui

    run_tui()


if __name__ == "__main__":
    app()
