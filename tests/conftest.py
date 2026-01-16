import pytest


@pytest.fixture(autouse=True)
def isolate_kroget_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KROGET_DATA_DIR", str(tmp_path))
