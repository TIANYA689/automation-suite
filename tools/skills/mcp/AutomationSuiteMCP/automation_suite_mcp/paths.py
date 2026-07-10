from __future__ import annotations

from pathlib import Path
from .config import SUITE_ROOT


def resolve_path(path: str | Path, *, must_exist: bool = False) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (SUITE_ROOT / p).resolve()
    else:
        p = p.resolve()
    if must_exist and not p.exists():
        raise FileNotFoundError(str(p))
    return p


def ensure_child_or_absolute_output(path: str | Path) -> Path:
    p = resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
