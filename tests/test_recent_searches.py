from kroget.core.recent_searches import load_recent_searches, record_recent_search


def test_record_recent_search_overwrite(tmp_path):
    path = tmp_path / "recent.json"
    record_recent_search(
        term="milk",
        upc="000111",
        description="Milk",
        path=path,
        timestamp="2024-01-01T00:00:00Z",
    )
    record_recent_search(
        term="milk",
        upc="000222",
        description="Milk 2",
        path=path,
        timestamp="2024-01-02T00:00:00Z",
    )
    entries = load_recent_searches(path=path)
    assert len(entries) == 1
    assert entries[0].upc == "000222"


def test_record_recent_search_prunes(tmp_path):
    path = tmp_path / "recent.json"
    for index in range(60):
        record_recent_search(
            term=f"item-{index}",
            upc=str(index),
            description="desc",
            path=path,
            timestamp=f"2024-01-01T00:00:{index:02d}Z",
        )
    entries = load_recent_searches(path=path)
    assert len(entries) == 50
    assert entries[0].term == "item-59"
