"""Game-folder discovery (foundry_export.steam) on fake Steam trees; smoke tests against the real install.
(The check exit codes are tested in test_cli.)"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import GAME, require_game  # noqa: F401  (puts extractor/ on sys.path)

from foundry_export import steam
from foundry_export.steam import (APP_ID, ENV_GAME_DIR, HINT_FILE, GameLocation, GameNotFound, find_game,
                                  library_folders, manifest_for_game_dir, parse_vdf, read_app_manifest, steam_roots)

LINUX = 'linux'


def write(p: Path, text: str = '') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def vdf_str(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def make_game(lib: Path, installdir: str = 'FOUNDRY', *, build: str | None = '100', state: int = 4,
              updated: int = 1000, version: str = '0.6.0.1') -> Path:
    """lib/steamapps/common/<installdir> with foundry_Data/StreamingAssets (+ appmanifest unless build is None)."""
    game = lib / 'steamapps' / 'common' / installdir
    (game / 'foundry_Data' / 'StreamingAssets').mkdir(parents=True)
    write(game / 'version.txt', version + '\n')
    if build is not None:
        write(lib / 'steamapps' / f'appmanifest_{APP_ID}.acf',
              f'"AppState"\n{{\n\t"appid"\t\t"{APP_ID}"\n\t"StateFlags"\t\t"{state}"\n'
              f'\t"installdir"\t\t"{installdir}"\n'
              f'\t"LastUpdated"\t\t"{updated}"\n\t"buildid"\t\t"{build}"\n\t"TargetBuildID"\t\t"0"\n'
              f'\t"InstalledDepots"\n\t{{\n\t\t"983872"\n\t\t{{\n\t\t\t"manifest"\t\t"1"\n\t\t}}\n\t}}\n}}\n')
    return game


def write_libraryfolders(steam_root: Path, libs: list[Path], *, old_format: bool = False,
                         where: str = 'steamapps') -> None:
    if old_format:
        body = '\t"TimeNextStatsReport"\t\t"1561832478"\n\t"ContentStatsID"\t\t"-158337411110787451"\n'
        body += ''.join(f'\t"{i}"\t\t{vdf_str(str(p))}\n' for i, p in enumerate(libs, 1))
        write(steam_root / where / 'libraryfolders.vdf', f'"LibraryFolders"\n{{\n{body}}}\n')
    else:
        body = ''.join(f'\t"{i}"\n\t{{\n\t\t"path"\t\t{vdf_str(str(p))}\n\t\t"label"\t\t""\n\t\t"apps"\n\t\t{{\n'
                       f'\t\t\t"{APP_ID}"\t\t"6010128092"\n\t\t}}\n\t}}\n' for i, p in enumerate([steam_root] + libs))
        write(steam_root / where / 'libraryfolders.vdf', f'"libraryfolders"\n{{\n{body}}}\n')


class VdfTest(unittest.TestCase):
    def test_nested_comments_escapes_unquoted(self):
        text = ('// header comment\n"AppState"\n{\n\t"appid"\t"983870" // trailing comment\n'
                '\tunquoted_key\tbare-value\n\t"quote"\t"say \\"hi\\""\n\t"Depots"\n\t{\n\t\t"1"\t{ "size" "5" }\n\t}\n'
                '\t"cond"\t"x" [$WIN32]\n\t"after"\t"y"\n}\n')
        d = parse_vdf(text)
        st = d['AppState']
        self.assertEqual(st['appid'], '983870')
        self.assertEqual(st['unquoted_key'], 'bare-value')
        self.assertEqual(st['quote'], 'say "hi"')
        self.assertEqual(st['Depots'], {'1': {'size': '5'}})
        self.assertEqual(st['cond'], 'x')
        self.assertEqual(st['after'], 'y')

    def test_windows_escaped_backslash_paths(self):
        d = parse_vdf('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n'
                      '\t"1"\t\t"D:\\\\SteamLibrary"\n}\n')
        self.assertEqual(d['libraryfolders']['0']['path'], r'C:\Program Files (x86)\Steam')
        self.assertEqual(d['libraryfolders']['1'], r'D:\SteamLibrary')

    def test_tolerates_broken_input(self):
        self.assertEqual(parse_vdf(''), {})
        self.assertEqual(parse_vdf('"a" { "b" "c"'), {'a': {'b': 'c'}})          # unclosed block
        self.assertEqual(parse_vdf('} "a" "1" "dangling"'), {'a': '1'})          # stray brace, dangling key
        self.assertEqual(parse_vdf('"a" { "x" "1" } "a" { "y" "2" }'), {'a': {'x': '1', 'y': '2'}})   # merged

    def test_real_manifest_shape(self):
        with tempfile.TemporaryDirectory() as td:
            make_game(Path(td), build='23077581', state=4, updated=1793545632)
            st = read_app_manifest(Path(td) / 'steamapps' / f'appmanifest_{APP_ID}.acf')
        self.assertEqual((st['buildid'], st['StateFlags'], st['installdir']), ('23077581', '4', 'FOUNDRY'))
        self.assertEqual(st['InstalledDepots'], {'983872': {'manifest': '1'}})


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.steam = self.home / '.local' / 'share' / 'Steam'

    def tearDown(self):
        self._td.cleanup()

    def find(self, explicit=None, env=None, **kw) -> GameLocation:
        return find_game(explicit, env=env or {}, home=self.home, platform=LINUX, **kw)

    def test_single_root(self):
        game = make_game(self.steam, build='23077581')
        loc = self.find()
        self.assertEqual(loc.root, game)
        self.assertEqual(loc.source, 'steam-library')
        self.assertEqual(loc.build_id, '23077581')
        self.assertEqual((loc.state_flags, loc.installdir, loc.last_updated), (4, 'FOUNDRY', 1000))
        self.assertEqual(loc.library, self.steam)
        self.assertEqual(loc.manifest, self.steam / 'steamapps' / f'appmanifest_{APP_ID}.acf')
        self.assertFalse(loc.update_pending)
        self.assertEqual(loc.alternatives, [])
        self.assertEqual(loc.game_version, '0.6.0.1')
        self.assertEqual(loc.as_dict()['steamBuildId'], '23077581')

    def test_second_library_new_format(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        lib2 = self.tmp / 'games' / 'SteamLibrary'
        game = make_game(lib2, build='7')
        write_libraryfolders(self.steam, [lib2])
        self.assertEqual(library_folders(self.steam), [self.steam, lib2])
        loc = self.find()
        self.assertEqual((loc.root, loc.library, loc.build_id), (game, lib2, '7'))

    def test_old_format_libraryfolders(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        lib2 = self.tmp / 'old lib'
        game = make_game(lib2, build='8')
        write_libraryfolders(self.steam, [lib2, self.tmp / 'unmounted'], old_format=True)
        self.assertEqual(library_folders(self.steam), [self.steam, lib2])    # stats keys and missing paths ignored
        self.assertEqual(self.find().root, game)

    def test_config_libraryfolders(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        lib2 = self.tmp / 'cfglib'
        game = make_game(lib2)
        write_libraryfolders(self.steam, [lib2], where='config')
        self.assertEqual(self.find().root, game)

    def test_flatpak_root(self):
        flat = self.home / '.var' / 'app' / 'com.valvesoftware.Steam' / '.local' / 'share' / 'Steam'
        game = make_game(flat, build='9')
        self.assertEqual(steam_roots({}, self.home, LINUX), [flat])
        loc = self.find()
        self.assertEqual((loc.root, loc.build_id), (game, '9'))

    def test_snap_and_env_roots(self):
        snap = self.home / 'snap' / 'steam' / 'common' / '.local' / 'share' / 'Steam'
        custom = self.tmp / 'custom_steam'
        snap.mkdir(parents=True)
        custom.mkdir()
        self.assertEqual(steam_roots({'STEAM_DIR': str(custom)}, self.home, LINUX), [custom, snap])

    def test_roots_deduplicated_by_resolved_path(self):
        self.steam.mkdir(parents=True)
        try:
            (self.home / '.steam').mkdir()
            os.symlink(self.steam, self.home / '.steam' / 'steam', target_is_directory=True)
            os.symlink(self.steam, self.home / '.steam' / 'root', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks not available')
        self.assertEqual(steam_roots({}, self.home, LINUX), [self.steam])

    def test_macos_and_windows_roots(self):
        mac = self.home / 'Library' / 'Application Support' / 'Steam'
        mac.mkdir(parents=True)
        self.assertEqual(steam_roots({}, self.home, 'darwin'), [mac])
        reg, pf = self.tmp / 'regsteam', self.tmp / 'PF86'
        reg.mkdir()
        (pf / 'Steam').mkdir(parents=True)
        with mock.patch.object(steam, '_registry_steam_paths', return_value=[str(reg)]):
            self.assertEqual(steam_roots({'ProgramFiles(x86)': str(pf)}, self.home, 'win32'), [reg, pf / 'Steam'])

    def test_explicit_beats_steam(self):
        make_game(self.steam)
        other = make_game(self.tmp / 'copy', build=None)
        loc = self.find(str(other))
        self.assertEqual((loc.root, loc.source), (other, 'argument'))

    def test_explicit_exe_or_data_dir_accepted(self):
        game = make_game(self.steam)
        write(game / 'Foundry.exe')
        self.assertEqual(self.find(game / 'Foundry.exe').root, game)
        self.assertEqual(self.find(game / 'foundry_Data').root, game)

    def test_invalid_explicit_raises(self):
        make_game(self.steam)
        bad = self.tmp / 'nothing_here'
        bad.mkdir()
        with self.assertRaises(GameNotFound) as cm:
            self.find(str(bad))
        self.assertIn(str(bad), str(cm.exception))
        self.assertIn('no *_Data/StreamingAssets', str(cm.exception))
        with self.assertRaises(GameNotFound):
            self.find(str(self.tmp / 'missing'))

    def test_env_override(self):
        make_game(self.steam)
        other = make_game(self.tmp / 'envlib', build='55')
        loc = self.find(env={'FOUNDRY_GAME_DIR': str(other)})
        self.assertEqual((loc.root, loc.source, loc.build_id), (other, 'env', '55'))
        self.assertEqual(self.find(str(self.steam / 'steamapps' / 'common' / 'FOUNDRY'),
                                   env={'FOUNDRY_GAME_DIR': str(other)}).source, 'argument')
        with self.assertRaises(GameNotFound) as cm:
            self.find(env={'FOUNDRY_GAME_DIR': str(self.tmp / 'missing')})
        self.assertIn('env FOUNDRY_GAME_DIR', str(cm.exception))

    def test_hint_file_fallback(self):
        game = make_game(self.tmp / 'elsewhere', build=None)
        hint = write(self.tmp / 'game_path.txt', f'\n{game}\n')
        loc = self.find(hint_file=hint)
        self.assertEqual((loc.root, loc.source, loc.manifest, loc.build_id), (game, 'hint-file', None, None))
        self.assertFalse(loc.update_pending)

    def test_steam_beats_hint_file(self):
        game = make_game(self.steam)
        hint = write(self.tmp / 'game_path.txt', str(make_game(self.tmp / 'elsewhere', build=None)))
        self.assertEqual(self.find(hint_file=hint).root, game)

    def test_not_found_lists_searched_places(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        hint = write(self.tmp / 'game_path.txt', str(self.tmp / 'gone'))
        with self.assertRaises(GameNotFound) as cm:
            self.find(hint_file=hint)
        msg = str(cm.exception)
        self.assertIn(f'Steam library {self.steam}: no appmanifest_{APP_ID}.acf', msg)
        self.assertIn(str(self.home / '.steam' / 'steam'), msg)                       # missing root candidates
        self.assertIn(str(self.home / 'snap' / 'steam' / 'common' / '.local' / 'share' / 'Steam'), msg)
        self.assertIn(f'hint file {hint}', msg)
        self.assertIn(str(self.tmp / 'gone'), msg)
        self.assertGreaterEqual(len(cm.exception.searched), 7)

    def test_manifest_without_game_folder_reported(self):
        make_game(self.steam)
        game = self.steam / 'steamapps' / 'common' / 'FOUNDRY'
        (game / 'foundry_Data' / 'StreamingAssets').rmdir()
        with self.assertRaises(GameNotFound) as cm:
            self.find()
        self.assertIn('found but', str(cm.exception))

    def test_two_installs_prefers_fully_installed_then_newest(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        a, b, c = self.tmp / 'a', self.tmp / 'b', self.tmp / 'c'
        ga = make_game(a, build='1', state=4, updated=100)
        gb = make_game(b, build='2', state=4, updated=200)        # newest fully installed
        gc = make_game(c, build='3', state=6, updated=300)        # newer but update pending
        write_libraryfolders(self.steam, [a, b, c])
        loc = self.find()
        self.assertEqual((loc.root, loc.build_id), (gb, '2'))
        self.assertEqual(sorted(loc.alternatives), sorted([ga, gc]))
        self.assertFalse(loc.update_pending)
        # the full locations of the others (cli check uses them to spot a newer install Steam is still updating)
        self.assertEqual([a.root for a in loc.alternative_locations], loc.alternatives)
        alt = {a.root: (a.build_id, a.update_pending, a.last_updated) for a in loc.alternative_locations}
        self.assertEqual(alt, {ga: ('1', False, 100), gc: ('3', True, 300)})

    def test_update_pending(self):
        make_game(self.steam, build='5', state=6)
        loc = self.find()
        self.assertEqual(loc.state_flags, 6)
        self.assertTrue(loc.update_pending)

    def test_missing_manifest_build_none(self):
        game = make_game(self.tmp / 'nosteam', build=None)
        loc = self.find(game)
        self.assertEqual((loc.manifest, loc.build_id, loc.state_flags, loc.library), (None, None, None, None))
        self.assertFalse(loc.update_pending)
        self.assertIsNone(manifest_for_game_dir(game, roots=[]))

    def test_leftover_folder_without_manifest_ranked_last(self):
        (self.steam / 'steamapps').mkdir(parents=True)
        lib2 = self.tmp / 'lib2'
        leftover = make_game(self.steam, build=None)
        real = make_game(lib2, build='42', state=4)
        write_libraryfolders(self.steam, [lib2])
        loc = self.find()
        self.assertEqual((loc.root, loc.build_id, loc.alternatives), (real, '42', [leftover]))

    def test_manifest_for_symlinked_game_dir(self):
        game = make_game(self.steam, build='77')
        link = self.tmp / 'link_to_game'
        try:
            os.symlink(game, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks not available')
        self.assertEqual(manifest_for_game_dir(link, roots=[]), self.steam / 'steamapps' / f'appmanifest_{APP_ID}.acf')
        self.assertEqual(self.find(link).build_id, '77')

    def test_manifest_for_game_dir_checks_installdir(self):
        make_game(self.steam, 'FOUNDRY', build='1')
        other = self.steam / 'steamapps' / 'common' / 'SomeOtherGame'
        (other / 'x_Data' / 'StreamingAssets').mkdir(parents=True)
        self.assertIsNone(manifest_for_game_dir(other, roots=[]))


class SmokeTest(unittest.TestCase):
    """The real installation, found the same way the extractor finds it (cli._find: find_game(hint_file=HINT_FILE))."""

    @require_game
    def test_finds_installed_game(self):
        loc = find_game(hint_file=HINT_FILE)
        self.assertEqual(loc.root.resolve(), GAME.resolve())
        manifest = manifest_for_game_dir(loc.root)
        if manifest is None:
            self.assertIsNone(loc.build_id)
            self.skipTest(f'{loc.root} is not inside a Steam library (no appmanifest_{APP_ID}.acf) - build id not checked')
        self.assertEqual(loc.manifest.resolve(), manifest.resolve())
        self.assertEqual(loc.build_id, read_app_manifest(manifest)['buildid'])   # '23077581' for game 0.6.0.26518
        self.assertRegex(loc.build_id, r'^\d+$')

    @require_game
    def test_steam_libraries_find_the_game(self):
        """Without FOUNDRY_GAME_DIR the Steam libraries alone find the installation (unless it lives elsewhere)."""
        via = find_game(hint_file=HINT_FILE).source
        if via == 'hint-file':
            self.skipTest(f'game found only via game_path.txt ({GAME}), not in a registered Steam library')
        env = {k: v for k, v in os.environ.items() if k != ENV_GAME_DIR}
        try:
            loc = find_game(env=env)
        except GameNotFound as e:
            if via == 'env':
                self.skipTest(f'{ENV_GAME_DIR}={os.environ[ENV_GAME_DIR]} is outside the registered Steam libraries, '
                              f'and they hold no FOUNDRY install - Steam discovery not compared ({e})')
            raise
        if via == 'env' and loc.root.resolve() != GAME.resolve():
            self.skipTest(f'{ENV_GAME_DIR}={os.environ[ENV_GAME_DIR]} points to an install outside the registered Steam '
                          f'libraries (they hold {loc.root}) - Steam discovery not compared')
        self.assertEqual(loc.source, 'steam-library')
        self.assertEqual(loc.root.resolve(), GAME.resolve())
        self.assertIsNotNone(loc.manifest)
        self.assertRegex(loc.build_id or '', r'^\d+$')


if __name__ == '__main__':
    unittest.main()
