"""CLI logic without the real game: check exit codes (incl. Steam library discovery on fake libraries), verify,
version folder naming / overwrite guard, sanity gate and code-hash warnings."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import run_cli as run  # (puts extractor/ on sys.path)

from foundry_export import cli

ACF = '''"AppState"
{
	"appid"		"983870"
	"StateFlags"		"%(flags)s"
	"installdir"		"FOUNDRY"
	"LastUpdated"		"%(updated)s"
	"buildid"		"%(build)s"
	%(beta)s
}
'''


def fake_game(lib: Path, version: str, build: str, flags: int = 4, beta: str | None = None,
              updated: int = 1793545632) -> Path:
    """<lib>/steamapps/common/FOUNDRY with just enough files for locate()/read_versions()."""
    root = lib / 'steamapps' / 'common' / 'FOUNDRY'
    sa = root / 'foundry_Data' / 'StreamingAssets'
    (sa / 'locale').mkdir(parents=True)
    (sa / 'AssetBundles').mkdir()
    (sa / 'AssetBundles' / 'foundry_main_bundle').write_bytes(b'')
    (root / 'version.txt').write_text(version + '\n', encoding='utf-8')
    beta_block = f'"MountedConfig"\n\t{{\n\t\t"BetaKey"\t\t"{beta}"\n\t}}' if beta else ''
    (lib / 'steamapps' / 'appmanifest_983870.acf').write_text(
        ACF % {'flags': flags, 'build': build, 'beta': beta_block, 'updated': updated}, encoding='utf-8')
    return root


def write_latest(out: Path, version: str, build: str | None, folder: bool = True) -> None:
    """out/latest.json (+ index.json and the version folder with a manifest unless folder=False)."""
    name = f'v{version}'
    entry = {'version': name, 'gameVersion': version, 'steamBuildId': build, 'generatedAt': '2026-01-01T00:00:00+00:00'}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'latest.json').write_text(json.dumps(entry), encoding='utf-8')
    (out / 'index.json').write_text(json.dumps({'latest': name, 'versions': [entry]}), encoding='utf-8')
    if folder:
        (out / name).mkdir(exist_ok=True)
        (out / name / 'manifest.json').write_text(json.dumps({'gameVersion': version, 'steamBuildId': build, 'files': {}}),
                                                  encoding='utf-8')


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='fx_cli_')
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / 'out'

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, version, build, latest, flags=4, beta=None):
        game = fake_game(self.tmp / 'lib', version, build, flags, beta)
        if latest:
            write_latest(self.out, *latest)
        return run(['check', '--game', str(game), '--out', str(self.out)])

    def test_same(self):
        code, msg = self.check('0.6.0.26518', '100', ('0.6.0.26518', '100'))
        self.assertEqual(code, cli.CHECK_SAME, msg)
        self.assertIn('STATUS: same', msg)

    def test_new_version(self):
        code, msg = self.check('0.6.1.27000', '200', ('0.6.0.26518', '100'))
        self.assertEqual(code, cli.CHECK_NEW_VERSION, msg)

    def test_new_build_same_version(self):
        code, msg = self.check('0.6.0.26518', '200', ('0.6.0.26518', '100'))
        self.assertEqual(code, cli.CHECK_NEW_BUILD, msg)

    def test_update_pending_wins(self):
        code, msg = self.check('0.6.1.27000', '200', ('0.6.0.26518', '100'), flags=6)
        self.assertEqual(code, cli.CHECK_UPDATE_PENDING, msg)

    def test_first_export(self):
        code, msg = self.check('0.6.0.26518', '100', None)
        self.assertEqual(code, cli.CHECK_FIRST_EXPORT, msg)

    def test_older_version(self):
        code, msg = self.check('0.5.9.20000', '90', ('0.6.0.26518', '100'))
        self.assertEqual(code, cli.CHECK_OLDER, msg)

    def test_beta_branch_shown(self):
        code, msg = self.check('0.6.1.27000', '200', ('0.6.0.26518', '100'), beta='experimental')
        self.assertEqual(code, cli.CHECK_NEW_VERSION, msg)
        self.assertIn('branch experimental', msg)

    def test_latest_points_to_missing_folder(self):
        game = fake_game(self.tmp / 'lib', '0.6.0.26518', '100')
        write_latest(self.out, '0.6.0.26518', '100', folder=False)     # e.g. the -b folder was deleted, not committed
        code, msg = run(['check', '--game', str(game), '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_INCONSISTENT, msg)
        self.assertIn('STATUS: inconsistent', msg)
        (self.out / 'v0.6.0.26518').mkdir()                              # folder without manifest.json: still inconsistent
        self.assertEqual(run(['check', '--game', str(game), '--out', str(self.out)])[0], cli.CHECK_INCONSISTENT)

    def test_game_not_found(self):
        code, msg = run(['check', '--game', str(self.tmp / 'nope'), '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_NOT_FOUND, msg)

    def test_incomplete_game_folder(self):
        game = fake_game(self.tmp / 'lib', '0.6.0.26518', '100')
        write_latest(self.out, '0.6.0.26518', '100')
        (game / 'foundry_Data' / 'StreamingAssets' / 'AssetBundles' / 'foundry_main_bundle').unlink()
        code, msg = run(['check', '--game', str(game), '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_NOT_FOUND, msg)
        self.assertIn('incomplete game folder', msg)
        (game / 'foundry_Data' / 'StreamingAssets' / 'AssetBundles' / 'foundry_main_bundle').write_bytes(b'')
        (game / 'version.txt').unlink()
        code, msg = run(['check', '--game', str(game), '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_NOT_FOUND, msg)

    def test_locate_field(self):
        game = fake_game(self.tmp / 'lib', '0.6.0.26518', '100', beta='experimental')
        code, msg = run(['locate', '--game', str(game), '--field', 'steamBranch'])
        self.assertEqual((code, msg.strip()), (0, 'experimental'))

    def test_export_exit_codes_before_reading_data(self):
        out = self.tmp / 'xout'
        code, msg = run(['export', str(self.tmp / 'nope'), str(out)])
        self.assertEqual(code, cli.EXIT_NOT_FOUND, msg)
        game = fake_game(self.tmp / 'lib', '0.6.1.27000', '200', flags=6)
        code, msg = run(['export', str(game), str(out)])
        self.assertEqual(code, cli.CHECK_UPDATE_PENDING, msg)
        self.assertFalse(out.exists())


@unittest.skipIf(sys.platform.startswith('win'), 'Steam roots come from the registry on Windows')
class SteamLibraryCheckTests(unittest.TestCase):
    """check without --game: discovery over a fake Steam root (STEAM_DIR) with a second library, real Steam hidden
    by a fake HOME."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='fx_cli_steam_')
        self.tmp = Path(self._tmp.name)
        self.steam, self.lib2, self.out = self.tmp / 'steam', self.tmp / 'lib2', self.tmp / 'out'
        (self.tmp / 'home').mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ('FOUNDRY_GAME_DIR', 'STEAM_ROOT')}
        env.update(HOME=str(self.tmp / 'home'), STEAM_DIR=str(self.steam))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def libraries(self, alt_flags: int, alt_updated: int) -> tuple[Path, Path]:
        main = fake_game(self.steam, '0.6.0.26518', '100', flags=4, updated=1000)
        alt = fake_game(self.lib2, '0.6.1.27000', '200', flags=alt_flags, updated=alt_updated)
        (self.steam / 'steamapps' / 'libraryfolders.vdf').write_text(
            '"libraryfolders"\n{\n' + ''.join(f'\t"{i}"\n\t{{\n\t\t"path"\t\t"{p}"\n\t}}\n'
                                             for i, p in enumerate((self.steam, self.lib2))) + '}\n', encoding='utf-8')
        write_latest(self.out, '0.6.0.26518', '100')
        return main, alt

    def test_newer_install_mid_update_is_pending(self):
        main, alt = self.libraries(alt_flags=1026, alt_updated=2000)
        code, msg = run(['check', '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_UPDATE_PENDING, msg)
        self.assertIn('STATUS: update-pending', msg)
        self.assertIn(str(alt), msg)

    def test_older_install_mid_update_is_ignored(self):
        main, alt = self.libraries(alt_flags=1026, alt_updated=500)
        code, msg = run(['check', '--out', str(self.out)])
        self.assertEqual(code, cli.CHECK_SAME, msg)
        self.assertIn(f'note: other installation {alt}', msg)
        self.assertIn(str(main), msg)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.v = Path(self._tmp.name) / 'v1'
        (self.v / 'schemas').mkdir(parents=True)
        (self.v / 'a.json').write_text('{"count": 0}\n', encoding='utf-8')
        (self.v / 'schemas' / 'a.schema.json').write_text('{}\n', encoding='utf-8')
        sha = lambda rel: hashlib.sha256((self.v / rel).read_bytes()).hexdigest()  # noqa: E731
        (self.v / 'manifest.json').write_text(json.dumps({'files': {'a.json': {'count': 0, 'sha256': sha('a.json')}},
                                                          'schemaHashes': {'a.schema.json': sha('schemas/a.schema.json')}}),
                                              encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def test_ok(self):
        code, msg = run(['verify', str(self.v)])
        self.assertEqual(code, 0, msg)
        self.assertIn('(2 files checked)', msg)

    def test_detects_changed_data(self):
        (self.v / 'a.json').write_text('{"count": 1}\n', encoding='utf-8')
        code, msg = run(['verify', str(self.v)])
        self.assertEqual(code, 1)
        self.assertIn('changed a.json', msg)

    def test_detects_changed_or_missing_schema(self):
        (self.v / 'schemas' / 'a.schema.json').write_text('{"type": "object"}\n', encoding='utf-8')
        code, msg = run(['verify', str(self.v)])
        self.assertEqual(code, 1)
        self.assertIn('changed schemas/a.schema.json', msg)
        (self.v / 'schemas' / 'a.schema.json').unlink()
        code, msg = run(['verify', str(self.v)])
        self.assertEqual(code, 1)
        self.assertIn('missing schemas/a.schema.json', msg)

    def test_extra_file_is_info_only(self):
        (self.v / 'stale.json').write_text('{}', encoding='utf-8')
        code, msg = run(['verify', str(self.v)])
        self.assertEqual(code, 0, msg)
        self.assertIn('not listed in manifest (info): stale.json', msg)


class NamingTests(unittest.TestCase):
    V = '0.6.0.26518'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def folder(self, name: str, build: str | None) -> None:
        (self.root / name).mkdir()
        (self.root / name / 'manifest.json').write_text(json.dumps({'steamBuildId': build}), encoding='utf-8')

    def latest(self, name: str | None) -> None:
        (self.root / 'index.json').write_text(json.dumps({'latest': name, 'versions': []}), encoding='utf-8')

    def name(self, build: str | None, overwrite: bool = False) -> tuple[str, list[str]]:
        w: list[str] = []
        return cli._version_dir_name(self.root, {'gameVersion': self.V, 'steamBuildId': build}, w, overwrite), w

    def refused(self, build: str | None) -> str:
        with self.assertRaises(cli.ExportRefused) as cm:
            self.name(build)
        self.assertEqual(cm.exception.code, cli.EXIT_OVERWRITE)
        return str(cm.exception)

    def test_new_folder(self):
        self.assertEqual(self.name('100'), (f'v{self.V}', []))

    def test_same_build_latest_is_replaced(self):
        self.folder(f'v{self.V}', '100')
        self.latest(f'v{self.V}')
        self.assertEqual(self.name('100'), (f'v{self.V}', []))

    def test_other_build_gets_b_suffix(self):
        self.folder(f'v{self.V}', '100')
        self.latest(f'v{self.V}')
        name, w = self.name('200')
        self.assertEqual(name, f'v{self.V}-b200')
        self.assertEqual(len(w), 1)
        self.assertTrue(w[0].startswith(f'source: v{self.V} already exists with Steam build 100; build 200'), w)
        # the -b folder, once it is the latest, is replaced by a re-export of the same build
        self.folder(f'v{self.V}-b200', '200')
        self.latest(f'v{self.V}-b200')
        self.assertEqual(self.name('200')[0], f'v{self.V}-b200')
        self.assertEqual(self.name('300')[0], f'v{self.V}-b300')

    def test_same_build_not_latest_is_refused(self):
        self.folder(f'v{self.V}', '100')
        self.folder(f'v{self.V}-b200', '200')
        self.latest(f'v{self.V}-b200')                  # rollback from the -b build to the base build
        self.assertIn('not the newest export', self.refused('100'))
        self.assertEqual(self.name('100', overwrite=True), (f'v{self.V}', []))
        (self.root / 'index.json').unlink()             # no index.json at all: not provably the latest either
        self.refused('100')

    def test_missing_build_id_is_refused(self):
        self.folder(f'v{self.V}', '100')
        self.latest(f'v{self.V}')
        self.assertIn('installed build is None', self.refused(None))      # --game path without app manifest
        self.assertEqual(self.name(None, overwrite=True)[0], f'v{self.V}')

    def test_existing_folder_without_build_id_is_refused(self):
        self.folder(f'v{self.V}', None)
        self.latest(f'v{self.V}')
        self.assertIn("Steam build None, installed build is '100'", self.refused('100'))


class SanityAndCodeHashTests(unittest.TestCase):
    def test_sanity(self):
        outputs = [('items.json', {'count': 100}), ('recipes.json', {'count': 0}), ('machines.json', {'count': 49}),
                   ('localization/de.json', {'count': 0}), ('template_fields.json', {'count': 0}),
                   ('research.json', {'count': 7})]
        prev = {'files': {'items.json': {'count': 200}, 'machines.json': {'count': 100}, 'research.json': {'count': 0}}}
        self.assertEqual(cli._sanity(outputs, prev, 'v1'), ['recipes.json is empty', 'machines.json: 100 -> 49 entries vs v1'])
        self.assertEqual(cli._sanity(outputs, None, None), ['recipes.json is empty'])
        self.assertEqual(cli._sanity([('items.json', {'count': 100})], prev, 'v1'), [])    # exactly half is allowed

    def test_code_warnings(self):
        old = {'Main.dll': 'a', 'FoundryNative.dll': 'n1', 'Channel3.dll': 'c'}
        new = {'Main.dll': 'a', 'FoundryNative.dll': 'n2', 'Assembly-CSharp.dll': 'x'}
        w = cli._code_warnings(new, old, 'v1')
        self.assertEqual([x.split(' - ')[0] for x in w], [
            'code-changed: Assembly-CSharp.dll is new (not hashed in v1)',
            'code-changed: Channel3.dll missing (present in v1)',
            'code-changed: FoundryNative.dll differs from v1'])
        self.assertIn('check_native_constants.py', w[2])
        self.assertEqual(cli._code_warnings(new, {}, None), [])          # first export / manifest without codeHashes
        self.assertIn('check_code_constants.py', cli._code_warnings({'Main.dll': 'b'}, old, 'v1')[-1])


if __name__ == '__main__':
    unittest.main()
