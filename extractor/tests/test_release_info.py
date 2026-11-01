"""Title and description of a game version (export --title/--description, kept from index.json otherwise).

Unit: cli._release_info with and without index.json. With the game: exports of fake game folders write both fields into
manifest.json, index.json and latest.json; a second Steam build of the same version keeps them; without any source
they are null and the console says so.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _util import GAME, describe, make_fake_game, parallel, require_game, run_export, slow

from foundry_export import cli


def read_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def write_index(root: Path, versions: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'index.json').write_text(json.dumps({'latest': versions[-1]['version'] if versions else None,
                                                 'versions': versions}), encoding='utf-8')


class ReleaseInfoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'out'

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_index(self):
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', None, None), (None, None))
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', 'Update 4', 'Rails & Reactors'),
                         ('Update 4', 'Rails & Reactors'))

    def test_kept_from_index_for_the_same_game_version(self):
        write_index(self.root, [
            {'version': 'v0.6.0.1', 'gameVersion': '0.6.0.1', 'title': 'Update 3', 'description': 'Old'},
            {'version': 'v0.6.0.2', 'gameVersion': '0.6.0.2', 'title': 'Update 4', 'description': 'Rails & Reactors'},
            {'version': 'v0.6.0.2-b2', 'gameVersion': '0.6.0.2', 'title': 'Update 4', 'description': 'Hotfix'},
        ])
        self.assertEqual(cli._release_info(self.root, '0.6.0.2', None, None), ('Update 4', 'Hotfix'))   # newest entry
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', None, None), ('Update 3', 'Old'))
        self.assertEqual(cli._release_info(self.root, '0.6.0.3', None, None), (None, None))           # other version
        self.assertEqual(cli._release_info(self.root, '0.6.0.2', 'Update 5', None), ('Update 5', 'Hotfix'))
        self.assertEqual(cli._release_info(self.root, '0.6.0.2', '', ''), (None, None))                 # cleared

    def test_entries_without_fields_and_broken_index(self):
        write_index(self.root, [{'version': 'v0.6.0.1', 'gameVersion': '0.6.0.1', 'generatedAt': 'x'}])
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', None, None), (None, None))
        (self.root / 'index.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', None, None), (None, None))
        (self.root / 'index.json').write_text('[1, 2]', encoding='utf-8')
        self.assertEqual(cli._release_info(self.root, '0.6.0.1', 'T', None), ('T', None))

    def test_manifest_schema_accepts_null_and_text(self):
        schema = cli.SCHEMAS['manifest']
        for field in ('title', 'description'):
            self.assertIn(field, schema['required'])
            self.assertEqual(schema['properties'][field], {'type': ['string', 'null']})


@require_game
@slow
class ReleaseInfoExportTests(unittest.TestCase):
    BUILD_A, BUILD_B = '900000011', '900000012'

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        t = Path(cls._tmp.name)
        try:
            cls.version = (Path(GAME) / 'version.txt').read_text(encoding='utf-8').strip()
            game_a = make_fake_game(t / 'game_a', cls.BUILD_A)
            game_b = make_fake_game(t / 'game_b', cls.BUILD_B)
            cls.out_titled, cls.out_plain = t / 'out_titled', t / 'out_plain'
            r = parallel({
                'titled': lambda: run_export(game_a, cls.out_titled, '--title', 'Update 4',
                                             '--description', 'Rails & Reactors'),
                'plain': lambda: run_export(game_a, cls.out_plain),
            })
            r['b'] = run_export(game_b, cls.out_titled)          # second Steam build, no options: kept from index.json
            cls.r = r
        except BaseException:
            cls._tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_given_values_everywhere(self):
        self.assertEqual(self.r['titled'].returncode, 0, describe(self.r['titled']))
        vname = f'v{self.version}'
        manifest = read_json(self.out_titled / vname / 'manifest.json')
        self.assertEqual((manifest['title'], manifest['description']), ('Update 4', 'Rails & Reactors'))
        self.assertEqual(list(manifest)[:6], ['schemaVersion', 'gameVersion', 'steamBuildId', 'steamBranch', 'title',
                                              'description'])
        entry = next(v for v in read_json(self.out_titled / 'index.json')['versions'] if v['version'] == vname)
        self.assertEqual(list(entry), ['version', 'gameVersion', 'steamBuildId', 'title', 'description', 'generatedAt'])
        self.assertEqual((entry['title'], entry['description']), ('Update 4', 'Rails & Reactors'))
        self.assertNotIn('note: no title/description', self.r['titled'].stdout)

    def test_second_build_keeps_values(self):
        self.assertEqual(self.r['b'].returncode, 0, describe(self.r['b']))
        bname = f'v{self.version}-b{self.BUILD_B}'
        manifest = read_json(self.out_titled / bname / 'manifest.json')
        self.assertEqual((manifest['title'], manifest['description']), ('Update 4', 'Rails & Reactors'))
        latest = read_json(self.out_titled / 'latest.json')
        self.assertEqual((latest['version'], latest['title'], latest['description']),
                         (bname, 'Update 4', 'Rails & Reactors'))
        self.assertEqual([(v['version'], v['title']) for v in read_json(self.out_titled / 'index.json')['versions']],
                         [(f'v{self.version}', 'Update 4'), (bname, 'Update 4')])

    def test_without_source_null_and_note(self):
        r = self.r['plain']
        self.assertEqual(r.returncode, 0, describe(r))
        manifest = read_json(self.out_plain / f'v{self.version}' / 'manifest.json')
        self.assertEqual((manifest['title'], manifest['description']), (None, None))
        latest = read_json(self.out_plain / 'latest.json')
        self.assertEqual((latest['title'], latest['description']), (None, None))
        self.assertIn(f'note: no title/description for {self.version}', r.stdout)


if __name__ == '__main__':
    unittest.main()
