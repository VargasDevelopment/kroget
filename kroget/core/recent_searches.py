from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from kroget.core.paths import data_dir


@dataclass
class RecentSearchEntry:
    term: str
    upc: str
    description: str
    timestamp: str

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RecentSearchEntry":
        return cls(
            term=str(data.get("term", "")),
            upc=str(data.get("upc", "")),
            description=str(data.get("description", "")),
            timestamp=str(data.get("timestamp", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "term": self.term,
            "upc": self.upc,
            "description": self.description,
            "timestamp": self.timestamp,
        }


class RecentSearchStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "recent_searches.json")

    def load(self) -> list[RecentSearchEntry]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        entries = data.get("recent", [])
        if not isinstance(entries, list):
            return []
        return [
            RecentSearchEntry.from_dict(entry)
            for entry in entries
            if isinstance(entry, dict)
        ]

    def save(self, entries: list[RecentSearchEntry]) -> None:
        payload = {"recent": [entry.to_dict() for entry in entries]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self.path)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_recent_searches(path: Path | None = None) -> list[RecentSearchEntry]:
    return RecentSearchStore(path).load()


def save_recent_searches(entries: list[RecentSearchEntry], path: Path | None = None) -> None:
    RecentSearchStore(path).save(entries)


def record_recent_search(
    *,
    term: str,
    upc: str,
    description: str,
    max_entries: int = 50,
    path: Path | None = None,
    timestamp: str | None = None,
) -> list[RecentSearchEntry]:
    store = RecentSearchStore(path)
    entries = store.load()
    term_key = term.strip().lower()
    filtered = [entry for entry in entries if entry.term.strip().lower() != term_key]
    entry = RecentSearchEntry(
        term=term.strip(),
        upc=upc.strip(),
        description=description.strip(),
        timestamp=timestamp or _now_iso(),
    )
    filtered.insert(0, entry)
    trimmed = filtered[:max_entries]
    store.save(trimmed)
    return trimmed
