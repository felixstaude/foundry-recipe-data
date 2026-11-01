"""Finding the FOUNDRY installation (pure stdlib).

Search order of find_game(): explicit argument > env FOUNDRY_GAME_DIR > Steam libraries
(every Steam root, every library from libraryfolders.vdf, appmanifest_983870.acf -> steamapps/common/<installdir>)
> hint file (repo game_path.txt) > GameNotFound. The Steam app manifest also yields build id, StateFlags and
LastUpdated, which tell whether Steam has finished installing/updating the game.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

APP_ID = '983870'
ENV_GAME_DIR = 'FOUNDRY_GAME_DIR'
STATE_FULLY_INSTALLED = 4      # Steam EAppState: StateFlags == 4 -> installed and up to date
DEFAULT_INSTALLDIR = 'FOUNDRY'
HINT_FILE = Path(__file__).resolve().parents[2] / 'game_path.txt'   # repo root (only exists in a checkout)



class GameNotFound(Exception):
    """No valid FOUNDRY folder; .searched lists every place that was looked at (and why it failed)."""

    def __init__(self, searched: list[str]):
        self.searched = list(searched)
        lines = '\n'.join(f'  - {s}' for s in self.searched) or '  (nothing)'
        super().__init__(f'FOUNDRY game folder not found. Searched:\n{lines}\n'
                         f'Pass the game folder explicitly or set {ENV_GAME_DIR}.')


@dataclass
class GameLocation:
    root: Path
    source: str                          # 'argument' | 'env' | 'steam-library' | 'hint-file'
    manifest: Path | None = None         # steamapps/appmanifest_983870.acf
    library: Path | None = None          # Steam library folder containing steamapps/
    build_id: str | None = None
    state_flags: int | None = None
    installdir: str | None = None
    last_updated: int | None = None      # unix time
    alternatives: list[Path] = field(default_factory=list)
    alternative_locations: list['GameLocation'] = field(default_factory=list, repr=False)
    target_build_id: str | None = None   # TargetBuildID while an update is queued ('0'/missing -> None)

    @property
    def update_pending(self) -> bool:
        """Steam has not finished installing/updating (manifest present and StateFlags != 4)."""
        return self.manifest is not None and self.state_flags != STATE_FULLY_INSTALLED

    @property
    def game_version(self) -> str | None:
        f = self.root / 'version.txt'
        try:
            return f.read_text(encoding='utf-8').strip() or None
        except OSError:
            return None

    def as_dict(self) -> dict:
        """JSON-friendly view (used by 'locate')."""
        s = lambda p: str(p) if p is not None else None  # noqa: E731
        return {'root': str(self.root), 'source': self.source, 'gameVersion': self.game_version,
                'steamBuildId': self.build_id, 'stateFlags': self.state_flags,
                'updatePending': self.update_pending, 'targetBuildId': self.target_build_id,
                'lastUpdated': self.last_updated, 'installdir': self.installdir,
                'manifest': s(self.manifest), 'library': s(self.library),
                'alternatives': [str(p) for p in self.alternatives]}


# ---- Valve KeyValues (VDF/ACF) ---------------------------------------------

_ESCAPES = {'\\': '\\', '"': '"', 'n': '\n', 't': '\t'}
_BREAK = frozenset(' \t\r\n\ufeff"{}')


def _tokens(text: str):
    """(token, is_string) pairs; braces come as ('{', False) / ('}', False)."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n\ufeff':
            i += 1
        elif c == '/' and text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
        elif c in '{}':
            yield c, False
            i += 1
        elif c == '"':
            buf, i = [], i + 1
            while i < n and text[i] != '"':
                if text[i] == '\\' and i + 1 < n:
                    e = _ESCAPES.get(text[i + 1])
                    buf.append(e if e is not None else text[i:i + 2])   # unknown escape kept verbatim
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
            yield ''.join(buf), True
        else:
            j = i
            while j < n and text[j] not in _BREAK:
                j += 1
            tok = text[i:j]
            i = j
            if not (tok.startswith('[') and tok.endswith(']')):   # skip [$WIN32]-style conditionals
                yield tok, True


