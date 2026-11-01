"""Tests for foundry_export.dll_types (ECMA-335 type inventory + baseline diff)."""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from _util import GAME, require_game

from foundry_export import dll_types as dt

OLD = [
    '# header comment, ignored',
    'Main\tC3.FoundryTemplate\tUnityEngine.ScriptableObject',
    'Main\tItemTemplate\tC3.FoundryTemplate',
    'Main\tGoneTemplate\tC3.FoundryTemplate',
    'Main\tHelper\tSystem.Object',
    'Main\tIFoo\t',
    'Channel3\tC3.Util\tSystem.Object',
]
NEW = [
    'Main\tC3.FoundryTemplate\tUnityEngine.ScriptableObject',
    'Main\tItemTemplate\tC3.FoundryTemplate',
    'Main\tBaseTpl`1\tC3.FoundryTemplate',
    'Main\tFancyTemplate\tBaseTpl`1<System.Int32>',  # generic base, transitive
    'Main\tHelper\tItemTemplate',                    # base change makes it a template
    'Main\tIFoo\t',
    'Main\tOuter/Inner\tSystem.Object',
    'Channel3\tC3.Util\tSystem.Object',
]


class SyntheticTests(unittest.TestCase):
    def test_diff_snapshot(self):
        d = dt.diff_snapshot(OLD, NEW)
        self.assertEqual(d['added'], ['Main\tBaseTpl`1\tC3.FoundryTemplate',
                                      'Main\tFancyTemplate\tBaseTpl`1<System.Int32>', 'Main\tOuter/Inner\tSystem.Object'])
        self.assertEqual(d['removed'], ['Main\tGoneTemplate\tC3.FoundryTemplate'])
        self.assertEqual(d['changed_base'], ['Main\tHelper\tSystem.Object -> ItemTemplate'])
        self.assertEqual(d['new_templates'], ['BaseTpl`1', 'FancyTemplate', 'Helper'])
        self.assertEqual(d['removed_templates'], ['GoneTemplate'])
        self.assertEqual(dt.diff_snapshot(NEW, NEW), {k: [] for k in d})

    def test_template_subclasses(self):
        self.assertEqual(dt.template_subclasses(NEW), {'ItemTemplate', 'BaseTpl`1', 'FancyTemplate', 'Helper'})
        infos = [dt.TypeInfo('C3', 'FoundryTemplate', 'UnityEngine.ScriptableObject', False, False),
                 dt.TypeInfo('', 'A', 'C3.FoundryTemplate', False, False),
                 dt.TypeInfo('N', 'B', 'A', False, False),
                 dt.TypeInfo('', 'Loop1', 'Loop2', False, False), dt.TypeInfo('', 'Loop2', 'Loop1', False, False)]
        self.assertEqual(dt.template_subclasses(infos), {'A', 'N.B'})

    def test_missing_managed_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'b.txt'
            base.write_text('Main\tX\tSystem.Object\n', encoding='utf-8')
            w = dt.warnings_for(Path(tmp) / 'foundry_Data' / 'Managed', base)
            self.assertEqual(w, ['dll-types: foundry_Data/Managed not found (IL2CPP build?) - class check skipped'])
            self.assertEqual(dt.warnings_for(tmp, Path(tmp) / 'nope.txt'),
                             ['dll-types: baseline nope.txt not found - class check skipped'])

    def test_committed_baselines_agree(self):
        """'export baseline' writes baseline/dll_types.txt, baseline/known_templates.json and data/managed_types.json
        together, with the game version passed explicitly - all three must name the same version."""
        from foundry_export.bundle_templates import TABLE_FILE, TypeTable
        from foundry_export.checks import load_baseline
        _lines, ver = dt.read_baseline()
        self.assertIsNotNone(ver, 'baseline/dll_types.txt header has no game version')
        self.assertEqual(ver, load_baseline()['gameVersion'], 'dll_types.txt vs known_templates.json')
        self.assertEqual(ver, TypeTable.from_json(TABLE_FILE).game_version, 'dll_types.txt vs data/managed_types.json')

    def test_not_a_pe_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'x.dll'
            p.write_bytes(b'not a dll' * 20)
            with self.assertRaises(ValueError):
                dt.list_types(p)


