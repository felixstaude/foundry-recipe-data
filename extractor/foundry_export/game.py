"""Locating game files, reading version info and the template YAML dump."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .steam import APP_ID as STEAM_APP_ID, GameLocation, find_game, read_app_manifest  # noqa: F401


@dataclass
class GamePaths:
    root: Path
    data: Path
    streaming: Path

    @property
    def templates(self) -> Path:
        return self.streaming / 'Templates'

    @property
    def locale(self) -> Path:
        return self.streaming / 'locale'

    @property
    def main_bundle(self) -> Path:
        return self.streaming / 'AssetBundles' / 'foundry_main_bundle'


def locate(game_dir: str | os.PathLike) -> GamePaths:
    root = Path(game_dir).expanduser().resolve()
    data_dirs = [d for d in root.glob('*_Data') if d.is_dir()]
    if not data_dirs:
        raise SystemExit(f'{root}: no *_Data folder found - is this the FOUNDRY game folder?')
    data = data_dirs[0]
    gp = GamePaths(root, data, data / 'StreamingAssets')
    for p in (gp.locale, gp.main_bundle):  # Templates is optional: sources.py falls back to the bundle
        if not p.exists():
            raise SystemExit(f'missing {p}')
    return gp


def read_versions(gp: GamePaths, loc: GameLocation | None = None) -> dict:
    """gameVersion from version.txt (Application.version + revision); steamBuildId / steamBranch from the Steam app
    manifest of the library that contains the game (foundry_export.steam searches every library)."""
    version_file = gp.root / 'version.txt'
    if not version_file.exists():
        raise SystemExit(f'missing {version_file}')
    game_version = version_file.read_text(encoding='utf-8').strip()
    if loc is None:
        loc = find_game(gp.root)
    branch = None
    if loc.manifest:
        app = read_app_manifest(loc.manifest)
        branch = next((c.get('BetaKey') for c in (app.get('MountedConfig'), app.get('UserConfig'))
                       if isinstance(c, dict) and c.get('BetaKey')), None)
    return {'gameVersion': game_version, 'steamBuildId': loc.build_id, 'steamBranch': branch}


def load_templates(gp: GamePaths, type_name: str) -> dict[str, dict]:
    """All templates of one type from StreamingAssets/Templates/<type>/*.yaml, keyed by identifier
    (thin wrapper; the template sources incl. the bundle fallback live in sources.py)."""
    from .sources import YamlTemplateSource
    return YamlTemplateSource(gp.templates).load(type_name)


# ---- value helpers -------------------------------------------------------

def num(v) -> float | int | None:
    """Fixed-point string (or plain number) -> JSON number; '' -> None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v or v in (float('inf'), float('-inf')):
            raise ValueError(f'not a finite number: {v!r}')
        return v
    s = str(v).strip()
    if s == '':
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f'not a number: {v!r}')
    if not d.is_finite():
        raise ValueError(f'not a finite number: {v!r}')
    return int(d) if d == d.to_integral_value() else float(d)


def text(v) -> str | None:
    if v is None:
        return None
    s = str(v)
    return s if s != '' else None


def flags(v) -> list[str]:
    if v in (None, ''):
        return []
    return [f.strip() for f in str(v).split('|') if f.strip()]


def strip_asset_ref(v) -> str | None:
    """'Assets/...asset|guid' -> 'Assets/...asset'."""
    if not v:
        return None
    return str(v).split('|', 1)[0]


def r4(x: float) -> float:
    return round(x + 0.0, 4)
