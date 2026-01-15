from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from kroget.core.product_upc import extract_upcs
from kroget.core.storage import Staple, update_staple
from kroget.kroger import auth
from kroget.kroger.client import KrogerAPIError, KrogerClient
from kroget.core.storage import KrogerConfig


class ProposalAlternative(BaseModel):
    upc: str
    description: str | None = None


class ProposalItem(BaseModel):
    name: str
    quantity: int
    modality: str
    upc: str | None = None
    source: str | None = None
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
    alternatives: list[ProposalAlternative] = Field(default_factory=list)


class Proposal(BaseModel):
    version: str
    created_at: str
    location_id: str | None = None
    items: list[ProposalItem] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Proposal":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            setattr(exc, "path", path)
            raise
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            setattr(exc, "path", path)
            raise

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.model_dump(), indent=2), encoding="utf-8")


def generate_proposal(
    *,
    config: KrogerConfig,
    staples: list[Staple],
    location_id: str,
    list_name: str | None = None,
    auto_pin: bool = False,
    confirm_pin: Callable[[Staple, str], bool] | None = None,
) -> tuple[Proposal, dict[str, bool]]:
    def _extract_product_upcs(
        client: KrogerClient,
        token: str,
        product: object,
        location_id: str,
    ) -> list[str]:
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
                        location_id=location_id,
                    )
                    upcs = extract_upcs(payload)
                except KrogerAPIError:
                    upcs = []
        return upcs

    token = auth.get_client_credentials_token(
        base_url=config.base_url,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=["product.compact"],
    )

    pinned: dict[str, bool] = {}
    items: list[ProposalItem] = []

    with KrogerClient(config.base_url) as client:
        for staple in staples:
            chosen_upc = staple.preferred_upc
            alternatives: list[ProposalAlternative] = []
            source = "preferred" if chosen_upc else "search"
            try:
                results = client.products_search(
                    token.access_token,
                    term=staple.term,
                    location_id=location_id,
                    limit=5,
                )
            except KrogerAPIError as exc:
                if not chosen_upc:
                    items.append(
                        ProposalItem(
                            name=staple.name,
                            quantity=staple.quantity,
                            modality=staple.modality,
                            upc=None,
                            source="search",
                            notes=str(exc),
                            alternatives=[],
                        )
                    )
                    pinned[staple.name] = False
                    continue
                results = None

            if results:
                for product in results.data[:3]:
                    upcs = _extract_product_upcs(
                        client,
                        token.access_token,
                        product,
                        location_id,
                    )
                    if upcs:
                        alternatives.append(
                            ProposalAlternative(
                                upc=upcs[0],
                                description=product.description,
                            )
                        )

                if not chosen_upc and results.data:
                    first = results.data[0]
                    first_upcs = _extract_product_upcs(
                        client,
                        token.access_token,
                        first,
                        location_id,
                    )
                    if first_upcs:
                        chosen_upc = first_upcs[0]

            if chosen_upc and not staple.preferred_upc:
                should_pin = auto_pin or (confirm_pin(staple, chosen_upc) if confirm_pin else False)
                if should_pin:
                    try:
                        update_staple(
                            staple.name,
                            preferred_upc=chosen_upc,
                            list_name=list_name,
                        )
                        pinned[staple.name] = True
                        source = "preferred"
                    except ValueError:
                        pinned[staple.name] = False
                else:
                    pinned[staple.name] = False
            else:
                pinned[staple.name] = bool(staple.preferred_upc)

            items.append(
                ProposalItem(
                    name=staple.name,
                    quantity=staple.quantity,
                    modality=staple.modality,
                    upc=chosen_upc,
                    source=source,
                    alternatives=alternatives,
                )
            )

    proposal = Proposal(
        version="1",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        location_id=location_id,
        items=items,
    )
    return proposal, pinned


def apply_proposal_items(
    *,
    config: KrogerConfig,
    token: str,
    items: list[ProposalItem],
    stop_on_error: bool = False,
) -> tuple[int, int, list[str], list["ApplyItemResult"]]:
    success = 0
    failed = 0
    errors: list[str] = []
    results: list[ApplyItemResult] = []

    with KrogerClient(config.base_url) as client:
        for item in items:
            if not item.upc:
                failed += 1
                message = f"Missing UPC for {item.name}"
                errors.append(message)
                results.append(
                    ApplyItemResult(item=item, status="failed", error=message)
                )
                if stop_on_error:
                    break
                continue
            try:
                client.add_to_cart(
                    token,
                    product_id=item.upc,
                    quantity=item.quantity,
                    modality=item.modality,
                )
                success += 1
                results.append(ApplyItemResult(item=item, status="success", error=None))
            except KrogerAPIError as exc:
                failed += 1
                message = f"Failed to add {item.name}: {exc}"
                errors.append(message)
                results.append(
                    ApplyItemResult(item=item, status="failed", error=message)
                )
                if stop_on_error:
                    break

    return success, failed, errors, results


@dataclass
class ApplyItemResult:
    item: ProposalItem
    status: str
    error: str | None = None
