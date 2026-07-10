from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_text_lossy(path: Path, limit: int | None = None) -> str:
    data = path.read_bytes()
    if limit is not None:
        data = data[:limit]
    for enc in ('utf-8', 'utf-8-sig', 'gb18030', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', errors='replace')


def mask_abs(path: Path) -> str:
    return str(path)
