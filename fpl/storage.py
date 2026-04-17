from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def load_watchlist(path: str | Path) -> set[int]:
    p = Path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {int(x) for x in data}
    except Exception:
        return set()
    return set()


def save_watchlist(path: str | Path, ids: Iterable[int]) -> None:
    p = Path(path)
    payload = sorted({int(x) for x in ids})
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

