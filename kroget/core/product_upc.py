from __future__ import annotations

from collections.abc import Iterable


def _iter_upc_values(payload: object) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "upc" and isinstance(value, str):
                yield value
            if isinstance(value, (dict, list)):
                yield from _iter_upc_values(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_upc_values(item)


def extract_upcs(product_response: dict) -> list[str]:
    upcs: list[str] = []
    seen: set[str] = set()

    data = product_response.get("data")
    if isinstance(data, list):
        items_to_scan = data
    elif isinstance(data, dict):
        items_to_scan = [data]
    else:
        items_to_scan = []

    for product in items_to_scan:
        if not isinstance(product, dict):
            continue
        items = product.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    value = item.get("upc")
                    if isinstance(value, str) and value not in seen:
                        upcs.append(value)
                        seen.add(value)

    for value in _iter_upc_values(product_response):
        if value not in seen:
            upcs.append(value)
            seen.add(value)

    return upcs


def pick_upc(upcs: list[str]) -> str:
    if not upcs:
        raise ValueError("No UPCs available")
    return upcs[0]
