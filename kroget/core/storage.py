from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from kroget.kroger.models import StoredToken
from kroget.core.paths import data_dir


class ConfigError(RuntimeError):
    pass


def _load_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        setattr(exc, "path", path)
        raise


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


def _clean_optional_str(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    return None


def load_kroger_config(store: "ConfigStore | None" = None) -> KrogerConfig:
    load_dotenv()
    store = store or ConfigStore()
    config = store.load()
    client_id = os.getenv("KROGER_CLIENT_ID") or config.kroger_client_id
    client_secret = os.getenv("KROGER_CLIENT_SECRET") or config.kroger_client_secret
    redirect_uri = os.getenv("KROGER_REDIRECT_URI") or config.kroger_redirect_uri
    base_url = os.getenv("KROGER_BASE_URL", "https://api.kroger.com").rstrip("/")

    missing = [name for name, value in (
        ("kroger_client_id", client_id),
        ("kroger_client_secret", client_secret),
    ) if not value]
    if missing:
        raise ConfigError(
            "Missing required config values: "
            f"{', '.join(missing)}. "
            "Set environment variables or run `kroget setup`."
        )

    return KrogerConfig(
        client_id=client_id or "",
        client_secret=client_secret or "",
        redirect_uri=redirect_uri,
        base_url=base_url,
    )

class TokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "tokens.json")

    def load(self) -> StoredToken | None:
        if not self.path.exists():
            return None
        data = _load_json_file(self.path)
        return StoredToken.model_validate(data)

    def save(self, token: StoredToken) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(token.model_dump(), indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)


@dataclass
class UserConfig:
    kroger_client_id: str | None = None
    kroger_client_secret: str | None = None
    kroger_redirect_uri: str | None = None
    default_location_id: str | None = None
    default_modality: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "UserConfig":
        return cls(
            kroger_client_id=_clean_optional_str(data.get("kroger_client_id")),
            kroger_client_secret=_clean_optional_str(data.get("kroger_client_secret")),
            kroger_redirect_uri=_clean_optional_str(data.get("kroger_redirect_uri")),
            default_location_id=_clean_optional_str(data.get("default_location_id")),
            default_modality=_clean_optional_str(data.get("default_modality")),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.kroger_client_id:
            payload["kroger_client_id"] = self.kroger_client_id
        if self.kroger_client_secret:
            payload["kroger_client_secret"] = self.kroger_client_secret
        if self.kroger_redirect_uri:
            payload["kroger_redirect_uri"] = self.kroger_redirect_uri
        if self.default_location_id:
            payload["default_location_id"] = self.default_location_id
        if self.default_modality:
            payload["default_modality"] = self.default_modality
        return payload


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "config.json")

    def load(self) -> UserConfig:
        if not self.path.exists():
            return UserConfig()
        data = _load_json_file(self.path)
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
        self.path = path or (data_dir() / "staples.json")

    def load(self) -> list[Staple]:
        if not self.path.exists():
            return []
        data = _load_json_file(self.path)
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


def _default_lists_path() -> Path:
    return data_dir() / "lists.json"


def _default_staples_path() -> Path:
    return data_dir() / "staples.json"


def _validate_list_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("List name must not be empty")
    if len(cleaned) > 60:
        raise ValueError("List name is too long")
    return cleaned


def _ensure_lists_data(lists_path: Path, staples_path: Path) -> None:
    if lists_path.exists():
        return
    if staples_path.exists():
        staples = StaplesStore(staples_path).load()
        payload = {"active": "Staples", "lists": {"Staples": [s.to_dict() for s in staples]}}
        lists_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = lists_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, lists_path)
        return
    payload = {"active": "Staples", "lists": {"Staples": []}}
    lists_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = lists_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, lists_path)


def _load_lists_data(
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> tuple[str, dict[str, list[Staple]]]:
    lists_path = lists_path or _default_lists_path()
    staples_path = staples_path or _default_staples_path()
    _ensure_lists_data(lists_path, staples_path)
    data = _load_json_file(lists_path)
    if not isinstance(data, dict):
        raise ValueError("Invalid lists.json format")
    active = str(data.get("active", "Staples"))
    raw_lists = data.get("lists", {})
    if not isinstance(raw_lists, dict):
        raw_lists = {}
    lists: dict[str, list[Staple]] = {}
    for name, entries in raw_lists.items():
        if isinstance(entries, list):
            lists[str(name)] = [
                Staple.from_dict(entry) for entry in entries if isinstance(entry, dict)
            ]
    if not lists:
        lists["Staples"] = []
        active = "Staples"
    if active not in lists:
        active = next(iter(lists.keys()))
    return active, lists


def _save_lists_data(
    active: str,
    lists: dict[str, list[Staple]],
    lists_path: Path | None = None,
) -> None:
    lists_path = lists_path or _default_lists_path()
    payload = {
        "active": active,
        "lists": {name: [staple.to_dict() for staple in staples] for name, staples in lists.items()},
    }
    lists_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = lists_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, lists_path)


