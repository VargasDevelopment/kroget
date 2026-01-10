import httpx

from kroget.core.product_upc import extract_upcs
from kroget.kroger.client import KrogerClient


def test_extract_upcs_items_single():
    payload = {
        "data": [
            {
                "items": [
                    {"upc": "000111"},
                ]
            }
        ]
    }
    assert extract_upcs(payload) == ["000111"]


def test_extract_upcs_multiple_items_unique():
    payload = {
        "data": [
            {
                "items": [
                    {"upc": "000111"},
                    {"upc": "000222"},
                    {"upc": "000111"},
                ]
            }
        ]
    }
    assert extract_upcs(payload) == ["000111", "000222"]


def test_extract_upcs_recursive_fallback():
    payload = {
        "meta": {"nested": {"upc": "999888"}},
        "data": [],
    }
    assert extract_upcs(payload) == ["999888"]


def test_extract_upcs_none():
    payload = {"data": [{"items": [{"foo": "bar"}]}]}
    assert extract_upcs(payload) == []


def test_get_product_parsing_with_mocked_httpx():
    client = KrogerClient("https://api.kroger.com")
    request = httpx.Request("GET", "https://api.kroger.com/v1/products/123")
    response_payload = {"data": {"items": [{"upc": "000111"}]}}

    def fake_request(method, path, headers=None, params=None, json=None, data=None):
        return httpx.Response(200, json=response_payload, request=request)

    client._client.request = fake_request  # type: ignore[assignment]

    result = client.get_product("token", product_id="123", location_id="01400441")
    assert result == response_payload
