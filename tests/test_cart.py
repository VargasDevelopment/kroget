from kroget.kroger.client import KrogerClient


def test_cart_add_payload_includes_modality():
    client = KrogerClient("https://api.kroger.com")
    captured = {}

    def fake_request(method, path, headers=None, params=None, json=None, data=None):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json

        class _Response:
            status_code = 204
            content = b""
            text = ""

            def json(self):
                return {}

        return _Response()

    client._client.request = fake_request  # type: ignore[assignment]

    client.add_to_cart("token", product_id="000111", quantity=2, modality="PICKUP")

    assert captured["method"] == "PUT"
    assert captured["path"] == "/v1/cart/add"
    assert captured["json"] == {
        "items": [{"upc": "000111", "quantity": 2, "modality": "PICKUP"}]
    }
