from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from kroget.kroger.models import StoredToken


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class KrogerConfig:
    client_id: str
    client_secret: str
    redirect_uri: str | None
    base_url: str

    @classmethod
    def from_env(cls) -> "KrogerConfig":
        load_dotenv()
        client_id = os.getenv("KROGER_CLIENT_ID")
        client_secret = os.getenv("KROGER_CLIENT_SECRET")
        redirect_uri = os.getenv("KROGER_REDIRECT_URI")
        base_url = os.getenv("KROGER_BASE_URL", "https://api.kroger.com").rstrip("/")

        missing = [name for name, value in (
            ("KROGER_CLIENT_ID", client_id),
            ("KROGER_CLIENT_SECRET", client_secret),
        ) if not value]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            client_id=client_id or "",
            client_secret=client_secret or "",
            redirect_uri=redirect_uri,
            base_url=base_url,
        )


class TokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".kroget" / "tokens.json")

    def load(self) -> StoredToken | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return StoredToken.model_validate(data)

    def save(self, token: StoredToken) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(token.model_dump(), indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)


@dataclass
class UserConfig:
    default_location_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "UserConfig":
        return cls(default_location_id=data.get("default_location_id"))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {"default_location_id": self.default_location_id}


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".kroget" / "config.json")

    def load(self) -> UserConfig:
        if not self.path.exists():
            return UserConfig()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return UserConfig()
        return UserConfig.from_dict(data)

    def save(self, config: UserConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)


@dataclass
class Staple:
    name: str
    term: str
    quantity: int
    preferred_upc: str | None = None
    modality: str = "PICKUP"

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Staple":
        return cls(
            name=str(data.get("name", "")),
            term=str(data.get("term", "")),
            quantity=int(data.get("quantity", 1)),
            preferred_upc=data.get("preferred_upc") if data.get("preferred_upc") else None,
            modality=str(data.get("modality", "PICKUP")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "term": self.term,
            "quantity": self.quantity,
            "preferred_upc": self.preferred_upc,
            "modality": self.modality,
        }


class StaplesStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".kroget" / "staples.json")

    def load(self) -> list[Staple]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        staples = data.get("staples", [])
        if not isinstance(staples, list):
            return []
        return [Staple.from_dict(item) for item in staples if isinstance(item, dict)]

    def save(self, staples: list[Staple]) -> None:
        payload = {"staples": [staple.to_dict() for staple in staples]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)


def load_staples(path: Path | None = None) -> list[Staple]:
    return StaplesStore(path).load()


def save_staples(staples: list[Staple], path: Path | None = None) -> None:
    StaplesStore(path).save(staples)


def add_staple(staple: Staple, path: Path | None = None) -> None:
    store = StaplesStore(path)
    staples = store.load()
    if any(existing.name == staple.name for existing in staples):
        raise ValueError(f"Staple '{staple.name}' already exists")
    staples.append(staple)
    store.save(staples)


def remove_staple(name: str, path: Path | None = None) -> None:
    store = StaplesStore(path)
    staples = store.load()
    filtered = [staple for staple in staples if staple.name != name]
    if len(filtered) == len(staples):
        raise ValueError(f"Staple '{name}' not found")
    store.save(filtered)


def update_staple(
    name: str,
    *,
    term: str | None = None,
    quantity: int | None = None,
    preferred_upc: str | None = None,
    modality: str | None = None,
    path: Path | None = None,
) -> None:
    store = StaplesStore(path)
    staples = store.load()
    updated = False
    for staple in staples:
        if staple.name == name:
            if term is not None:
                staple.term = term
            if quantity is not None:
                staple.quantity = quantity
            if preferred_upc is not None:
                staple.preferred_upc = preferred_upc
            if modality is not None:
                staple.modality = modality
            updated = True
            break
    if not updated:
        raise ValueError(f"Staple '{name}' not found")
    store.save(staples)
