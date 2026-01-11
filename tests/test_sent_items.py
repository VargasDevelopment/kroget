from kroget.core.proposal import ApplyItemResult, ProposalItem
from kroget.core.sent_items import (
    SentItem,
    SentSession,
    load_sent_sessions,
    record_sent_session,
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
    )
    record_sent_session(session, path=path, max_sessions=20)
    sessions = load_sent_sessions(path=path)
    assert sessions[0].session_id == "abc"
    assert sessions[0].items[0].status == "success"


def test_sent_items_prune(tmp_path):
    path = tmp_path / "sent_items.json"
    for i in range(25):
        session = SentSession(
            session_id=str(i),
            started_at="2024-01-01T00:00:00Z",
            finished_at="2024-01-01T00:01:00Z",
            location_id=None,
            sources=[],
            items=[],
        )
        record_sent_session(session, path=path, max_sessions=20)
    sessions = load_sent_sessions(path=path)
    assert len(sessions) == 20
    assert sessions[0].session_id == "24"


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
