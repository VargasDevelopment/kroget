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
    move_item,
    remove_staple,
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


def test_remove_staple_targets_only_named_list(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    create_list("Alt", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="milk", term="milk", quantity=1),
        list_name="Staples",
        lists_path=lists_path,
        staples_path=staples_path,
    )
    add_staple(
        Staple(name="milk", term="milk", quantity=1),
        list_name="Alt",
        lists_path=lists_path,
        staples_path=staples_path,
    )

    remove_staple("milk", list_name="Alt", lists_path=lists_path, staples_path=staples_path)

    assert len(get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)) == 0
    assert len(get_staples(list_name="Staples", lists_path=lists_path, staples_path=staples_path)) == 1


def test_move_item_by_preferred_upc(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    create_list("Alt", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="chips", term="chips", quantity=2, preferred_upc="000222"),
        list_name="Staples",
        lists_path=lists_path,
        staples_path=staples_path,
    )

    move_item("Staples", "Alt", "000222", lists_path=lists_path, staples_path=staples_path)

    assert get_staples(list_name="Staples", lists_path=lists_path, staples_path=staples_path) == []
    staples = get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)
    assert len(staples) == 1
    assert staples[0].preferred_upc == "000222"
    assert staples[0].name == "chips"


def test_move_item_merges_quantity_on_conflict(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    create_list("Alt", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="soda", term="soda", quantity=1, preferred_upc="000333"),
        list_name="Alt",
        lists_path=lists_path,
        staples_path=staples_path,
    )
    add_staple(
        Staple(name="Soda", term="soda", quantity=2, preferred_upc="000333"),
        list_name="Staples",
        lists_path=lists_path,
        staples_path=staples_path,
    )

    move_item("Staples", "Alt", "000333", lists_path=lists_path, staples_path=staples_path)

    staples = get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)
    assert len(staples) == 1
    assert staples[0].quantity == 3
    assert get_staples(list_name="Staples", lists_path=lists_path, staples_path=staples_path) == []


def test_move_item_invalid_identifier_no_change(tmp_path):
    lists_path = tmp_path / "lists.json"
    staples_path = tmp_path / "staples.json"
    create_list("Alt", lists_path=lists_path, staples_path=staples_path)
    add_staple(
        Staple(name="milk", term="milk", quantity=1),
        list_name="Staples",
        lists_path=lists_path,
        staples_path=staples_path,
    )
    before_staples = get_staples(list_name="Staples", lists_path=lists_path, staples_path=staples_path)
    before_alt = get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)

    with pytest.raises(ValueError):
        move_item("Staples", "Alt", "nope", lists_path=lists_path, staples_path=staples_path)

    after_staples = get_staples(list_name="Staples", lists_path=lists_path, staples_path=staples_path)
    after_alt = get_staples(list_name="Alt", lists_path=lists_path, staples_path=staples_path)
    assert after_staples == before_staples
    assert after_alt == before_alt
