import json

import pytest

from kroget.core.storage import Staple, add_staple, load_staples, remove_staple, update_staple


def test_staples_crud(tmp_path):
    path = tmp_path / "staples.json"
    staple = Staple(name="milk", term="milk", quantity=2)

    add_staple(staple, path=path)
    staples = load_staples(path=path)
    assert len(staples) == 1
    assert staples[0].name == "milk"

    update_staple("milk", quantity=3, path=path)
    staples = load_staples(path=path)
    assert staples[0].quantity == 3

    remove_staple("milk", path=path)
    staples = load_staples(path=path)
    assert staples == []


def test_staples_duplicate(tmp_path):
    path = tmp_path / "staples.json"
    staple = Staple(name="milk", term="milk", quantity=1)
    add_staple(staple, path=path)
    with pytest.raises(ValueError):
        add_staple(staple, path=path)


def test_staples_file_schema(tmp_path):
    path = tmp_path / "staples.json"
    path.write_text(json.dumps({"staples": [{"name": "eggs", "term": "eggs", "quantity": 1}]}))
    staples = load_staples(path=path)
    assert staples[0].name == "eggs"