def parse_vdf(text: str) -> dict:
    """Valve KeyValues text -> nested dicts of strings. Duplicate block keys are merged, duplicate values
    overwritten; unbalanced braces and dangling keys are tolerated."""
    root: dict = {}
    stack = [root]
    key: str | None = None
    for tok, is_str in _tokens(text):
        if is_str:
            if key is None:
                key = tok
            else:
                stack[-1][key] = tok
                key = None
        elif tok == '{':
            cur = stack[-1]
            k = key if key is not None else ''
            child = cur.get(k)
            if not isinstance(child, dict):
                child = cur[k] = {}
            stack.append(child)
            key = None
        else:
            key = None
            if len(stack) > 1:
                stack.pop()
    return root


def _ci(d: Mapping, key: str, default=None):
    """Case-insensitive dict lookup (Steam is not consistent: 'LibraryFolders'/'libraryfolders', 'BuildID'...)."""
    if key in d:
        return d[key]
    low = key.lower()
    for k, v in d.items():
        if k.lower() == low:
            return v
    return default


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _read_vdf(path: Path) -> dict:
    return parse_vdf(path.read_text(encoding='utf-8', errors='replace'))


# ---- Steam roots and libraries -------------------------------------------

def _registry_steam_paths() -> list[str]:
    """Steam install paths from the Windows registry ([] elsewhere or on error)."""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return []
    out = []
    for hive, sub, name in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
        try:
            with winreg.OpenKey(hive, sub) as k:
                val, _ = winreg.QueryValueEx(k, name)
        except OSError:
            continue
        if val:
            out.append(str(val))
    return out


def _root_candidates(env: Mapping[str, str], home: Path | None, platform: str) -> list[Path]:
    """All Steam root candidates in priority order (existing or not)."""
    cands = [Path(env[k]).expanduser() for k in ('STEAM_DIR', 'STEAM_ROOT') if env.get(k)]
    if platform in ('win32', 'cygwin'):
        cands += [Path(p) for p in _registry_steam_paths()]
        cands += [Path(env[k]) / 'Steam' for k in ('ProgramFiles(x86)', 'ProgramFiles') if env.get(k)]
    elif home is None:
        pass
    elif platform == 'darwin':
        cands.append(home / 'Library' / 'Application Support' / 'Steam')
    else:   # linux, *bsd
        flatpak = home / '.var' / 'app' / 'com.valvesoftware.Steam'
        cands += [home / '.local' / 'share' / 'Steam', home / '.steam' / 'steam', home / '.steam' / 'root',
                  flatpak / '.local' / 'share' / 'Steam', flatpak / 'data' / 'Steam',
                  home / 'snap' / 'steam' / 'common' / '.local' / 'share' / 'Steam']
    return cands


