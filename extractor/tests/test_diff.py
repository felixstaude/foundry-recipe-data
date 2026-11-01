"""Version diff -> CHANGES.md (foundry_export.diff).

Synthetic mini exports test the diff rules without the game; the real-data tests copy a reference export
(env FOUNDRY_REF_EXPORT, else the repo's committed out/<latest>, else a fresh export of the installed game) to a temp
dir, mutate the copy and check the rendered markdown. out/ itself is never modified."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _util import EXTRACTOR, GAME, REPO  # (puts extractor/ on sys.path)

from foundry_export import diff as diffmod
from foundry_export.diff import COLLAPSE, diff_versions, main, render_changes_md

BASELINE = EXTRACTOR / 'foundry_export' / 'baseline' / 'known_templates.json'
MISMATCH_WARNING = ('source: Templates dump differs from foundry_main_bundle (see source-mismatch) - data taken from '
                    'foundry_main_bundle, which is what the game loads')
FALLBACK_WARNING = ('source: StreamingAssets/Templates missing - templates read from foundry_main_bundle (fallback)')

LIST_KEYS = {'items.json': 'items', 'elements.json': 'elements', 'crafting_tags.json': 'tags', 'recipes.json': 'recipes',
             'machines.json': 'machines', 'research.json': 'research', 'assembly_line.json': 'objects'}


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def copy_export(src: Path, dst: Path) -> Path:
    """Writable copy of an export folder (the reference export may be read-only)."""
    shutil.copytree(src, dst, copy_function=shutil.copyfile, ignore=shutil.ignore_patterns('CHANGES.md'))
    for p in [dst, *dst.rglob('*')]:
        p.chmod(0o755 if p.is_dir() else 0o644)
    return dst


def section(md: str, title: str) -> str:
    """Text of the '## <title>' section up to the next '## ' heading."""
    start = md.index(f'\n## {title}\n')
    end = md.find('\n## ', start + 1)
    return md[start:end if end != -1 else len(md)]


def mini_export(vdir: Path, *, items=(), recipes=(), machines=(), research=(), exploration=(), al_objects=(),
                al_machines=(), elements=(), tags=(), warnings=(), strings=None, loc=None, manifest_extra=None,
                template_fields=None, skip=(), categories=None, creative_categories=None) -> Path:
    """Minimal export folder in out/v<version> layout (only the fields the tests need). loc: {lang: strings}
    (default: en.json with `strings`); template_fields: {type: [field paths]} -> template_fields.json;
    categories / creative_categories: items.json categories / creativeModeCategories (None: key missing, as before 1.2)."""
    ver = vdir.name.lstrip('v')
    head = {'gameVersion': ver, 'steamBuildId': '1'}
    cats = {k: list(v) for k, v in (('categories', categories), ('creativeModeCategories', creative_categories))
            if v is not None}
    docs = {'items.json': {'items': list(items), **cats}, 'elements.json': {'elements': list(elements)},
            'crafting_tags.json': {'tags': list(tags)}, 'recipes.json': {'recipes': list(recipes)},
            'machines.json': {'machines': list(machines)},
            'research.json': {'research': list(research), 'explorationUnlocks': list(exploration)},
            'assembly_line.json': {'constants': {'ticksPerSecond': 60}, 'machines': list(al_machines),
                                   'objects': list(al_objects)}}
    files = {}
    for fname, body in docs.items():
        if fname in skip:
            continue
        doc = {'schema': f"foundry-data/{fname[:-5]}@1", **head, 'count': len(body[LIST_KEYS[fname]]), **body}
        write_json(vdir / fname, doc)
        files[fname] = {'count': doc['count'], 'sha256': '0'}
    source = (manifest_extra or {}).get('templateSource', 'StreamingAssets/Templates')
    if template_fields is not None:
        write_json(vdir / 'template_fields.json', template_fields_doc(head, source, template_fields))
    loc = loc if loc is not None else {'en': strings or {}}
    for lang, st in loc.items():
        write_json(vdir / 'localization' / f'{lang}.json', {'schema': 'foundry-data/localization@1', **head,
                                                             'language': lang, 'count': 0, 'strings': st})
    write_json(vdir / 'manifest.json', {'schemaVersion': '1.0', **head, 'unityVersion': 'x',
                                        'generatedAt': f'2026-01-01T00:00:0{len(ver) % 10}+00:00',
                                        'generator': 'foundry-export test', 'languages': sorted(loc),
                                        'templateSource': source, 'warnings': sorted(warnings), 'files': files,
                                        **(manifest_extra or {})})
    return vdir


def template_fields_doc(head: dict, source: str, types: dict) -> dict:
    return {'schema': 'foundry-data/template_fields@1', **head, 'templateSource': source, 'count': len(types),
            'types': {t: {'count': 1, 'fields': sorted(f)} for t, f in sorted(types.items())}}


def ensure_template_counts(vdir: Path) -> None:
    """manifest.templateCounts for a copied export that predates it (from template_fields.json)."""
    man = read_json(vdir / 'manifest.json')
    if not isinstance(man.get('templateCounts'), dict):
        tf = read_json(vdir / 'template_fields.json')
        man['templateCounts'] = {t: v['count'] for t, v in tf['types'].items() if t != 'AssemblyLineStages'}
        write_json(vdir / 'manifest.json', man)


def ensure_template_fields(vdir: Path) -> dict:
    """template_fields.json for a copied export that predates it (built from the committed baseline)."""
    p = vdir / 'template_fields.json'
    if not p.is_file():
        man, base = read_json(vdir / 'manifest.json'), read_json(BASELINE)
        head = {'gameVersion': man['gameVersion'], 'steamBuildId': man['steamBuildId']}
        write_json(p, template_fields_doc(head, man.get('templateSource'),
                                          {t: v['fields'] for t, v in base['types'].items()}))
    return read_json(p)


def item(i: str, **kw) -> dict:
    return {'identifier': i, 'name': i.upper(), 'stackSize': 50, 'flags': [], **kw}


def recipe(i: str, producers=(), **kw) -> dict:
    return {'identifier': i, 'name': i, 'timeMs': 1000, 'tags': ['assembler'], 'inputs': [{'item': 'a', 'amount': 1}],
            'outputs': [{'item': i, 'amount': 1, 'chance': 1}], 'fluidInputs': [], 'fluidOutputs': [],
            'derived': {'unlockedBy': {'research': [], 'explorationUnlocks': []},
                        'producers': [{'machine': m, 'kind': 'Producer', 'speedMultiplier': s, 'craftTimeSec': 1 / s}
                                      for m, s in producers]}, **kw}


def action(i: str, power=100, parent=None, **pa) -> dict:
    return {'identifier': i, 'type': 'MachineInteraction', 'description': None, 'parentAction': parent,
            'producerAction': {'identifier': f'pa{i}', 'name': f'Action {i}', 'powerKJ': power, 'items': [],
                               'fluids': [], 'attachesPart': None, **pa}}


def al_object(i: str, stages) -> dict:
    return {'identifier': i, 'name': i, 'starterItem': 's', 'sellItem': 'x', 'researchedBy': None, 'parts': [],
            'stages': [{'identifier': sid, 'title': title, 'description': None, 'actions': acts}
                       for sid, title, acts in stages],
            'derived': {'totalPowerKJ': 1}}


class SyntheticDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='diff_test_')
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self, old: dict, new: dict) -> tuple[dict, str]:
        for side in ('a', 'b'):   # several pairs per test: start from empty folders
            shutil.rmtree(self.root / side, ignore_errors=True)
        o = mini_export(self.root / 'a' / 'v1.0.0', **old)
        n = mini_export(self.root / 'b' / 'v1.0.1', **new)
        d = diff_versions(o, n)
        return d, render_changes_md(d)

    def test_al_stage_rename_and_action_position(self):
        old = {'al_objects': [al_object('o', [('s', 'Stage', [action('a'), action('b'), action('c')])]),
                              al_object('o2', [('old_st', 'Peripherals', [action('x')])])]}
        new = {'al_objects': [al_object('o', [('s', 'Stage', [action('b'), action('a'), action('c', power=250)])]),
                              al_object('o2', [('new_st', 'Peripherals', [action('x')])])]}
        d, md = self.pair(old, new)
        stages = section(md, 'Assembly-Line-Stufen')
        self.assertIn('- `o2 / new_st` – Peripherals\n  - identifier: `old_st` → `new_st`', stages)
        self.assertNotIn('### Neu', stages)
        self.assertNotIn('### Entfernt', stages)
        acts = section(md, 'Assembly-Line-Aktionen')
        # entries show the producer action template id (ALPA) next to '<object> / <action>'
        self.assertIn('- `o / a` (`paa`) – Action a\n  - position: 1 → 2', acts)   # LCS keeps b, c; only a moved
        self.assertNotIn('`o / b`', acts)
        self.assertIn('- `o / c` (`pac`) – Action c\n  - producerAction.powerKJ: 100 → 250', acts)
        self.assertIn('- `o2 / x` (`pax`) – Action x\n  - stage: `old_st` → `new_st`', acts)
        self.assertEqual(next(e for s in d['sections'] if s['key'] == 'alActions' for e in s['changed']
                              if e['id'] == 'o / c')['ref'], 'pac')

    def test_al_action_added_and_removed_show_producer_action(self):
        old = {'al_objects': [al_object('o', [('s', 'S', [action('a'), action('gone')])])]}
        new = {'al_objects': [al_object('o', [('s', 'S', [action('a'), action('weld', power=500)])])]}
        d, md = self.pair(old, new)
        acts = section(md, 'Assembly-Line-Aktionen')
        self.assertIn('### Neu (1)\n\n- `o / weld` (`paweld`) – Action weld: Stufe `s`, Position 2', acts)
        self.assertIn('### Entfernt (1)\n\n- `o / gone` (`pagone`) – Action gone', acts)
        self.assertNotIn('(`', section(md, 'Assembly-Line-Stufen'))   # only actions carry the ALPA id

    def test_new_extractor_field_only_listed_once(self):
        old = {'items': [item('i1'), item('i2', legacy=1)], 'al_objects': [al_object('o', [('s', 'S', [action('a')])])]}
        new = {'items': [item('i1', weightKg=1.0), item('i2', weightKg=2.0)],
               'al_objects': [al_object('o', [('s', 'S', [action('a', durationSec=2)])])]}
        d, md = self.pair(old, new)
        self.assertEqual(section(md, 'Items').count('weightKg'), 0)
        self.assertEqual(section(md, 'Assembly-Line-Aktionen').count('durationSec'), 0)
        fields = section(md, 'Neue Felder im Export (Extractor erweitert)')
        self.assertIn('- Items: `weightKg`', fields)
        self.assertIn('- Assembly-Line-Aktionen: `producerAction.durationSec`', fields)
        # 'legacy' existed only on one old item -> real per-entry change, not an extractor field
        self.assertIn('- `i2` – I2\n  - legacy: 1 → (entfernt)', md)
        self.assertNotIn('Entfernte Felder im Export', md)

    def test_removed_extractor_field(self):
        d, md = self.pair({'items': [item('i1', legacy=1), item('i2', legacy=2)]}, {'items': [item('i1'), item('i2')]})
        self.assertIn('### Entfernte Felder im Export', md)
        self.assertIn('- Items: `legacy`', md)
        self.assertEqual(d['sections'][0]['changed'], [])

    def test_map_keys_are_data_not_fields(self):
        m = lambda i, slots: {'identifier': i, 'name': i, 'type': 'Producer', 'itemSlots': slots}  # noqa: E731
        d, md = self.pair({'machines': [m('m1', {'Input': 1}), m('m2', {})]},
                          {'machines': [m('m1', {'Input': 1, 'Fuel': 2}), m('m2', {'Fuel': 1})]})
        self.assertIn('- `m1` – m1\n  - itemSlots.Fuel: (fehlt) → 2', md)
        self.assertIn('- `m2` – m2\n  - itemSlots.Fuel: (fehlt) → 1', md)
        self.assertIn('## Neue Felder im Export (Extractor erweitert)\n\nkeine', md)

    def test_list_changes(self):
        r = lambda deps, cost, recipes: {'identifier': 'r', 'name': 'R', 'cost': cost, 'dependencies': deps,  # noqa: E731
                                         'unlocks': {'recipes': recipes}}
        d, md = self.pair({'research': [r(['x', 'y'], [{'item': 'sp1', 'amount': 10}], ['a', 'b'])]},
                          {'research': [r(['x', 'z'], [{'item': 'sp1', 'amount': 20}, {'item': 'sp2', 'amount': 5}],
                                          ['b', 'a'])]})
        sec = section(md, 'Forschungen')
        self.assertIn('  - cost: `sp1` 10 → 20', sec)
        self.assertIn('  - cost: + `sp2` 5', sec)
        self.assertIn('  - dependencies: + `z`; − `y`', sec)
        self.assertIn('  - unlocks.recipes: Reihenfolge `a`, `b` → `b`, `a`', sec)

    def test_producer_summary(self):
        old = {'recipes': [recipe('r1', [('m1', 1)]), recipe('r2', [('m1', 1)]), recipe('r3', [('m1', 1)])]}
        new = {'recipes': [recipe('r1', [('m1', 2), ('m2', 1)]), recipe('r2', [('m1', 2), ('m2', 1)]),
                           recipe('r3', [('m1', 1)], timeMs=500)]}
        d, md = self.pair(old, new)
        sec = section(md, 'Rezepte')
        self.assertIn('- `m2` stellt jetzt zusätzlich 2 Rezept(e) her: `r1`, `r2`', sec)
        self.assertIn('- `m1` speedMultiplier: 1 → 2 (2 Rezept(e): `r1`, `r2`)', sec)
        self.assertIn('### Geändert (1)\n\n- `r3` – r3\n  - timeMs: 1000 → 500', sec)
        self.assertIn('_2 weitere Einträge haben nur Änderungen in abgeleiteten Feldern', sec)
        self.assertIn('| Rezepte | 3 | 3 | 0 | 0 | 1 |', md)

    def test_collapse_large_lists(self):
        d, md = self.pair({'items': []}, {'items': [item(f'i{n:03}') for n in range(COLLAPSE + 10)]})
        sec = section(md, 'Items')
        self.assertIn(f'<details>\n<summary>{COLLAPSE + 10} Einträge anzeigen</summary>', sec)
        self.assertLess(sec.index('`i000`'), sec.index('`i059`'))

    def test_localization_and_missing_file(self):
        old = {'strings': {'items': {'a': {'name': 'A'}, 'b': {'name': 'B'}}}, 'skip': ('elements.json',)}
        new = {'strings': {'items': {'a': {'name': 'A2'}, 'b': {'name': 'B'}, 'c': {'name': 'C'}}},
               'elements': [{'identifier': 'e', 'name': 'E'}]}
        d, md = self.pair(old, new)
        self.assertIn('| en | 2 | 3 | 1 | 0 | 1 |', section(md, 'Lokalisierung'))
        self.assertIn('fehlen in der alten Version – kein Vergleich möglich', section(md, 'Elemente'))
        self.assertIn('| Elemente | – | 1 | – | – | – |', md)
        self.assertIn('- `elements.json`', section(md, 'Neue Felder im Export (Extractor erweitert)'))

    def test_cli(self):
        self.assertFalse(hasattr(diffmod, 'previous_version'))   # removed: cli uses checks.previous_version
        o = mini_export(self.root / 'out' / 'v1.0.9', items=[item('i1')])
        n = mini_export(self.root / 'out' / 'v1.0.10', items=[item('i1'), item('i2')])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main([str(o), str(n)]), 0)
            js = self.root / 'diff.json'
            self.assertEqual(main(['none', str(o), '--out', str(self.root / 'first.md'), '--json', str(js)]), 0)
            self.assertEqual(main([str(self.root / 'nope'), str(n)]), 2)
        self.assertIn(str(n / 'CHANGES.md'), out.getvalue())
        self.assertIn('manifest.json missing', err.getvalue())
        md = (n / 'CHANGES.md').read_text(encoding='utf-8')
        self.assertTrue(md.startswith('# Änderungen v1.0.9 → v1.0.10\n'))
        self.assertIn('### Neu (1)\n\n- `i2` – I2: Stack 50', md)
        self.assertTrue(read_json(js)['first'])
        self.assertIn('# Erster Export v1.0.9', (self.root / 'first.md').read_text(encoding='utf-8'))

    # ---- 1. verdict refers to data, warnings are listed but do not count

    def test_only_warnings_changed_is_no_data_change(self):
        base = {'items': [item('i1')], 'warnings': ['recipes use undefined crafting tag base_station']}
        new = dict(base, warnings=base['warnings'] + ['source: v1.0.0 already exists with Steam build 1; written to '
                                                      'v1.0.0-b2'])
        d, md = self.pair(base, new)
        self.assertFalse(d['hasChanges'])
        self.assertTrue(d['warningsChanged'])
        self.assertIn('**Ergebnis: keine Datenänderungen** (nur Warnungen geändert: 1 neu, 0 entfallen', md)
        self.assertIn('### Neu in dieser Version (1)\n\n- source: v1.0.0 already exists', section(md, 'Warnungen'))
        d, md = self.pair(new, base)   # a warning that disappeared does not count either
        self.assertFalse(d['hasChanges'])
        self.assertIn('(nur Warnungen geändert: 0 neu, 1 entfallen', md)
        self.assertIn('### Nicht mehr vorhanden (1)', section(md, 'Warnungen'))

    def test_nothing_changed_and_data_change_verdicts(self):
        d, md = self.pair({'items': [item('i1')]}, {'items': [item('i1')]})
        self.assertFalse(d['hasChanges'] or d['warningsChanged'])
        self.assertIn('**Ergebnis: keine Datenänderungen** (auch die Warnungen sind unverändert', md)
        d, md = self.pair({'items': [item('i1')]}, {'items': [item('i1', stackSize=100)], 'warnings': ['w']})
        self.assertTrue(d['hasChanges'])
        self.assertNotIn('**Ergebnis', md)
        self.assertIn('- Warnungen: 1 neu, 0 entfallen', md)

    # ---- 2. template fields

    def test_template_fields_new_and_removed_topmost(self):
        old_tf = {'ItemTemplate': ['identifier', 'name', 'legacy', 'legacy.x'],
                  'AssemblyLineStages': ['stages', 'stages[].identifier'], 'GoneTemplate': ['a']}
        new_tf = {'ItemTemplate': ['identifier', 'name', 'weightKg', 'parts', 'parts[].id', 'parts[].sub.x'],
                  'AssemblyLineStages': ['stages', 'stages[].identifier', 'stages[].durationSec'],
                  'NewTemplate': ['a', 'b']}
        d, md = self.pair({'template_fields': old_tf}, {'template_fields': new_tf})
        tf = d['templateFields']
        self.assertEqual(tf['types'], [
            {'type': 'AssemblyLineStages', 'added': ['stages[].durationSec'], 'removed': []},
            {'type': 'ItemTemplate', 'added': ['parts', 'weightKg'], 'removed': ['legacy']}])
        self.assertEqual(tf['typesAdded'], [{'type': 'NewTemplate', 'fields': 2}])
        self.assertEqual(tf['typesRemoved'], [{'type': 'GoneTemplate', 'fields': 1}])
        self.assertTrue(d['hasChanges'])
        sec = section(md, 'Template-Felder')
        self.assertIn('- `AssemblyLineStages`\n  - neu (1): `stages[].durationSec`', sec)
        self.assertIn('- `ItemTemplate`\n  - neu (2): `parts`, `weightKg`\n  - entfernt (1): `legacy`', sec)
        self.assertNotIn('parts[].id', md)
        self.assertIn('`NewTemplate` (2 Felder)', sec)
        self.assertIn('Nur in der Vorversion erfasst: `GoneTemplate` (1 Felder)', sec)
        self.assertIn('- Template-Felder: 3 neu / 1 entfernt in 2 Typ(en)', md)
        self.assertLess(md.index('\n## Neue Template-Typen\n'), md.index('\n## Template-Felder\n'))
        self.assertLess(md.index('\n## Template-Felder\n'), md.index('\n## Warnungen\n'))

    def test_template_fields_unchanged_or_not_determinable(self):
        tf = {'ItemTemplate': ['identifier'], 'AssemblyLineStages': ['stages']}
        d, md = self.pair({'template_fields': tf}, {'template_fields': tf})
        self.assertFalse(d['hasChanges'])
        self.assertIn('keine neuen oder entfernten Template-Felder (2 Template-Typen verglichen)',
                      section(md, 'Template-Felder'))
        d, md = self.pair({}, {'template_fields': tf})
        self.assertEqual(d['templateFields']['status'], 'oldMissing')
        self.assertIn('nicht bestimmbar (Vorversion ohne template_fields.json)', section(md, 'Template-Felder'))
        self.assertIn('- `template_fields.json`', section(md, 'Neue Felder im Export (Extractor erweitert)'))
        d, md = self.pair({'template_fields': tf}, {})
        self.assertIn('nicht bestimmbar (neue Version ohne template_fields.json)', section(md, 'Template-Felder'))

    def test_template_fields_from_different_sources_flagged(self):
        tf = {'ItemTemplate': ['identifier']}
        d, md = self.pair({'template_fields': tf},
                          {'template_fields': tf, 'manifest_extra': {'templateSource': 'foundry_main_bundle'}})
        self.assertIn('Feldlisten aus unterschiedlichen Template-Quellen (`StreamingAssets/Templates` → '
                      '`foundry_main_bundle`)', section(md, 'Template-Felder'))

    def test_topmost(self):
        self.assertEqual(diffmod._topmost({'a', 'a.b', 'a[].c', 'a[][].d', 'ab', 'ab.c[].d', 'x.y'}),
                         ['a', 'ab', 'x.y'])

    # ---- 4. localization coverage of new entries

    def test_new_entries_without_translation(self):
        def loc(*ids, title=False):
            f = 'title' if title else 'name'
            return {'items': {i: {f: i.upper()} for i in ids if not i.startswith('e')},
                    'explorationUnlocks': {i: {'title': i} for i in ids if i.startswith('e')},
                    'assemblyLineActions': {f'pa{i}': {'name': i} for i in ids}}
        old = {'items': [item('i1')], 'loc': {'de': loc('i1'), 'en': loc('i1')}}
        new = {'items': [item('i1'), item('i2'), item('i3')], 'exploration': [{'identifier': 'e1', 'title': 'E1'}],
               'al_objects': [al_object('o', [('s', 'S', [action('a')])])],
               'loc': {'de': loc('i1', 'i2', 'e1'), 'en': {**loc('i1', 'i2', 'i3', 'e1', 'a'), 'items': {
                   'i1': {'name': 'I1'}, 'i2': {'name': ' '}, 'i3': {'description': 'no name'}}}}}
        d, md = self.pair(old, new)
        cov = d['localization']['newEntries']
        self.assertEqual(cov['checked'], 5)    # i2, i3, e1, o (AL object), o / a (via producer action 'paa')
        self.assertEqual([(x['section'], x['id']) for x in cov['missing']['de']],
                         [('Items', 'i3'), ('Assembly-Line-Roboter', 'o'), ('Assembly-Line-Aktionen', 'o / a')])
        self.assertEqual([x['id'] for x in cov['missing']['en']], ['i2', 'i3', 'o'])
        sec = section(md, 'Lokalisierung')
        self.assertIn('neue Einträge ohne deutsche Übersetzung (de.json, kein `name`/`title`): 3\n\n'
                      '- Items: `i3`\n- Assembly-Line-Roboter: `o`\n- Assembly-Line-Aktionen: `o / a` (`paa`)', sec)
        self.assertIn('neue Einträge ohne englischen Text (en.json, kein `name`/`title`): 3\n\n- Items: `i2`', sec)
        self.assertIn('- 3 neue Einträge ohne deutsche Übersetzung (de.json, siehe „Lokalisierung“)', md)
        self.assertTrue(d['hasChanges'])   # new entries are data changes; missing translations are only listed

    def test_item_categories(self):
        cat = lambda i, n, **kw: {'identifier': i, 'name': n, 'sortOrder': 0, **kw}  # noqa: E731
        # export before schema 1.2 (no category lists) -> not comparable, no crash
        d, md = self.pair({'items': [item('i1')]}, {'items': [item('i1')], 'categories': [cat('c1', 'Products')],
                                                     'creative_categories': [cat('m1', 'Factory')]})
        secs = {s['key']: s for s in d['sections']}
        self.assertFalse(secs['itemCategories']['comparable'])
        self.assertEqual((secs['itemCategories']['oldCount'], secs['itemCategories']['newCount']), (None, 1))
        self.assertEqual(secs['creativeModeCategories']['newCount'], 1)
        # renamed / added categories; the new one has no German name
        st = {'itemCategories': {'c1': {'name': 'Produkte'}}, 'creativeModeCategories': {'m1': {'name': 'Fabrik'}}}
        old = {'categories': [cat('c1', 'Products')], 'creative_categories': [cat('m1', 'Factory')],
               'loc': {'de': st, 'en': st}}
        new = {'categories': [cat('c1', 'Sales Items')], 'creative_categories': [cat('m1', 'Factory'), cat('m2', 'Decor')],
               'loc': {'de': st, 'en': {**st, 'creativeModeCategories': {'m1': {'name': 'Factory'}, 'm2': {'name': 'Decor'}}}}}
        d, md = self.pair(old, new)
        secs = {s['key']: s for s in d['sections']}
        self.assertEqual([c['id'] for c in secs['itemCategories']['changed']], ['c1'])
        self.assertEqual([c['id'] for c in secs['creativeModeCategories']['added']], ['m2'])
        self.assertEqual([(x['section'], x['id']) for x in d['localization']['newEntries']['missing']['de']],
                         [('Creative-Mode-Kategorien', 'm2')])
        self.assertEqual(d['localization']['newEntries']['missing']['en'], [])
        self.assertIn('Sales Items', md)
        self.assertTrue(d['hasChanges'])

    def test_new_entries_all_translated_or_language_missing(self):
        st = {'items': {'i1': {'name': 'A'}, 'i2': {'name': 'B'}}}
        d, md = self.pair({'items': [item('i1')], 'loc': {'de': st, 'en': st}},
                          {'items': [item('i1'), item('i2')], 'loc': {'de': st, 'en': st}})
        self.assertIn('Alle 1 neuen Einträge haben `name`/`title` in de.json und en.json.', section(md, 'Lokalisierung'))
        d, md = self.pair({'items': [item('i1')], 'loc': {'en': st}}, {'items': [item('i1'), item('i2')], 'loc': {'en': st}})
        self.assertEqual(d['localization']['newEntries']['unavailable'], ['de'])
        sec = section(md, 'Lokalisierung')
        self.assertIn('Neue Einträge: `localization/de.json` fehlt – Übersetzungen nicht prüfbar.', sec)
        self.assertIn('Alle 1 neuen Einträge haben `name`/`title` in en.json.', sec)
        d, md = self.pair({'items': [item('i1')]}, {'items': [item('i1')]})   # nothing new -> no coverage line
        self.assertNotIn('Einträge haben', md)
        self.assertNotIn('ohne deutsche', md)

    # ---- 5. template source notice

    def test_source_notice(self):
        d, md = self.pair({'items': [item('i1')]}, {'items': [item('i1')], 'warnings': [MISMATCH_WARNING],
                                                    'manifest_extra': {'templateSource': 'foundry_main_bundle'}})
        self.assertEqual(d['sourceNotice']['reasons'], ['mismatch'])
        self.assertTrue(d['sourceNotice']['switched'])
        head = md[:md.index('\n## Übersicht\n')]
        self.assertIn('> **Hinweis zur Template-Quelle:** Die Daten dieser Version stammen aus `foundry_main_bundle`.', head)
        self.assertIn('weicht von `foundry_main_bundle` ab', head)
        self.assertIn('Die Vorversion wurde aus `StreamingAssets/Templates` gelesen. **Änderungen gegenüber der '
                      'Vorversion können ganz oder teilweise auf diesen Quellenwechsel zurückgehen**', head)
        self.assertLess(head.index('| Template-Quelle |'), head.index('> **Hinweis'))

    def test_source_notice_fallback_without_switch_and_none(self):
        bundle = {'templateSource': 'foundry_main_bundle'}
        d, md = self.pair({'items': [item('i1')], 'manifest_extra': bundle},
                          {'items': [item('i1')], 'warnings': [FALLBACK_WARNING], 'manifest_extra': bundle})
        self.assertEqual(d['sourceNotice']['reasons'], ['fallback'])
        self.assertFalse(d['sourceNotice']['switched'])
        head = md[:md.index('\n## Übersicht\n')]
        self.assertIn('fehlt oder ist unvollständig; die Templates wurden aus `foundry_main_bundle` gelesen (Fallback).', head)
        self.assertIn('Die Vorversion wurde aus derselben Quelle gelesen (kein Quellenwechsel).', head)
        # switch alone (no warning) is enough; same source without such warnings -> no notice
        d, md = self.pair({'items': [item('i1')], 'manifest_extra': bundle}, {'items': [item('i1')]})
        self.assertEqual(d['sourceNotice']['reasons'], [])
        self.assertIn('Quellenwechsel zurückgehen', md)
        d, md = self.pair({'items': [item('i1')], 'warnings': ['source: Templates/X.yaml line 5 is not valid YAML']},
                          {'items': [item('i1')], 'warnings': ['source: Templates/X.yaml line 5 is not valid YAML']})
        self.assertIsNone(d['sourceNotice'])
        self.assertNotIn('Hinweis zur Template-Quelle', md)
        # first export: notice without the comparison sentence
        first = render_changes_md(diff_versions(None, mini_export(self.root / 'c' / 'v2.0.0', items=[item('i1')],
                                                                  warnings=[FALLBACK_WARNING], manifest_extra=bundle)))
        self.assertIn('> **Hinweis zur Template-Quelle:** Die Daten dieser Version stammen aus `foundry_main_bundle`.', first)
        self.assertNotIn('Vorversion', first)


def find_reference(tmp: Path) -> Path:
    """Reference export (read only - tests work on copies): env FOUNDRY_REF_EXPORT, else the repo's out/<latest>
    (out/v0.6.0.26518 when latest.json is unusable), else a fresh export of the installed game into tmp."""
    env = os.environ.get('FOUNDRY_REF_EXPORT')
    if env and (Path(env) / 'manifest.json').is_file():
        return Path(env)
    out_dir = REPO / 'out'
    try:
        latest = out_dir / read_json(out_dir / 'latest.json')['version']
    except (OSError, ValueError, KeyError, TypeError):
        latest = out_dir / 'v0.6.0.26518'
    if (latest / 'manifest.json').is_file():
        return latest
    if GAME is None:
        raise unittest.SkipTest('no reference export (out/) and FOUNDRY game folder not found')
    out = tmp / 'fresh'
    r = subprocess.run([sys.executable, str(EXTRACTOR / 'export'), str(GAME), str(out)],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise unittest.SkipTest(f'reference export failed: {r.stderr[-500:]}')
    return out / read_json(out / 'latest.json')['version']


class RealExportDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='diff_real_')
        root = Path(cls.tmp.name)
        try:
            cls.ref = find_reference(root)
        except unittest.SkipTest:
            cls.tmp.cleanup()
            raise
        cls.old = root / 'old' / cls.ref.name
        cls.new = root / 'new' / 'v9.9.9.99999'
        copy_export(cls.ref, cls.old)
        copy_export(cls.ref, cls.new)
        for v in (cls.old, cls.new):
            ensure_template_fields(v)
            ensure_template_counts(v)
        cls.facts = cls.mutate(cls.new)
        cls.diff = diff_versions(cls.old, cls.new)
        cls.md = render_changes_md(cls.diff)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def mutate(v: Path) -> dict:
        f: dict = {}
        docs = {name: read_json(v / name) for name in LIST_KEYS}
        f['counts'] = {name: d['count'] for name, d in docs.items()}
        r = next(x for x in docs['recipes.json']['recipes'] if x['inputs'])
        f['recipe'], f['time'], f['input'] = r['identifier'], r['timeMs'], dict(r['inputs'][0])
        r['timeMs'] = r['timeMs'] * 2
        r['inputs'][0]['amount'] += 1
        items = docs['items.json']['items']
        gone = items.pop(0)
        f['removedItem'] = (gone['identifier'], gone['name'])
        docs['items.json']['count'] -= 1
        for it in items:
            it['zzBrandNewKey'] = {'x': 1}
        res = docs['research.json']
        new_r = copy.deepcopy(res['research'][0])
        new_r.update(identifier='_zz_test_new_research', name='Test-Forschung')
        res['research'].append(new_r)
        res['count'] += 1
        obj = docs['assembly_line.json']['objects'][0]
        act = next(a for s in obj['stages'] for a in s['actions'] if isinstance(a['producerAction']['powerKJ'], (int, float)))
        f['action'] = (obj['identifier'], act['identifier'], act['producerAction']['name'], act['producerAction']['powerKJ'])
        act['producerAction']['powerKJ'] += 150
        f['actionRef'] = act['producerAction']['identifier']
        for name, d in docs.items():
            write_json(v / name, d)
        tf = read_json(v / 'template_fields.json')
        tf['types']['ItemTemplate']['fields'] += ['zzNewList', 'zzNewList[].a', 'zzNewList[].b.c']
        gone_field = sorted(tf['types']['ResearchTemplate']['fields'])[-1]
        tf['types']['ResearchTemplate']['fields'].remove(gone_field)
        f['goneField'] = gone_field
        tf['types']['AssemblyLineStages']['fields'] += ['stages[].stageSubActions.$items[].zzDurationSec']
        write_json(v / 'template_fields.json', tf)
        man = read_json(v / 'manifest.json')
        f['oldWarnings'] = len(man['warnings'])
        man.update(gameVersion='9.9.9.99999', steamBuildId='99999999', generatedAt='2099-01-01T00:00:00+00:00',
                   warnings=sorted(man['warnings'] + ['test: new warning']),
                   templateCounts={**man['templateCounts'], 'ZzBrandNewTemplate': 3})
        write_json(v / 'manifest.json', man)
        return f

    def test_header_and_summary(self):
        md, c = self.md, self.facts['counts']
        self.assertTrue(md.startswith(f'# Änderungen {self.ref.name} → v9.9.9.99999\n'))
        self.assertIn('| Steam-Build |', md)
        self.assertIn('2099-01-01T00:00:00+00:00', md)
        n_items, n_res = c['items.json'], c['research.json']
        self.assertIn(f'| Items | {n_items} | {n_items - 1} | 0 | 1 | 0 |', md)
        self.assertIn(f"| Rezepte | {c['recipes.json']} | {c['recipes.json']} | 0 | 0 | 1 |", md)
        self.assertIn(f'| Forschungen | {n_res} | {n_res + 1} | 1 | 0 | 0 |', md)
        self.assertRegex(md, r'\| Assembly-Line-Aktionen \| (\d+) \| \1 \| 0 \| 0 \| 1 \|')
        order = ['## Übersicht', '## Items', '## Rezepte', '## Maschinen und Gebäude', '## Forschungen',
                 '## Erkundungs-Freischaltungen', '## Assembly-Line-Roboter', '## Assembly-Line-Stufen',
                 '## Assembly-Line-Aktionen', '## Assembly-Line-Maschinen', '## Elemente', '## Crafting-Tags',
                 '## Neue Template-Typen', '## Warnungen']
        pos = [md.index(f'\n{h}\n') for h in order]
        self.assertEqual(pos, sorted(pos))

    def test_recipe_changes(self):
        f = self.facts
        sec = section(self.md, 'Rezepte')
        self.assertIn(f"- `{f['recipe']}`", sec)
        self.assertIn(f"  - timeMs: {f['time']} → {f['time'] * 2}", sec)
        self.assertIn(f"  - inputs: `{f['input']['item']}` {f['input']['amount']} → {f['input']['amount'] + 1}", sec)

    def test_items_removed_and_new_key_not_per_item(self):
        iid, name = self.facts['removedItem']
        sec = section(self.md, 'Items')
        self.assertIn(f'### Entfernt (1)\n\n- `{iid}` – {name}', sec)
        self.assertNotIn('### Geändert', sec)
        self.assertEqual(self.md.count('zzBrandNewKey'), 1)
        self.assertIn('- Items: `zzBrandNewKey`', section(self.md, 'Neue Felder im Export (Extractor erweitert)'))
        items = next(s for s in self.diff['sections'] if s['key'] == 'items')
        self.assertEqual(items['changed'], [])
        self.assertEqual(items['newFields'], ['zzBrandNewKey'])

    def test_research_and_al_action(self):
        self.assertIn('### Neu (1)\n\n- `_zz_test_new_research` – Test-Forschung: Kosten ', section(self.md, 'Forschungen'))
        oid, aid, name, power = self.facts['action']
        ref = self.facts['actionRef']
        self.assertIn(f'- `{oid} / {aid}` (`{ref}`) – {name}\n  - producerAction.powerKJ: {power} → {power + 150}',
                      section(self.md, 'Assembly-Line-Aktionen'))

    def test_template_fields(self):
        sec = section(self.md, 'Template-Felder')
        self.assertIn('- `AssemblyLineStages`\n  - neu (1): `stages[].stageSubActions.$items[].zzDurationSec`', sec)
        self.assertIn('- `ItemTemplate`\n  - neu (1): `zzNewList`\n', sec)
        self.assertNotIn('zzNewList[]', sec)
        self.assertIn(f"- `ResearchTemplate`\n  - entfernt (1): `{self.facts['goneField']}`", sec)
        self.assertNotIn('Nur in der neuen Version erfasst', sec)
        self.assertNotIn('Nur in der Vorversion erfasst', sec)

    def test_new_research_without_translation(self):
        sec = section(self.md, 'Lokalisierung')
        self.assertIn('neue Einträge ohne deutsche Übersetzung (de.json, kein `name`/`title`): 1\n\n'
                      '- Forschungen: `_zz_test_new_research`', sec)
        self.assertIn('neue Einträge ohne englischen Text (en.json, kein `name`/`title`): 1', sec)
        self.assertEqual(self.diff['localization']['newEntries']['checked'], 1)

    def test_new_build_same_data_is_no_data_change(self):
        """Review repro: same version.txt, new Steam build -> the export's own build-suffix warning must not turn
        'keine Datenänderungen' into a change."""
        with tempfile.TemporaryDirectory(prefix='diff_build_') as t:
            new = copy_export(self.old, Path(t) / f'{self.old.name}-b99999999')
            man = read_json(new / 'manifest.json')
            man.update(steamBuildId='99999999', previousVersion=self.old.name,
                       warnings=sorted(man['warnings'] + [
                           f"source: {self.old.name} already exists with Steam build {man['steamBuildId']}; installed "
                           f"build 99999999 written to {self.old.name}-b99999999"]))
            write_json(new / 'manifest.json', man)
            d = diff_versions(self.old, new)
            md = render_changes_md(d)
        self.assertFalse(d['hasChanges'])
        self.assertTrue(d['warningsChanged'])
        self.assertIn('**Ergebnis: keine Datenänderungen** (nur Warnungen geändert: 1 neu, 0 entfallen', md)
        self.assertIn('already exists with Steam build', section(md, 'Warnungen'))
        self.assertIn('keine neuen oder entfernten Template-Felder', section(md, 'Template-Felder'))
        self.assertIsNone(d['sourceNotice'])

    def test_source_switch_notice(self):
        with tempfile.TemporaryDirectory(prefix='diff_src_') as t:
            new = copy_export(self.new, Path(t) / self.new.name)
            man = read_json(new / 'manifest.json')
            old_src = man['templateSource']
            man.update(templateSource='foundry_main_bundle', warnings=sorted(man['warnings'] + [MISMATCH_WARNING]))
            write_json(new / 'manifest.json', man)
            md = render_changes_md(diff_versions(self.old, new))
        head = md[:md.index('\n## Übersicht\n')]
        self.assertIn('> **Hinweis zur Template-Quelle:** Die Daten dieser Version stammen aus `foundry_main_bundle`.', head)
        self.assertIn(f'Die Vorversion wurde aus `{old_src}` gelesen.', head)
        self.assertNotIn('Hinweis zur Template-Quelle', self.md)

    def test_templates_and_warnings(self):
        tpl = section(self.md, 'Neue Template-Typen')
        self.assertIn('- `ZzBrandNewTemplate`: 3 Templates', tpl)
        self.assertIn('Template-Anzahlen unverändert.', tpl)
        self.assertNotIn('Entfernte Template-Typen', tpl)
        w = section(self.md, 'Warnungen')
        self.assertIn('### Neu in dieser Version (1)\n\n- test: new warning', w)
        self.assertIn(f"Unverändert: {self.facts['oldWarnings']} Warnung(en).", w)

    def test_template_types_when_old_manifest_lacks_counts(self):
        with tempfile.TemporaryDirectory(prefix='diff_tpl_') as t:
            old = copy_export(self.old, Path(t) / 'old' / self.ref.name)
            man = read_json(old / 'manifest.json')
            del man['templateCounts']
            write_json(old / 'manifest.json', man)
            md = render_changes_md(diff_versions(old, self.new))
        tpl = section(md, 'Neue Template-Typen')
        self.assertIn('nicht bestimmbar', tpl)
        self.assertIn('- `ZzBrandNewTemplate`: 3', tpl)
        self.assertIn('- manifest.json: `templateCounts`', section(md, 'Neue Felder im Export (Extractor erweitert)'))

    def test_template_counts_changed(self):
        n = read_json(self.new / 'manifest.json')['templateCounts']['CraftingRecipe']
        with tempfile.TemporaryDirectory(prefix='diff_tpl_') as t:
            old = copy_export(self.old, Path(t) / 'old' / self.ref.name)
            man = read_json(old / 'manifest.json')
            man['templateCounts']['CraftingRecipe'] = n - 2
            write_json(old / 'manifest.json', man)
            tpl = section(render_changes_md(diff_versions(old, self.new)), 'Neue Template-Typen')
        self.assertIn('- `ZzBrandNewTemplate`: 3 Templates', tpl)
        self.assertIn(f'- `CraftingRecipe`: {n - 2} → {n}', tpl)
        self.assertNotIn('nicht bestimmbar', tpl)

    def test_deterministic(self):
        again = diff_versions(self.old, self.new)
        self.assertEqual(json.dumps(again, sort_keys=False), json.dumps(self.diff, sort_keys=False))
        self.assertEqual(render_changes_md(again), self.md)

    def test_identical_folders(self):
        d = diff_versions(self.old, self.old)
        md = render_changes_md(d)
        self.assertFalse(d['hasChanges'])
        self.assertFalse(d['warningsChanged'])
        self.assertIn('**Ergebnis: keine Datenänderungen** (auch die Warnungen sind unverändert', md)
        self.assertIsNone(d['sourceNotice'])
        self.assertNotIn('### Geändert', md)
        self.assertNotIn('### Neu', md)

    def test_first_version(self):
        md = render_changes_md(diff_versions(None, self.ref))
        self.assertTrue(md.startswith(f'# Erster Export {self.ref.name}\n'))
        self.assertIn(f"| Items | {self.facts['counts']['items.json']} |", md)
        self.assertIn('keine Vorgängerversion', md)
        self.assertRegex(section(md, 'Lokalisierung'), r'Alle \d+ Einträge haben `name`/`title` in de\.json und en\.json\.')


if __name__ == '__main__':
    unittest.main()
