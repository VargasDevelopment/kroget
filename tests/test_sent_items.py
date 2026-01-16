import json
from pathlib import Path

from kroget.core.paths import data_dir
from kroget.core.proposal import ApplyItemResult, ProposalItem
from kroget.core.sent_items import (
    SentItem,
    SentSession,
    load_sent_sessions,
    load_sent_sessions_with_cleanup,
    record_sent_session,
    save_sent_sessions,
    session_from_apply_results,
)


def test_sent_items_roundtrip(tmp_path):
    path = tmp_path / "sent_items.json"
    session = SentSession(
        session_id="abc",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:01:00Z",
        location_id="01400441",
        sources=["Staples"],
        items=[
            SentItem(
                name="Milk",
                upc="000111",
                quantity=1,
                modality="PICKUP",
                status="success",
            )
        ],
        kind="apply",
    )
    record_sent_session(session, path=path, max_sessions=20)
    sessions = load_sent_sessions(path=path)
    assert sessions[0].session_id == "abc"
    assert sessions[0].items[0].status == "success"
    assert sessions[0].kind == "apply"


def test_sent_items_prune(tmp_path):
    path = tmp_path / "sent_items.json"
    for i in range(25):
        session = SentSession(
            session_id=str(i),
            started_at="2024-01-01T00:00:00Z",
            finished_at="2024-01-01T00:01:00Z",
            location_id=None,
            sources=[],
            items=[
                SentItem(
                    name="Item",
                    upc="000111",
                    quantity=1,
                    modality="PICKUP",
                    status="success",
                )
            ],
        )
        record_sent_session(session, path=path, max_sessions=20)
    sessions = load_sent_sessions(path=path)
    assert len(sessions) == 20
    assert sessions[0].session_id == "24"


def test_sent_items_missing_file_returns_empty(tmp_path):
    path = tmp_path / "sent_items.json"
    sessions = load_sent_sessions(path=path)
    assert sessions == []
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload == {"sessions": []}


def test_sent_items_cleanup_removes_seed(tmp_path):
    path = tmp_path / "sent_items.json"
    seed_session = SentSession(
        session_id="seed",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:00:00Z",
        location_id=None,
        sources=[],
        items=[
            SentItem(
                name="Milk",
                upc="",
                quantity=1,
                modality="PICKUP",
                status="",
            )
        ],
        kind="seed",
    )
    real_session = SentSession(
        session_id="real",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:01:00Z",
        location_id="01400441",
        sources=["Staples"],
        items=[
            SentItem(
                name="Eggs",
                upc="000222",
                quantity=1,
                modality="PICKUP",
                status="success",
            )
        ],
    )
    save_sent_sessions([seed_session, real_session], path=path)
    sessions, removed = load_sent_sessions_with_cleanup(path=path)
    assert removed == 1
    assert len(sessions) == 1
    assert sessions[0].session_id == "real"


def test_sent_items_preserve_legacy_sessions(tmp_path):
    path = tmp_path / "sent_items.json"
    legacy_session = SentSession(
        session_id="legacy",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:01:00Z",
        location_id="01400441",
        sources=["Staples"],
        items=[
            SentItem(
                name="Milk",
                upc="000111",
                quantity=1,
                modality="PICKUP",
                status="success",
            )
        ],
    )
    save_sent_sessions([legacy_session], path=path)
    sessions, removed = load_sent_sessions_with_cleanup(path=path)
    assert removed == 0
    assert len(sessions) == 1
    assert sessions[0].session_id == "legacy"


def test_session_from_apply_results():
    item = ProposalItem(name="Milk", quantity=1, modality="PICKUP", upc="000111")
    results = [ApplyItemResult(item=item, status="success", error=None)]
    session = session_from_apply_results(
        results,
        location_id="01400441",
        sources=["Staples"],
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:01:00Z",
        session_id="session-1",
    )
    assert session.session_id == "session-1"
    assert session.items[0].status == "success"
    assert session.kind == "apply"


def test_sent_items_respects_data_dir_override(tmp_path, monkeypatch):
    data_root = tmp_path / "kroget-data"
    fake_home = tmp_path / "home"
    monkeypatch.setenv("KROGET_DATA_DIR", str(data_root))
    monkeypatch.setenv("HOME", str(fake_home))

    session = SentSession(
        session_id="override",
        started_at="2024-01-01T00:00:00Z",
        finished_at="2024-01-01T00:01:00Z",
        location_id="01400441",
        sources=["Staples"],
        items=[
            SentItem(
                name="Milk",
                upc="000111",
                quantity=1,
                modality="PICKUP",
                status="success",
            )
        ],
        kind="apply",
    )
    record_sent_session(session)

    expected_path = data_dir() / "sent_items.json"
    assert expected_path == data_root / "sent_items.json"
    assert expected_path.exists()
    payload = json.loads(expected_path.read_text())
    assert payload["sessions"][0]["session_id"] == "override"

    default_path = Path(fake_home) / ".kroget" / "sent_items.json"
    assert not default_path.exists()
