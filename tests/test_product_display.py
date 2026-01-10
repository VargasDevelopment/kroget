from kroget.core.product_display import format_price, product_display_fields
from kroget.kroger.models import Product


def test_format_price_prefers_promo():
    assert format_price({"regular": 2.49, "promo": 1.99}) == "$1.99 promo"


def test_format_price_regular():
    assert format_price({"regular": "2.49"}) == "$2.49"


def test_product_display_fields():
    product = Product(
        productId="123",
        description="Milk",
        items=[
            {
                "upc": "000111",
                "size": "1 gal",
                "price": {"regular": 3.49},
            }
        ],
    )
    fields = product_display_fields(product)
    assert fields["description"] == "Milk"
    assert fields["upc"] == "000111"
    assert fields["size"] == "1 gal"
    assert fields["price"] == "$3.49"