@require_game
class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.managed = dt.managed_dir_of(GAME)
        t = time.perf_counter()
        cls.lines = dt.snapshot(cls.managed)
        cls.seconds = time.perf_counter() - t

    def test_main_dll(self):
        types = {t.full_name: t for t in dt.list_types(self.managed / 'Main.dll')}
        self.assertEqual(types['ItemTemplate'].base, 'C3.FoundryTemplate')
        self.assertEqual(types['C3.FoundryTemplate'].base, 'UnityEngine.ScriptableObject')
        self.assertTrue(types['ItemTemplate/ItemTemplateFlags'].is_enum)
        self.assertTrue(types['IDataSignal'].is_interface)
        self.assertIsNone(types['IDataSignal'].base)
        self.assertGreater(len(types), 2000)

    def test_templates_cover_template_folders(self):
        tpl = {n.rsplit('.', 1)[-1] for n in dt.template_subclasses(self.lines)}
        folders = {p.name for p in (self.managed.parent / 'StreamingAssets' / 'Templates').iterdir() if p.is_dir()}
        self.assertTrue(folders, 'no template folders found')
        self.assertEqual(folders - tpl, set())
        # types TemplateExporter skips on purpose
        self.assertLessEqual({'TrainTrackTemplate', 'TrainTrackSetTemplate', 'SplineDataContainer',
                              'TrainTrackSplineDataContainer'}, tpl)

    def test_baseline_matches_installed_game(self):
        lines, ver = dt.read_baseline()
        game_version = (GAME / 'version.txt').read_text(encoding='utf-8').strip()
        hint = 'review the dll-types warnings of the export, then run `python3 extractor/export baseline` (UPDATE.md step d)'
        self.assertEqual(ver, game_version, f'baseline/dll_types.txt was accepted for game {ver}, installed is '
                                            f'{game_version}: {hint}')
        self.assertEqual(dt.warnings_for(self.managed), [])
        self.assertEqual(lines, self.lines, hint)

    def test_fast(self):
        # generous bound against a pathological slowdown only (typically well under 2 s)
        self.assertLess(self.seconds, 30.0)

    def test_write_baseline_version_header(self):
        # 'export baseline' passes the version explicitly; without it the version.txt next to *_Data is used, which is
        # wrong for a symlinked Managed folder (fake/symlinked installs)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'foundry_Data').mkdir()
            (tmp / 'version.txt').write_text('1.2.3\n', encoding='utf-8')
            link = tmp / 'foundry_Data' / 'Managed'
            link.symlink_to(self.managed.resolve(), target_is_directory=True)
            self.assertEqual(dt.read_baseline(dt.write_baseline(link, tmp / 'a.txt'))[1], '1.2.3')
            lines, ver = dt.read_baseline(dt.write_baseline(link, tmp / 'b.txt', game_version='9.9.9.1'))
            self.assertEqual((ver, lines), ('9.9.9.1', self.lines))

    def test_write_baseline_and_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = dt.write_baseline(self.managed, Path(tmp) / 'b.txt')
            self.assertEqual(dt.read_baseline(p)[0], self.lines)
            doctored = [x for x in self.lines if x != 'Main\tItemTemplate\tC3.FoundryTemplate']
            doctored.append('Main\tGoneThing\tSystem.Object')
            p.write_text('\n'.join(doctored) + '\n', encoding='utf-8')
            self.assertEqual(dt.warnings_for(self.managed, p),
                             ['dll-types: Main +1 / -1 types vs baseline (new FoundryTemplate subclasses: ItemTemplate)'])
            # only Channel3.dll present -> the others reported as missing, Channel3 compared (unchanged)
            managed = Path(tmp) / 'foundry_Data' / 'Managed'
            managed.mkdir(parents=True)
            shutil.copy(self.managed / 'Channel3.dll', managed / 'Channel3.dll')
            self.assertEqual(sorted(dt.warnings_for(managed, p)),
                             [f'dll-types: foundry_Data/Managed/{a}.dll not found (IL2CPP build?) - class check skipped'
                              for a in ('Assembly-CSharp', 'Main')])


if __name__ == '__main__':
    unittest.main()
