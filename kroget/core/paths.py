from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.getenv("KROGET_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".kroget"
