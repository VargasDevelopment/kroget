from __future__ import annotations

from typing import Any

import httpx

from kroget.kroger.models import ProductsResponse


class KrogerAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class KrogerClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KrogerClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                path,
                headers=headers,
                params=params,
                json=json,
                data=data,
            )
        except httpx.RequestError as exc:
            raise KrogerAPIError(f"Network error contacting Kroger API: {exc}") from exc

        if response.status_code >= 400:
            message = response.text
            try:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error"):
                    message = payload.get("error")
            except ValueError:
                pass
            raise KrogerAPIError(
                f"Kroger API error {response.status_code}: {message}",
                status_code=response.status_code,
                response_text=response.text,
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise KrogerAPIError(
                "Kroger API returned invalid JSON",
                response_text=response.text,
            ) from exc

    def products_search(
        self,
        token: str,
        term: str,
        location_id: str,
        limit: int = 10,
        start: int | None = None,
    ) -> ProductsResponse:
        params: dict[str, Any] = {
            "filter.term": term,
            "filter.locationId": location_id,
            "filter.limit": limit,
        }
        if start is not None:
            params["filter.start"] = start

        payload = self._request(
            "GET",
            "/v1/products",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            params=params,
        )
        return ProductsResponse.model_validate(payload)

    def get_product(self, token: str, product_id: str, location_id: str) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/v1/products/{product_id}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            params={"filter.locationId": location_id},
        )
        return payload

    def locations_search(
        self,
        token: str,
        *,
        zip_code_near: str | None = None,
        lat_long_near: str | None = None,
        lat_near: float | None = None,
        lon_near: float | None = None,
        radius_in_miles: int | None = None,
        limit: int | None = None,
        chain: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if zip_code_near:
            params["filter.zipCode.near"] = zip_code_near
        if lat_long_near:
            params["filter.latLong.near"] = lat_long_near
        if lat_near is not None:
            params["filter.lat.near"] = lat_near
        if lon_near is not None:
            params["filter.lon.near"] = lon_near
        if radius_in_miles is not None:
            params["filter.radiusInMiles"] = radius_in_miles
        if limit is not None:
            params["filter.limit"] = limit
        if chain:
            params["filter.chain"] = chain

        return self._request(
            "GET",
            "/v1/locations",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            params=params,
        )

    def get_location(self, token: str, location_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/locations/{location_id}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )

    def profile(self, token: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/identity/profile",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )

    def add_to_cart(
        self,
        token: str,
        product_id: str,
        quantity: int,
        modality: str,
        return_status: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "items": [
                {
                    "upc": product_id,
                    "quantity": quantity,
                    "modality": modality,
                }
            ],
        }
        try:
            response = self._client.request(
                "PUT",
                "/v1/cart/add",
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                json=payload,
            )
        except httpx.RequestError as exc:
            raise KrogerAPIError(f"Network error contacting Kroger API: {exc}") from exc

        if response.status_code >= 400:
            message = response.text
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict) and error_payload.get("error"):
                    message = error_payload.get("error")
            except ValueError:
                pass
            raise KrogerAPIError(
                f"Kroger API error {response.status_code}: {message}",
                status_code=response.status_code,
                response_text=response.text,
            )

        if not response.content:
            result: dict[str, Any] = {}
        else:
            try:
                result = response.json()
            except ValueError as exc:
                raise KrogerAPIError(
                    "Kroger API returned invalid JSON",
                    response_text=response.text,
                ) from exc

        if return_status:
            result["_status_code"] = response.status_code
        return result
