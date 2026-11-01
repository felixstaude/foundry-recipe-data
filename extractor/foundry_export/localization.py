"""Template localization from foundry_templates-<lang>.mo (key scheme: Main/PoMgr.generateId)."""
from __future__ import annotations

import gettext
from pathlib import Path


def load_catalogs(locale_dir: Path) -> dict[str, dict[str, str]]:
    out = {}
    for lang_dir in sorted(p for p in locale_dir.iterdir() if p.is_dir()):
        lang = lang_dir.name
        mo = lang_dir / 'LC_MESSAGES' / f'foundry_templates-{lang}.mo'
        if not mo.exists():
            continue
        with open(mo, 'rb') as fh:
            cat = gettext.GNUTranslations(fh)._catalog  # noqa: SLF001 - stdlib has no public accessor
        out[lang] = {k: v for k, v in cat.items() if isinstance(k, str) and k}
    return out


def key(type_name: str, identifier: str, field: str, path: list[tuple[str, int]] = ()) -> str:
    """Rebuild PoMgr.generateId. path = [(fieldName, index), ...] of enclosing array elements."""
    parent = ''.join(f'_{f.upper()}_{i}' for f, i in path)
    k = f'{type_name.upper()}{identifier.upper()}{parent}_{field.upper()}'
    if path:
        k += f'_{path[-1][1]}'
    return k
