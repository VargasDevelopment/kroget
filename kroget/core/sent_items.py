from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from kroget.core.paths import data_dir


@dataclass
class SentItem:
    name: str
    upc: str
    quantity: int
    modality: str
    status: str
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SentItem":
        return cls(
            name=str(data.get("name", "")),
            upc=str(data.get("upc", "")),
            quantity=int(data.get("quantity", 0)),
            modality=str(data.get("modality", "")),
            status=str(data.get("status", "")),
            error=str(data.get("error")) if data.get("error") else None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "upc": self.upc,
            "quantity": self.quantity,
            "modality": self.modality,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class SentSession:
    session_id: str
    started_at: str
    finished_at: str
    location_id: str | None
    sources: list[str]
    items: list[SentItem]
    kind: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SentSession":
        items = [
            SentItem.from_dict(item)
            for item in data.get("items", [])
            if isinstance(item, dict)
        ]
        return cls(
            session_id=str(data.get("session_id", "")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            location_id=(str(data.get("location_id")) if data.get("location_id") else None),
            sources=[str(source) for source in data.get("sources", [])],
            items=items,
            kind=str(data.get("kind")) if data.get("kind") else None,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "location_id": self.location_id,
            "sources": self.sources,
            "items": [item.to_dict() for item in self.items],
        }
        if self.kind:
            payload["kind"] = self.kind
        return payload


class SentItemsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "sent_items.json")

    def _ensure_empty_file(self) -> None:
        payload = {"sessions": []}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self.path)

    def load(self) -> list[SentSession]:
        if not self.path.exists():
            self._ensure_empty_file()
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            sessions = data
        elif isinstance(data, dict):
            sessions = data.get("sessions", [])
        else:
            return []
        if not isinstance(sessions, list):
            return []
        return [
            SentSession.from_dict(session)
            for session in sessions
            if isinstance(session, dict)
        ]

    def save(self, sessions: list[SentSession]) -> None:
        payload = {"sessions": [session.to_dict() for session in sessions]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(self.path)


MAX_SESSIONS = 20


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_session_id() -> str:
    return str(uuid.uuid4())

def _looks_like_seed_session(session: SentSession) -> bool:
    if session.kind == "seed":
        return True
    if not session.items:
        return True
    if session.kind is not None:
        return False
    if session.location_id is not None:
        return False
    if session.sources:
        return False
    if session.started_at != session.finished_at:
        return False
    if any(item.upc for item in session.items):
        return False
    return True


def load_sent_sessions_with_cleanup(path: Path | None = None) -> tuple[list[SentSession], int]:
    store = SentItemsStore(path)
    sessions = store.load()
    cleaned: list[SentSession] = []
    removed = 0
    for session in sessions:
        if _looks_like_seed_session(session):
            removed += 1
            continue
        cleaned.append(session)
    if removed:
        store.save(cleaned)
    return cleaned, removed


def load_sent_sessions(path: Path | None = None) -> list[SentSession]:
    sessions, _ = load_sent_sessions_with_cleanup(path)
    return sessions


def save_sent_sessions(sessions: list[SentSession], path: Path | None = None) -> None:
    SentItemsStore(path).save(sessions)


def record_sent_session(
    session: SentSession,
    *,
    path: Path | None = None,
    max_sessions: int = MAX_SESSIONS,
) -> list[SentSession]:
    store = SentItemsStore(path)
    sessions = store.load()
    if not session.items:
        return sessions
    sessions.insert(0, session)
    sessions = sessions[:max_sessions]
    store.save(sessions)
    return sessions


def session_from_apply_results(
    results,
    *,
    location_id: str | None,
    sources: list[str],
    kind: str | None = "apply",
    started_at: str | None = None,
    finished_at: str | None = None,
    session_id: str | None = None,
) -> SentSession:
    started_at = started_at or _now_iso()
    finished_at = finished_at or _now_iso()
    session_id = session_id or new_session_id()
    items = [
        SentItem(
            name=result.item.name,
            upc=result.item.upc or "",
            quantity=result.item.quantity,
            modality=result.item.modality,
            status=result.status,
            error=result.error,
        )
        for result in results
    ]
    return SentSession(
        session_id=session_id,
        started_at=started_at,
        finished_at=finished_at,
        location_id=location_id,
        sources=sources,
        items=items,
        kind=kind,
    )
