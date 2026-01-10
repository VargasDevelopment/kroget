from __future__ import annotations

import re


_whitespace = re.compile(r"\s+")


def normalize_staple_name(text: str) -> str:
    name = _whitespace.sub(" ", text.strip())
    return name or "staple"
