from __future__ import annotations

from kroget.kroger.models import Product


def _format_price_value(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return f"${value:.2f}"
    if isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return None
        return f"${numeric:.2f}"
    return None


def format_price(price: dict | None) -> str:
    if not price:
        return ""
    promo = _format_price_value(price.get("promo"))
    regular = _format_price_value(price.get("regular"))
    if promo:
        return f"{promo} promo"
    if regular:
        return regular
    return ""


def product_display_fields(product: Product) -> dict[str, str]:
    description = product.description or ""
    upc = ""
    size = ""
    price = ""

    if product.items:
        for item in product.items:
            if not isinstance(item, dict):
                continue
            if not upc and isinstance(item.get("upc"), str):
                upc = item["upc"]
            if not size and isinstance(item.get("size"), str):
                size = item["size"]
            if not price and isinstance(item.get("price"), dict):
                price = format_price(item.get("price"))
            if upc and size and price:
                break

    return {
        "description": description,
        "upc": upc,
        "size": size,
        "price": price,
    }
