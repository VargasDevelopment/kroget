from kroget.core.staple_name import normalize_staple_name


def test_normalize_staple_name():
    assert normalize_staple_name("  oat   milk  ") == "oat milk"
    assert normalize_staple_name("") == "staple"
