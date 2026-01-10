import json

import pytest

from kroget.core.storage import (
    Staple,
    add_staple,
    create_list,
    delete_list,
    get_active_list,
    get_staples,
    list_names,
    rename_list,
    set_active_list,
    update_staple,
)


def test_lists_migration(tmp_path):
    staples_path = tmp_path / "staples.json"
    lists_path = tmp_path / "lists.json"

    staples_payload = {"staples": [{"name": "milk", "term": "milk", "quantity": 1}]}
    staples_path.write_text(json.dumps(staples_payload))

    active = get_active_list(lists_path=lists_path, staples_path=staples_path)
    assert active == "Staples"
    staples = get_staples(lists_path=lists_path, staples_path=staples_path)
    assert staples[0].name == "milk"
    assert staples_path.exists()


def test_list_crud(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"

    assert "Staples" in list_names(lists_path=lists_path, staples_path=staples_path)

    create_list("Weekly", lists_path=lists_path, staples_path=staples_path)
    assert "Weekly" in list_names(lists_path=lists_path, staples_path=staples_path)

    set_active_list("Weekly", lists_path=lists_path, staples_path=staples_path)
    assert get_active_list(lists_path=lists_path, staples_path=staples_path) == "Weekly"

    rename_list("Weekly", "Monthly", lists_path=lists_path, staples_path=staples_path)
    assert "Monthly" in list_names(lists_path=lists_path, staples_path=staples_path)

    delete_list("Monthly", lists_path=lists_path, staples_path=staples_path)
    assert "Monthly" not in list_names(lists_path=lists_path, staples_path=staples_path)


def test_cannot_delete_last_list(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    with pytest.raises(ValueError):
        delete_list("Staples", lists_path=lists_path, staples_path=staples_path)


def test_update_staple_in_list(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    create_list("Alt", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="milk", term="milk", quantity=1),
        list_name="Alt",
        lists_path=lists_path,
        staples_path=staples_path,
    )
    update_staple(
        "milk",
        term="milk",
        quantity=2,
        preferred_upc="000111",
        modality="PICKUP",
        list_name="Alt",
        lists_path=lists_path,
        staples_path=staples_path,
    )
    staples = get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)
    assert staples[0].preferred_upc == "000111"
