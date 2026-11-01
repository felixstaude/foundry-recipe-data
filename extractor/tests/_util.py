"""Shared test helpers. Run all tests from the repo root with

    python3 -m unittest discover -s extractor/tests -v      (or: python3 -m pytest extractor/tests)

The game folder is found exactly like the extractor finds it (foundry_export.steam.find_game: env FOUNDRY_GAME_DIR,
then the Steam libraries, then game_path.txt). Tests that need the game are skipped when there is none, but they
FAIL instead of skipping when
  * FOUNDRY_GAME_DIR is set but does not point to a valid game folder, or
  * FOUNDRY_REQUIRE_GAME=1 is set (UPDATE.md step f) and no game is found.
FOUNDRY_SKIP_SLOW=1 skips the slow end-to-end tests (fake game folders, extra full exports).
"""
from __future__ import annotations

import contextlib
import functools
import io
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
EXTRACTOR = TESTS.parent
REPO = EXTRACTOR.parent
if str(EXTRACTOR) not in sys.path:
    sys.path.insert(0, str(EXTRACTOR))

from foundry_export.steam import APP_ID, ENV_GAME_DIR, HINT_FILE, GameNotFound, find_game  # noqa: E402

EXPORT = EXTRACTOR / 'export'
REQUIRE_GAME = os.environ.get('FOUNDRY_REQUIRE_GAME') == '1'
SKIP_SLOW = os.environ.get('FOUNDRY_SKIP_SLOW') == '1'


def _discover() -> tuple[Path | None, str | None, str]:
    """(game root, problem, skip reason). A problem turns the game tests into failures."""
    try:
        loc = find_game(hint_file=HINT_FILE)          # same call as foundry_export.cli._find
    except GameNotFound as e:
        if os.environ.get(ENV_GAME_DIR):
            return None, f'{ENV_GAME_DIR} is set but invalid - fix or unset it.\n{e}', ''
        if REQUIRE_GAME:
            return None, f'FOUNDRY_REQUIRE_GAME=1 but the game was not found.\n{e}', ''
        return None, None, 'FOUNDRY game folder not found (Steam libraries, FOUNDRY_GAME_DIR, game_path.txt)'
    if not (loc.root / 'version.txt').is_file():
        msg = f'{loc.root} (found via {loc.source}) has no version.txt - incomplete game folder'
        if os.environ.get(ENV_GAME_DIR) or REQUIRE_GAME:
            return None, msg, ''
        return None, None, msg
    return loc.root, None, ''


def game_dir() -> Path | None:
    return _discover()[0]


GAME, GAME_PROBLEM, _SKIP_REASON = _discover()


def require_game(obj):
    """Class or test method decorator: needs the installed game. Without one the test is skipped, or fails when
    GAME_PROBLEM is set (invalid FOUNDRY_GAME_DIR / FOUNDRY_REQUIRE_GAME=1)."""
    if GAME is not None:
        return obj
    if GAME_PROBLEM is None:
        return unittest.skip(_SKIP_REASON)(obj)
    problem = GAME_PROBLEM
    if isinstance(obj, type):
        def setUpClass(cls):
            raise AssertionError(problem)
        obj.setUpClass = classmethod(setUpClass)
        return obj

    @functools.wraps(obj)
    def failing(self, *_a, **_kw):
        self.fail(problem)
    return failing


slow = unittest.skipIf(SKIP_SLOW, 'FOUNDRY_SKIP_SLOW=1')


# ---------------------------------------------------------------- running the exporter

def run_export(game: Path | str, out: Path | str, *extra: str, timeout: int = 900) -> subprocess.CompletedProcess:
    """extractor/export <game> <out> [extra...] in a subprocess (safe to run several in parallel threads)."""
    return subprocess.run([sys.executable, str(EXPORT), str(game), str(out), *extra], capture_output=True, text=True,
                          timeout=timeout)