def _find_staple_index(staples: list[Staple], identifier: str) -> int | None:
    for index, staple in enumerate(staples):
        if staple.preferred_upc and staple.preferred_upc == identifier:
            return index
    lowered = identifier.lower()
    for index, staple in enumerate(staples):
        if staple.name.lower() == lowered:
            return index
    return None


def list_names(
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> list[str]:
    _, lists = _load_lists_data(lists_path, staples_path)
    return list(lists.keys())


def get_active_list(
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> str:
    active, _ = _load_lists_data(lists_path, staples_path)
    return active


def set_active_list(
    name: str,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = _validate_list_name(name)
    if name not in lists:
        raise ValueError(f"List '{name}' not found")
    _save_lists_data(name, lists, lists_path)


def create_list(
    name: str,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = _validate_list_name(name)
    if name in lists:
        raise ValueError(f"List '{name}' already exists")
    lists[name] = []
    _save_lists_data(active, lists, lists_path)


def rename_list(
    old_name: str,
    new_name: str,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    old_name = _validate_list_name(old_name)
    new_name = _validate_list_name(new_name)
    if old_name not in lists:
        raise ValueError(f"List '{old_name}' not found")
    if new_name in lists:
        raise ValueError(f"List '{new_name}' already exists")
    lists[new_name] = lists.pop(old_name)
    if active == old_name:
        active = new_name
    _save_lists_data(active, lists, lists_path)


def delete_list(
    name: str,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = _validate_list_name(name)
    if name not in lists:
        raise ValueError(f"List '{name}' not found")
    if len(lists) <= 1:
        raise ValueError("Cannot delete the last remaining list")
    lists.pop(name)
    if active == name:
        active = next(iter(lists.keys()))
    _save_lists_data(active, lists, lists_path)


def get_staples(
    list_name: str | None = None,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> list[Staple]:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = list_name or active
    if name not in lists:
        raise ValueError(f"List '{name}' not found")
    return list(lists[name])


def load_staples(path: Path | None = None) -> list[Staple]:
    return get_staples(lists_path=path)


def save_staples(
    staples: list[Staple],
    *,
    list_name: str | None = None,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = list_name or active
    lists[name] = staples
    _save_lists_data(active, lists, lists_path)


def add_staple(
    staple: Staple,
    *,
    list_name: str | None = None,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    name = list_name or active
    if name not in lists:
        raise ValueError(f"List '{name}' not found")
    if any(existing.name == staple.name for existing in lists[name]):
        raise ValueError(f"Staple '{staple.name}' already exists")
    lists[name].append(staple)
    _save_lists_data(active, lists, lists_path)


def remove_staple(
    identifier: str,
    *,
    list_name: str | None = None,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    list_name = list_name or active
    if list_name not in lists:
        raise ValueError(f"List '{list_name}' not found")
    staples = lists[list_name]
    match_index = _find_staple_index(staples, identifier)
    if match_index is None:
        raise ValueError(f"Staple '{identifier}' not found")
    staples.pop(match_index)
    lists[list_name] = staples
    _save_lists_data(active, lists, lists_path)


def move_item(
    source_list: str,
    target_list: str,
    item_identifier: str,
    *,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    if source_list not in lists:
        raise ValueError(f"List '{source_list}' not found")
    if target_list not in lists:
        raise ValueError(f"List '{target_list}' not found")
    if source_list == target_list:
        raise ValueError("Source and target lists must be different")

    source_staples = list(lists[source_list])
    target_staples = list(lists[target_list])

    match_index = _find_staple_index(source_staples, item_identifier)
    if match_index is None:
        raise ValueError(f"Staple '{item_identifier}' not found")
    staple = source_staples.pop(match_index)

    if staple.preferred_upc:
        target_index = None
        for index, existing in enumerate(target_staples):
            if existing.preferred_upc == staple.preferred_upc:
                target_index = index
                break
        if target_index is not None:
            target_staples[target_index].quantity += staple.quantity
        else:
            target_staples.append(staple)
    else:
        target_staples.append(staple)

    lists[source_list] = source_staples
    lists[target_list] = target_staples
    _save_lists_data(active, lists, lists_path)


def update_staple(
    name: str,
    *,
    term: str | None = None,
    quantity: int | None = None,
    preferred_upc: str | None = None,
    modality: str | None = None,
    list_name: str | None = None,
    lists_path: Path | None = None,
    staples_path: Path | None = None,
) -> None:
    active, lists = _load_lists_data(lists_path, staples_path)
    list_name = list_name or active
    if list_name not in lists:
        raise ValueError(f"List '{list_name}' not found")
    staples = lists[list_name]
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
    lists[list_name] = staples
    _save_lists_data(active, lists, lists_path)
