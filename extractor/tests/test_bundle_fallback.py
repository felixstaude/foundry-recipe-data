"""Template fallback: FoundryTemplates read from foundry_main_bundle instead of StreamingAssets/Templates.

These tests compare the two template sources directly (two slow ones are skipped with FOUNDRY_SKIP_SLOW=1).
Full exports from fake game folders without / with an emptied or modified Templates dump, compared file by file with
the plain export, are in test_export.FakeGameExportTests.

Known, documented differences between the YAML dump and the bundle (normalised in the source comparison):
  * references: the dump writes '<asset path or template identifier>|<guid>', the bundle has no guids -> '<path>|'
  * strings the dump has as null but the bundle as '' (editor assets saved before the field existed)
"""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from _util import GAME, require_game, slow

from foundry_export.bundle_templates import TABLE_FILE, TypeTable, net_single, yaml_scalar
from foundry_export.game import locate
from foundry_export.sources import BundleTemplateSource, YamlTemplateSource
from foundry_export.unity_bundle import lz4_block_decompress

NINE = ['ItemTemplate', 'ElementTemplate', 'CraftingTag', 'CraftingRecipe', 'BuildableObjectTemplate',
        'ResearchTemplate', 'ExplorationUnlockTemplate', 'AssemblyLineObjectTemplate',
        'AssemblyLineProducerActionTemplate']


def _diffs(a, b, path=''):
    """Differences between a YAML-dump value and a bundle value, minus the documented artifacts."""
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            return [f'{path}: keys {sorted(set(a) ^ set(b)) or "order"}']
        return [d for k in a for d in _diffs(a[k], b[k], f'{path}.{k}')]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f'{path}: length {len(a)} != {len(b)}']
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _diffs(x, y, f'{path}[{i}]')]
    if isinstance(a, str) and isinstance(b, str) and '|' in a and b.endswith('|') and a.split('|')[0] == b[:-1]:
        return []  # reference without guid
    if a is None and b == '':
        return []  # stale editor asset
    if type(a) is not type(b) or a != b:
        return [f'{path}: {a!r} != {b!r}']
    return []


class ScalarTests(unittest.TestCase):
    def test_yaml_scalar_matches_pyyaml(self):
        import yaml
        for s in ['', 'abc', 'True', 'False', 'Off', 'yes', '12', '-3', '1.5', '1E-05', '1.5E-05', 'NaN', '~', 'null',
                  'a: b', 'x"y', 'back\\slash', ' lead', 'trail ', 'A|B', '[x]', 'a #b', '0x1A', '2001-12-14',
                  '-', '#c']:
            if s == '' or any(c in s for c in '"\\\n\r:') or s != s.strip():
                text = '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
            else:
                text = s
            try:
                expected = yaml.load('k: ' + text + '\n', Loader=yaml.SafeLoader)['k']
            except yaml.YAMLError:
                expected = s  # invalid as plain YAML: kept as text
            self.assertEqual(yaml_scalar(s), expected, s)

    def test_net_single(self):
        f32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]  # noqa: E731
        self.assertEqual(net_single(f32(0.38268346)), '0.3826835')
        self.assertEqual(net_single(f32(0.1)), '0.1')
        self.assertEqual(net_single(1.0), '1')
        self.assertEqual(net_single(f32(1e-05)), '1E-05')
        self.assertEqual(net_single(f32(3.4028235e38)), '3.402823E+38')
        self.assertEqual(net_single(f32(-2.5)), '-2.5')

    def test_lz4_overlapping_match(self):
        # literals 'ab', then a 10 byte match at offset 2 (overlapping copy)
        self.assertEqual(lz4_block_decompress(bytes([0x26]) + b'ab' + bytes([2, 0]), 12), b'ab' * 6)


class YamlRepairTest(unittest.TestCase):
    def test_plain_dash_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'PlanetTemplate'
            folder.mkdir()
            (folder / 'p.yaml').write_text('PlanetTemplate:\n  p:\n    planetInfo: -\n    minLevel: 1\n',
                                           encoding='utf-8')
            warnings = []
            src = YamlTemplateSource(Path(tmp), warnings)
            self.assertEqual(src.load('PlanetTemplate'), {'p': {'planetInfo': '-', 'minLevel': 1, 'identifier': 'p'}})
            self.assertEqual(src.type_names(), ['PlanetTemplate'])
            self.assertTrue(warnings and warnings[0].startswith('source: Templates/PlanetTemplate/p.yaml line 3'))


@require_game
class SourceComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gp = locate(GAME)
        if not gp.templates.is_dir():
            raise unittest.SkipTest('game has no StreamingAssets/Templates to compare against')
        cls.gp = gp
        cls.yaml = YamlTemplateSource(gp.templates, [])
        cls.bundle_warnings = []
        cls.bundle = BundleTemplateSource(gp, cls.bundle_warnings)

    def _compare(self, src_a, src_b, types, values=True):
        for t in types:
            a, b = src_a.load(t), src_b.load(t)
            self.assertEqual(list(a), list(b), f'{t}: identifiers/order')
            for ident in a:
                if values:
                    self.assertEqual(_diffs(a[ident], b[ident]), [], f'{t} {ident}')
                else:
                    self.assertEqual(set(a[ident]), set(b[ident]), f'{t} {ident}: field names')

    def test_type_names(self):
        self.assertEqual(self.yaml.type_names(), self.bundle.type_names())

    def test_nine_types_equal(self):
        self._compare(self.yaml, self.bundle, NINE)
        self.assertEqual(self.bundle_warnings, [])

    @slow
    def test_all_types_identifiers_and_fields(self):
        self._compare(self.yaml, self.bundle, self.yaml.type_names())

    def test_committed_table_is_current(self):
        table = TypeTable.from_json(TABLE_FILE)
        version = (GAME / 'version.txt').read_text(encoding='utf-8').strip()
        if table.game_version != version:
            self.skipTest(f'committed table is for {table.game_version}, game is {version} '
                          f'(regenerate: python3 extractor/tools/gen_enums.py <game_dir>)')
        live = TypeTable.from_managed(self.gp.data / 'Managed')
        self.assertEqual(json.loads(json.dumps(live.types)), table.types)

    @slow
    def test_table_mode_equals_dll_mode(self):
        from foundry_export.bundle_templates import BundleTemplates
        version = (GAME / 'version.txt').read_text(encoding='utf-8').strip()
        warnings = []
        snap = BundleTemplates(self.bundle.bundle, table=TypeTable.from_json(TABLE_FILE), warnings=warnings,
                               game_version=version)
        for t in NINE:
            self.assertEqual(snap.load(t), self.bundle.load(t), t)
        self.assertEqual(warnings, [])


if __name__ == '__main__':
    unittest.main()