def run_cli(argv: list[str]) -> tuple[int, str]:
    """foundry_export.cli.main(argv) in-process; (exit code, stdout + stderr)."""
    from foundry_export import cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def parallel(tasks: dict):
    """Run {name: callable} in threads (exports are subprocesses, so they really run in parallel); {name: result}.
    At most one task may call run_cli (in-process, redirects stdout)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(len(tasks), os.cpu_count() or 2, 8))) as ex:
        futures = {name: ex.submit(fn) for name, fn in tasks.items()}
        return {name: f.result() for name, f in futures.items()}


def describe(r: subprocess.CompletedProcess) -> str:
    return f'exit {r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}'


def tree(root: Path) -> dict[str, bytes]:
    """{relative path: bytes} of every file below root ({} if root does not exist)."""
    root = Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


# ---------------------------------------------------------------- fake game folders

def game_data_dir(game: Path) -> Path:
    return next(d for d in sorted(Path(game).glob('*_Data')) if (d / 'StreamingAssets').is_dir())


def make_fake_game(base: Path, build: str | None, *, templates: str = 'link',
                   patch: dict[str, dict[str, str]] | None = None) -> Path:
    """<base>/steamapps/common/<name> that behaves like the installed game: version.txt and the Steam app manifest
    (buildid replaced, StateFlags 4) are copies, every *_Data entry is a symlink into the real game, so nothing big
    is copied. StreamingAssets/Templates:
      'link'  symlink to the real dump (default)
      'patch' type folders symlinked, except the types in `patch` ({type: {file name: new text}}): real folders
              whose other files are symlinks
      'empty' only the type folders, no *.yaml files
      'none'  no Templates folder at all
    build=None writes no app manifest (steamBuildId null)."""
    game = Path(GAME).resolve()
    data = game_data_dir(game)
    root = Path(base) / 'steamapps' / 'common' / game.name
    fdata = root / data.name
    fdata.mkdir(parents=True)
    shutil.copy2(game / 'version.txt', root / 'version.txt')
    if build is not None:
        acf = game.parent.parent / f'appmanifest_{APP_ID}.acf'
        text = acf.read_text(encoding='utf-8', errors='replace') if acf.is_file() else (
            f'"AppState"\n{{\n\t"appid"\t\t"{APP_ID}"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{game.name}"\n'
            f'\t"LastUpdated"\t\t"1700000000"\n\t"buildid"\t\t"0"\n}}\n')
        text = re.sub(r'("buildid"\s+)"[^"]*"', lambda m: f'{m.group(1)}"{build}"', text, flags=re.I)
        text = re.sub(r'("StateFlags"\s+)"[^"]*"', lambda m: f'{m.group(1)}"4"', text, flags=re.I)
        text = re.sub(r'("installdir"\s+)"[^"]*"', lambda m: f'{m.group(1)}"{game.name}"', text, flags=re.I)
        (root.parent.parent / f'appmanifest_{APP_ID}.acf').write_text(text, encoding='utf-8')
    for e in data.iterdir():
        if e.name != 'StreamingAssets':
            (fdata / e.name).symlink_to(e, target_is_directory=e.is_dir())
    sa_real, sa = data / 'StreamingAssets', fdata / 'StreamingAssets'
    sa.mkdir()
    for e in sa_real.iterdir():
        if e.name != 'Templates':
            (sa / e.name).symlink_to(e, target_is_directory=e.is_dir())
    tpl_real = sa_real / 'Templates'
    if templates == 'none' or not tpl_real.is_dir():
        return root
    if templates == 'link':
        (sa / 'Templates').symlink_to(tpl_real, target_is_directory=True)
        return root
    if templates not in ('patch', 'empty'):
        raise ValueError(templates)
    patch = patch or {}
    unknown = set(patch) - {t.name for t in tpl_real.iterdir() if t.is_dir()}
    if unknown:
        raise ValueError(f'no template folder {sorted(unknown)}')
    for t in sorted(p for p in tpl_real.iterdir() if p.is_dir()):
        target = sa / 'Templates' / t.name
        if templates == 'empty':
            target.mkdir(parents=True)
        elif t.name in patch:
            target.mkdir(parents=True)
            missing = set(patch[t.name]) - {f.name for f in t.iterdir()}
            if missing:
                raise ValueError(f'no file {sorted(missing)} in {t}')
            for f in t.iterdir():
                if f.name in patch[t.name]:
                    (target / f.name).write_text(patch[t.name][f.name], encoding='utf-8')
                else:
                    (target / f.name).symlink_to(f)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(t, target_is_directory=True)
    return root