def _resolved(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _dedupe_dirs(paths) -> list[Path]:
    out, seen = [], set()
    for p in paths:
        try:
            if not p.is_dir():
                continue
        except OSError:
            continue
        r = _resolved(p)
        if r not in seen:
            seen.add(r)
            out.append(p)
    return out


def _home(home: Path | str | None) -> Path | None:
    if home is not None:
        return Path(home)
    try:
        return Path.home()
    except RuntimeError:   # no HOME / unknown user
        return None


def steam_roots(env: Mapping[str, str] = os.environ, home: Path | str | None = None,
                platform: str = sys.platform) -> list[Path]:
    """Existing Steam installation folders, de-duplicated by resolved path, in priority order."""
    return _dedupe_dirs(_root_candidates(env, _home(home), platform))


def _steamapps(lib: Path) -> Path:
    for name in ('steamapps', 'SteamApps'):
        if (lib / name).is_dir():
            return lib / name
    return lib / 'steamapps'


def library_folders(steam_root: Path | str) -> list[Path]:
    """steam_root itself + every existing library listed in steamapps/libraryfolders.vdf (or config/libraryfolders.vdf).
    Handles the current format ("0" { "path" "..." }) and the old one ("1" "D:\\\\SteamLibrary")."""
    steam_root = Path(steam_root)
    libs = [steam_root]
    for vdf in (_steamapps(steam_root) / 'libraryfolders.vdf', steam_root / 'config' / 'libraryfolders.vdf'):
        try:
            data = _read_vdf(vdf)
        except OSError:
            continue
        lf = _ci(data, 'libraryfolders')
        if not isinstance(lf, dict):
            continue
        for k, v in lf.items():
            p = _ci(v, 'path') if isinstance(v, dict) else (v if k.isdigit() else None)
            if isinstance(p, str) and p.strip():
                libs.append(Path(p.strip()).expanduser())
    return _dedupe_dirs(libs)


def read_app_manifest(path: Path | str) -> dict:
    """The AppState block of an appmanifest_*.acf ({} if absent)."""
    st = _ci(_read_vdf(Path(path)), 'AppState')
    return st if isinstance(st, dict) else {}


def _installdir_matches(manifest: Path, root: Path) -> bool:
    try:
        inst = _ci(read_app_manifest(manifest), 'installdir')
    except OSError:
        return False
    if not inst:
        return True
    return inst.lower() == root.name.lower() or _resolved(manifest.parent / 'common' / inst) == _resolved(root)


def manifest_for_game_dir(root: Path | str, roots: list[Path] | None = None) -> Path | None:
    """App manifest belonging to a game folder: root.parent.parent/appmanifest_983870.acf (unresolved, then resolved
    path), else any library whose steamapps/common/<installdir> resolves to root."""
    root = Path(root).expanduser()
    name = f'appmanifest_{APP_ID}.acf'
    for r in dict.fromkeys((root.absolute(), _resolved(root))):
        m = r.parent.parent / name
        if m.is_file() and _installdir_matches(m, r):
            return m
    target = _resolved(root)
    for sr in (steam_roots() if roots is None else roots):
        for lib in library_folders(sr):
            m = _steamapps(lib) / name
            if not m.is_file():
                continue
            try:
                inst = _ci(read_app_manifest(m), 'installdir') or DEFAULT_INSTALLDIR
            except OSError:
                continue
            if _resolved(m.parent / 'common' / inst) == target:
                return m
    return None


# ---- game folder discovery -----------------------------------------------

def _data_dir(root: Path) -> Path | None:
    try:
        for d in sorted(root.glob('*_Data')):
            if (d / 'StreamingAssets').is_dir():
                return d
    except OSError:
        pass
    return None


def is_game_dir(p: Path | str) -> bool:
    """A FOUNDRY folder contains '<name>_Data/StreamingAssets'."""
    return _data_dir(Path(p)) is not None


def _normalize(p: Path) -> Path:
    """Accept the exe or the *_Data folder as well as the game folder itself."""
    if p.is_file():
        p = p.parent
    if p.name.endswith('_Data') and (p / 'StreamingAssets').is_dir():
        p = p.parent
    return p


def _why_invalid(p: Path) -> str:
    if not p.exists():
        return 'does not exist'
    if not p.is_dir():
        return 'not a directory'
    return 'no *_Data/StreamingAssets folder'


def _from_manifest(loc: GameLocation, manifest: Path | None, library: Path | None = None) -> GameLocation:
    if manifest is None:
        return loc
    try:
        st = read_app_manifest(manifest)
    except OSError:
        st = {}
    loc.manifest = manifest
    loc.library = library if library is not None else manifest.parent.parent
    loc.build_id = _ci(st, 'buildid') or None
    loc.state_flags = _int(_ci(st, 'StateFlags'))
    loc.installdir = _ci(st, 'installdir') or None
    loc.last_updated = _int(_ci(st, 'LastUpdated'))
    tb = _ci(st, 'TargetBuildID')
    loc.target_build_id = tb if tb and tb != '0' and tb != loc.build_id else None
    return loc


def _steam_candidates(roots: list[Path], searched: list[str]) -> list[GameLocation]:
    found: list[GameLocation] = []
    seen_libs, seen_games = set(), set()
    name = f'appmanifest_{APP_ID}.acf'
    for sr in roots:
        for lib in library_folders(sr):
            rl = _resolved(lib)
            if rl in seen_libs:
                continue
            seen_libs.add(rl)
            sa = _steamapps(lib)
            m = sa / name
            if m.is_file():
                try:
                    inst = _ci(read_app_manifest(m), 'installdir') or DEFAULT_INSTALLDIR
                except OSError as e:
                    searched.append(f'Steam library {lib}: unreadable {name} ({e})')
                    continue
                game, manifest = sa / 'common' / inst, m
            else:   # leftover folder without manifest: still usable, ranked last
                game, manifest = sa / 'common' / DEFAULT_INSTALLDIR, None
            if not is_game_dir(game):
                searched.append(f'Steam library {lib}: ' + (f'{name} found but {game} is invalid ({_why_invalid(game)})'
                                                            if manifest else f'no {name}'))
                continue
            rg = _resolved(game)
            if rg in seen_games:
                continue
            seen_games.add(rg)
            found.append(_from_manifest(GameLocation(game, 'steam-library', library=lib), manifest, lib))
    return found


def _rank(loc: GameLocation) -> tuple:
    return (loc.manifest is not None, loc.state_flags == STATE_FULLY_INSTALLED, loc.last_updated or 0)


def find_game(explicit: str | os.PathLike | None = None, *, env: Mapping[str, str] = os.environ,
              home: Path | str | None = None, hint_file: Path | str | None = None,
              platform: str = sys.platform) -> GameLocation:
    """Locate the FOUNDRY folder. An explicit argument or FOUNDRY_GAME_DIR that is not a valid game folder raises
    GameNotFound (no silent fallback). Among several Steam installs the fully installed (StateFlags 4), then the most
    recently updated one wins; the others are listed in .alternatives."""
    searched: list[str] = []
    roots_cache: list[list[Path]] = []

    def roots() -> list[Path]:
        if not roots_cache:
            roots_cache.append(steam_roots(env, home, platform))
        return roots_cache[0]

    def direct(raw, source: str, label: str) -> GameLocation | None:
        p = _normalize(Path(raw).expanduser())
        if not is_game_dir(p):
            searched.append(f'{label} {p}: {_why_invalid(p)}')
            return None
        return _from_manifest(GameLocation(p, source), manifest_for_game_dir(p, roots()))

    if explicit not in (None, ''):
        loc = direct(explicit, 'argument', 'argument')
        if loc is None:
            raise GameNotFound(searched)
        return loc
    if env.get(ENV_GAME_DIR):
        loc = direct(env[ENV_GAME_DIR], 'env', f'env {ENV_GAME_DIR}')
        if loc is None:
            raise GameNotFound(searched)
        return loc

    searched += [f'Steam root {c}: does not exist' for c in _root_candidates(env, _home(home), platform)
                 if not c.is_dir()]
    found = _steam_candidates(roots(), searched)
    if found:
        found.sort(key=_rank, reverse=True)   # stable: equal rank keeps root/library priority order
        best = found[0]
        best.alternatives = [f.root for f in found[1:]]
        best.alternative_locations = found[1:]
        return best

    if hint_file is not None:
        hf = Path(hint_file)
        try:
            line = next((ln.strip() for ln in hf.read_text(encoding='utf-8').splitlines() if ln.strip()), '')
        except OSError:
            searched.append(f'hint file {hf}: does not exist')
        else:
            if line:
                loc = direct(line, 'hint-file', f'hint file {hf} ->')
                if loc is not None:
                    return loc
            else:
                searched.append(f'hint file {hf}: empty')
    raise GameNotFound(searched)
