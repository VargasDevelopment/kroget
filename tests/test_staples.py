import json

import pytest

from kroget.core.storage import Staple, add_staple, get_staples, remove_staple, update_staple


def test_staples_crud(tmp_path):
    path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    staple = Staple(name="milk", term="milk", quantity=2)

    add_staple(staple, lists_path=path, staples_path=staples_path)
    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert len(staples) == 1
    assert staples[0].name == "milk"

    update_staple("milk", quantity=3, lists_path=path, staples_path=staples_path)
    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert staples[0].quantity == 3

    remove_staple("milk", lists_path=path, staples_path=staples_path)
    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert staples == []


def test_staples_duplicate(tmp_path):
    path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    staple = Staple(name="milk", term="milk", quantity=1)
    add_staple(staple, lists_path=path, staples_path=staples_path)
    with pytest.raises(ValueError):
        add_staple(staple, lists_path=path, staples_path=staples_path)


def test_staples_file_schema(tmp_path):
    path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    payload = {"active": "Staples", "lists": {"Staples": [{"name": "eggs", "term": "eggs", "quantity": 1}]}}
    path.write_text(json.dumps(payload))
    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert staples[0].name == "eggs"


def test_remove_staple_by_preferred_upc(tmp_path):
    path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    staple = Staple(name="milk", term="milk", quantity=1, preferred_upc="000111")
    add_staple(staple, lists_path=path, staples_path=staples_path)

    remove_staple("000111", lists_path=path, staples_path=staples_path)

    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert staples == []


def test_remove_staple_by_name_case_insensitive(tmp_path):
    path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    staple = Staple(name="Eggs", term="eggs", quantity=1)
    add_staple(staple, lists_path=path, staples_path=staples_path)

    remove_staple("eggs", lists_path=path, staples_path=staples_path)

    staples = get_staples(lists_path=path, staples_path=staples_path)
    assert staples == []
