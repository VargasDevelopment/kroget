from __future__ import annotations

from typing import Any

import time
from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str | None = None
    expires_in: int
    refresh_token: str | None = None
    scope: str | None = None


class StoredToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str | None = None
    expires_at: int
    obtained_at: int
    scopes: list[str] = Field(default_factory=list)

    @classmethod
    def from_token_response(cls, token: TokenResponse, scopes: list[str]) -> "StoredToken":
        obtained_at = int(time.time())
        expires_at = obtained_at + int(token.expires_in)
        return cls(
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            token_type=token.token_type,
            expires_at=expires_at,
            obtained_at=obtained_at,
            scopes=scopes,
        )


class Product(BaseModel):
    productId: str
    description: str | None = None
    brand: str | None = None
    items: list[dict[str, Any]] | None = None


class ProductsResponse(BaseModel):
    data: list[Product] = Field(default_factory=list)
