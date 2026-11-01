"""'Nothing may silently drop' checks (foundry_export.checks): synthetic scans/manifests, enum values, baseline round
trip, previous-version lookup, and the real game against the committed baseline (through the production path:
sources.open_template_source via build.Data, checks.scan + scan_stages, enum_values/enum_warnings)."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from _util import GAME, require_game  # noqa: F401  (puts extractor/ on sys.path)

from foundry_export import checks
from foundry_export.checks import (ENUM_FIELDS, EXPORTED_TYPES, STAGES_TYPE, count_warnings, enum_values,
                                   enum_warnings, field_paths, load_baseline, previous_version, scan, scan_stages,
                                   scan_yaml_dir, template_counts, template_warnings, version_key, write_baseline,
                                   yaml_dir_source)
from foundry_export.sources import TemplateLoadError, YamlTemplateSource


def baseline_of(templates: dict[str, dict[str, dict]], **meta) -> dict:
    """Baseline dict as load_baseline() would return it, built from {type: {ident: body}}."""
    res = scan(templates, templates.__getitem__)
    with tempfile.TemporaryDirectory() as tmp:
        return load_baseline(write_baseline(res, Path(tmp) / 'b.json', **meta))


ITEM = {'identifier': 'a', 'name': 'A', 'stackSize': 10, 'fuel': {'kj': 1}, 'tags': ['x', 'y']}
QUEST = {'identifier': 'q', 'title': 'Q', 'steps': [{'goal': 1}]}
BASE = {'ItemTemplate': {'a': ITEM, 'b': {**ITEM, 'identifier': 'b'}}, 'QuestTemplate': {'q': QUEST}}


class FieldPathTests(unittest.TestCase):
    def test_nested_dicts_and_lists(self):
        body = {'id': 'x', 'in': [{'identifier': 'i', 'amount': 1}, {'identifier': 'j', 'extra': {'k': 1}}],
                'pos': {'x': 1, 'y': 2}, 'tags': ['a', 'b'], 'empty': [], 'grid': [[{'c': 1}]]}
        self.assertEqual(field_paths(body), {
            'id', 'in', 'in[].identifier', 'in[].amount', 'in[].extra', 'in[].extra.k',
            'pos', 'pos.x', 'pos.y', 'tags', 'empty', 'grid', 'grid[][].c'})

    def test_values_ignored_and_depth_limit(self):
        self.assertEqual(field_paths({'a': 'x'}), field_paths({'a': {'b': None}}) - {'a.b'})
        deep = {'a': {'b': {'c': {'d': 1}}}}
        self.assertEqual(field_paths(deep, max_depth=2), {'a', 'a.b'})
        self.assertEqual(field_paths(deep), {'a', 'a.b', 'a.b.c', 'a.b.c.d'})


class ScanTests(unittest.TestCase):
    def test_counts(self):
        data = {'T': {'1': {'a': 1, 'l': [{'x': 1}]}, '2': {'a': 2, 'l': []}}, 'U': {}}
        res = scan(['U', 'T', 'T'], data.__getitem__)
        self.assertEqual(list(res), ['T', 'U'])
        self.assertEqual(res['T'], {'count': 2, 'fields': {'a': 2, 'l': 2, 'l[].x': 1}})
        self.assertEqual(res['U'], {'count': 0, 'fields': {}})

    def test_unrepairable_yaml_is_recorded_not_raised(self):
        """A real YamlTemplateSource on a file _repair cannot fix (a line without ':') raises TemplateLoadError;
        scan() records it per type and carries on with the others."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for t, text in (('Good', 'Good:\n  g:\n    a: 1\n'),
                            ('Bad', 'Bad:\n  b:\n    a: 1\n    garbage line without colon\n')):
                (root / t).mkdir()
                (root / t / f'{t.lower()}.yaml').write_text(text, encoding='utf-8')
            src = YamlTemplateSource(root, [])
            with self.assertRaises(TemplateLoadError):
                YamlTemplateSource(root, []).load('Bad')
            res = scan(src.type_names() + ['Missing'], src.load)      # 'Missing': no folder -> TemplateLoadError too
        self.assertEqual(res['Good'], {'count': 1, 'fields': {'a': 1, 'identifier': 1}})
        self.assertEqual(res['Bad']['count'], 0)
        self.assertTrue(res['Bad']['error'].startswith('Templates/Bad/bad.yaml: invalid YAML'), res['Bad'])
        self.assertTrue(res['Missing']['error'].startswith('missing template folder'), res['Missing'])
        self.assertEqual(template_counts(res), {'Good': 1})
        w = template_warnings(res, {'types': {'Good': {'fields': ['a', 'identifier']}, 'Bad': {'fields': ['a']}}})
        self.assertEqual(len(w), 2, w)
        self.assertTrue(w[0].startswith('source: cannot scan Bad: Templates/Bad/bad.yaml: invalid YAML'), w)
        self.assertTrue(w[1].startswith('source: cannot scan Missing: missing template folder'), w)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            write_baseline(res, Path(tmp) / 'b.json')

    def test_system_exit_is_recorded_not_raised(self):
        # game.locate / build.Data still raise SystemExit for broken game files; a loader doing so must not end the run
        def load(t):
            if t == 'Bad':
                raise SystemExit('missing /x/foundry_main_bundle')
            return {'1': {'a': 1}}
        res = scan(['Good', 'Bad'], load)
        self.assertEqual(res['Bad'], {'count': 0, 'fields': {}, 'error': 'missing /x/foundry_main_bundle'})
        self.assertEqual(res['Good']['count'], 1)

    def test_scan_stages(self):
        stages = {'_base_droid01': [{'actions': [{'a': 1}], 'name': 's1'}, {'actions': [], 'name': 's2'}],
                  '_base_droid02': [{'actions': [{'a': 1, 'timeMs': 5}]}]}
        res = scan_stages(stages)
        self.assertEqual(list(res), [STAGES_TYPE])
        self.assertEqual(res[STAGES_TYPE], {'count': 2, 'fields': {
            'stages': 2, 'stages[].actions': 2, 'stages[].actions[].a': 2, 'stages[].actions[].timeMs': 1,
            'stages[].name': 1}})

    def test_yaml_dir_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'PlanetTemplate').mkdir()
            (root / 'EmptyTemplate').mkdir()
            # the game's exporter writes a bare '-' unquoted; must still load
            (root / 'PlanetTemplate' / 'p1.yaml').write_text(
                'PlanetTemplate:\n  p1:\n    planetName: Home\n    planetInfo: -\n    demands: []\n', encoding='utf-8')
            (root / 'PlanetTemplate' / 'p2.yaml').write_text('PlanetTemplate:\n  p2:\n    a: [\n', encoding='utf-8')
            errors: list[str] = []
            names, load = yaml_dir_source(root, errors)
            self.assertEqual(names, ['EmptyTemplate', 'PlanetTemplate'])
            planets = load('PlanetTemplate')
            self.assertEqual(planets, {'p1': {'planetName': 'Home', 'planetInfo': '-', 'demands': [],
                                              'identifier': 'p1'}})
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith('source: cannot parse PlanetTemplate/p2.yaml: '), errors)
            res = scan_yaml_dir(root)
            self.assertEqual(res['EmptyTemplate']['count'], 0)
            self.assertEqual(res['PlanetTemplate']['fields']['planetInfo'], 1)


class TemplateWarningTests(unittest.TestCase):
    def setUp(self):
        self.baseline = baseline_of(BASE, game_version='1.0', template_source='StreamingAssets/Templates')

    def warn(self, data: dict, **kw) -> list[str]:
        return template_warnings(scan(data, data.__getitem__), self.baseline, **kw)

    def test_unchanged_is_silent(self):
        self.assertEqual(self.warn(BASE), [])
        # template counts alone are not a template warning (count_warnings handles them)
        self.assertEqual(self.warn({**BASE, 'ItemTemplate': {'a': ITEM}}), [])
        self.assertEqual(self.warn(BASE, template_source='StreamingAssets/Templates'), [])

    def test_new_and_removed_type(self):
        data = {'ItemTemplate': BASE['ItemTemplate'], 'NewTemplate': {'n1': {'a': 1}, 'n2': {'a': 1}},
                'CraftingRecipe': {'r': {'x': 1}}}
        self.assertEqual(self.warn(data), [
            'new-template-type: CraftingRecipe (1 templates)',
            'new-template-type: NewTemplate (2 templates, not exported)',
            'removed-template-type: QuestTemplate'])

    def test_unknown_field_exported(self):
        item = {**ITEM, 'newField': 1, 'fuel': {'kj': 1, 'residual': 'x'},
                'newList': [{'p': 1, 'q': {'r': 2}}]}
        w = self.warn({**BASE, 'ItemTemplate': {'a': item, 'b': {**ITEM, 'newField': 2}}})
        # nested paths of a new list are reported once, via their topmost new parent
        self.assertEqual(w, [
            'unknown-field: ItemTemplate.fuel.residual (1 templates), not read by the extractor',
            'unknown-field: ItemTemplate.newField (2 templates), not read by the extractor',
            'unknown-field: ItemTemplate.newList (1 templates), not read by the extractor'])

    def test_unknown_field_other_type_grouped(self):
        quest = {**QUEST, 'zeta': 1, 'alpha': 2, 'steps': [{'goal': 1, 'reward': 3}]}
        self.assertEqual(self.warn({**BASE, 'QuestTemplate': {'q': quest}}),
                         ['unknown-field: QuestTemplate: alpha, steps[].reward, zeta'])

    def test_removed_field(self):
        item = {k: v for k, v in ITEM.items() if k not in ('stackSize', 'fuel')}
        quest = {'identifier': 'q', 'title': 'Q', 'steps': []}
        self.assertEqual(self.warn({'ItemTemplate': {'a': item}, 'QuestTemplate': {'q': quest}}), [
            'removed-field: ItemTemplate.fuel', 'removed-field: ItemTemplate.stackSize',
            'removed-field: QuestTemplate: steps[].goal'])

    def test_missing_baseline_and_source_mismatch(self):
        res = scan(BASE, BASE.__getitem__)
        w = template_warnings(res, None)
        self.assertEqual(len(w), 1)
        self.assertTrue(w[0].startswith('baseline: '))
        # another template source than the baseline's: only noted when there are field warnings to double-check
        self.assertEqual(template_warnings(res, self.baseline, template_source='foundry_main_bundle'), [])
        data = {**BASE, 'ItemTemplate': {'a': {**ITEM, 'newField': 1}}}
        w = template_warnings(scan(data, data.__getitem__), self.baseline, template_source='foundry_main_bundle')
        self.assertEqual(w[0], 'unknown-field: ItemTemplate.newField (1 templates), not read by the extractor')
        self.assertEqual(len(w), 2)
        self.assertTrue(w[1].startswith('source: templates read from foundry_main_bundle but baseline was taken from '
                                        'StreamingAssets/Templates'), w)
        # a new template type alone is no field warning -> no note
        data = {**BASE, 'NewTemplate': {'n': {'a': 1}}}
        self.assertEqual(template_warnings(scan(data, data.__getitem__), self.baseline, template_source='foundry_main_bundle'),
                         ['new-template-type: NewTemplate (1 templates, not exported)'])

    def test_stages_type_is_treated_as_exported(self):
        stages = {'d1': [{'actions': [{'a': 1}]}]}
        res = scan(BASE, BASE.__getitem__) | scan_stages(stages)
        baseline = baseline_of({**BASE}, game_version='1.0')
        self.assertEqual(template_warnings(res, baseline), ['new-template-type: AssemblyLineStages (1 templates)'])
        with tempfile.TemporaryDirectory() as tmp:
            baseline = load_baseline(write_baseline(res, Path(tmp) / 'b.json'))
        self.assertEqual(template_warnings(res, baseline), [])
        stages['d1'][0]['actions'][0]['timeMs'] = 100      # e.g. a per-action time appears in a patch
        res = scan(BASE, BASE.__getitem__) | scan_stages(stages)
        self.assertEqual(template_warnings(res, baseline),
                         ['unknown-field: AssemblyLineStages.stages[].actions[].timeMs (1 templates), not read by the '
                          'extractor'])


class EnumTests(unittest.TestCase):
    TEMPLATES = {
        'ItemTemplate': {'a': {'flags': 'AL_STARTER | BURNABLE', 'toggleableModeType': 'None'},
                         'b': {'flags': 'BURNABLE', 'toggleableModeType': ''},
                         'c': {}},
        'BuildableObjectTemplate': {'m': {'type': 'Producer', 'producerRecipeType': 'Tags'},
                                    'n': {'type': 'Producer', 'powerComponentType': 'Consumer'}},
    }

    def load(self, t):
        if t not in self.TEMPLATES:
            raise TemplateLoadError(f'missing template folder {t}')
        return self.TEMPLATES[t]

    def test_enum_values(self):
        v = enum_values(self.load)
        # flag fields ('|' in ENUM_FIELDS) are split; empty strings are values too, missing keys are not
        self.assertEqual(v['ItemTemplate.flags'], {'AL_STARTER': 1, 'BURNABLE': 2})
        self.assertEqual(v['ItemTemplate.toggleableModeType'], {'': 1, 'None': 1})
        self.assertEqual(v['BuildableObjectTemplate.type'], {'Producer': 2})
        self.assertEqual(v['BuildableObjectTemplate.producerRecipeType'], {'Tags': 1})
        self.assertEqual(v['BuildableObjectTemplate.poleGridType'], {})
        # types that fail to load are skipped (scan() reports them)
        self.assertNotIn('ResearchTemplate.flags', v)
        self.assertEqual({k.split('.')[0] for k in v}, {'ItemTemplate', 'BuildableObjectTemplate'})

    def test_enum_warnings(self):
        known = {'enumValues': {'ItemTemplate.flags': ['BURNABLE', 'GONE'], 'BuildableObjectTemplate.type': ['Producer'],
                                'ItemTemplate.toggleableModeType': ['', 'None']}}
        values = {'ItemTemplate.flags': {'AL_STARTER': 1, 'BURNABLE': 2}, 'BuildableObjectTemplate.type': {'Producer': 2},
                  'ItemTemplate.toggleableModeType': {'': 1, 'None': 1}, 'ResearchTemplate.researchContext': {'X': 3}}
        self.assertEqual(enum_warnings(values, known), [
            'new-enum-value: ItemTemplate.flags = AL_STARTER (1 templates)',
            'removed-enum-value: ItemTemplate.flags = GONE',
            'new-enum-value: ResearchTemplate.researchContext = X (3 templates)'])
        self.assertEqual(enum_warnings({k: v for k, v in values.items() if k != 'ResearchTemplate.researchContext'},
                                       {'enumValues': {**known['enumValues'], 'ItemTemplate.flags': ['AL_STARTER',
                                                                                                    'BURNABLE']}}), [])
        self.assertEqual(enum_warnings(values, None), [])        # template_warnings already reports the missing baseline
        w = enum_warnings(values, {'types': {}})
        self.assertEqual(len(w), 1)
        self.assertTrue(w[0].startswith('baseline: known_templates.json has no enumValues'), w)

    def test_round_trip_through_baseline(self):
        res = scan(self.TEMPLATES, self.TEMPLATES.__getitem__)
        v = enum_values(self.load)
        with tempfile.TemporaryDirectory() as tmp:
            b = load_baseline(write_baseline(res, Path(tmp) / 'b.json', enums=v))
        self.assertEqual(b['enumValues']['ItemTemplate.flags'], ['AL_STARTER', 'BURNABLE'])
        self.assertEqual(list(b['enumValues']), sorted(b['enumValues']))
        self.assertEqual(enum_warnings(v, b), [])


class BaselineFileTests(unittest.TestCase):
    def test_round_trip_stable_and_sorted(self):
        res = scan(BASE, BASE.__getitem__)
        with tempfile.TemporaryDirectory() as tmp:
            p1 = write_baseline(res, Path(tmp) / 'a' / 'b.json', game_version='0.6.0.1', template_source='S')
            # same content from a differently ordered scan -> identical bytes
            rev = dict(reversed(list(res.items())))
            p2 = write_baseline(rev, Path(tmp) / 'c.json', game_version='0.6.0.1', template_source='S')
            self.assertEqual(p1.read_bytes(), p2.read_bytes())
            b = load_baseline(p1)
            self.assertIsNone(load_baseline(Path(tmp) / 'missing.json'))
        self.assertEqual(b['gameVersion'], '0.6.0.1')
        self.assertEqual(b['templateSource'], 'S')
        self.assertEqual(list(b['types']), sorted(b['types']))
        self.assertEqual(b['types']['QuestTemplate'], {'count': 1, 'fields': ['identifier', 'steps', 'steps[].goal',
                                                                                 'title']})
        self.assertEqual(b['typeCount'], 2)
        self.assertEqual(b['fieldCount'], sum(len(v['fields']) for v in b['types'].values()))


PREV = {'gameVersion': '0.6.0.100', 'files': {'items.json': {'count': 100, 'sha256': 'x'},
                                              'quests.json': {'count': 0, 'sha256': 'x'},
                                              'old.json': {'count': 5, 'sha256': 'x'}}}


class CountWarningTests(unittest.TestCase):
    def files(self, items: int, quests: int = 0) -> dict:
        return {'items.json': {'count': items}, 'quests.json': {'count': quests}, 'old.json': {'count': 5},
                'brand_new.json': {'count': 7}}

    def test_threshold(self):
        self.assertEqual(count_warnings(PREV, self.files(119), {}), [])
        self.assertEqual(count_warnings(PREV, self.files(81), {}), [])
        self.assertEqual(count_warnings(PREV, self.files(120), {}), [])   # exactly 20 % is not > 20 %
        self.assertEqual(count_warnings(PREV, self.files(121), {}),
                         ['count-change: items.json 100 -> 121 (+21.0 %) vs v0.6.0.100'])
        self.assertEqual(count_warnings(PREV, self.files(79), {}),
                         ['count-change: items.json 100 -> 79 (-21.0 %) vs v0.6.0.100'])
        self.assertEqual(count_warnings(PREV, self.files(119), {}, threshold=0.1),
                         ['count-change: items.json 100 -> 119 (+19.0 %) vs v0.6.0.100'])

    def test_zero_to_some_vanished_and_label(self):
        files = self.files(100, quests=3)
        del files['old.json']
        self.assertEqual(count_warnings(PREV, files, {}, prev_name='v0.6.0.100-x'), [
            'count-change: old.json 5 -> 0 (missing) vs v0.6.0.100-x',
            'count-change: quests.json 0 -> 3 (new) vs v0.6.0.100-x'])

    def test_no_previous(self):
        self.assertEqual(count_warnings(None, self.files(1), {'T': 1}), [])
        self.assertEqual(count_warnings({}, self.files(1), {'T': 1}), [])

    def test_template_counts(self):
        prev = {**PREV, 'templateCounts': {'ItemTemplate': 500, 'QuestTemplate': 26, 'GoneTemplate': 2, 'Same': 3}}
        cur = {'ItemTemplate': 400, 'QuestTemplate': 30, 'Same': 3, 'NewTemplate': 9}
        # ItemTemplate -20.0 % (not > 20 %), QuestTemplate +15.4 %, NewTemplate not in prev -> only the vanished type
        self.assertEqual(count_warnings(prev, self.files(100), cur),
                         ['count-change: GoneTemplate 2 -> 0 (missing) vs v0.6.0.100'])
        cur['ItemTemplate'] = 399
        self.assertEqual(count_warnings(prev, self.files(100), cur), [
            'count-change: GoneTemplate 2 -> 0 (missing) vs v0.6.0.100',
            'count-change: ItemTemplate 500 -> 399 (-20.2 %) vs v0.6.0.100'])

    def test_old_manifest_without_template_counts(self):
        self.assertEqual(count_warnings(PREV, self.files(100), {'ItemTemplate': 1}), [])


class PreviousVersionTests(unittest.TestCase):
    def make_out(self, root: Path, versions: list[str], manifests: list[str]) -> None:
        index = {'latest': versions[-1], 'versions': [{'version': v, 'gameVersion': v[1:]} for v in versions]}
        (root / 'index.json').write_text(json.dumps(index), encoding='utf-8')
        for v in manifests:
            (root / v).mkdir()
            (root / v / 'manifest.json').write_text(json.dumps({'gameVersion': v[1:], 'files': {}}), encoding='utf-8')

    def test_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(previous_version(root, 'v0.6.0.10'))       # no index.json
            self.make_out(root, ['v0.5.0.1', 'v0.6.0.2', 'v0.6.0.10', 'v0.6.0.9', 'v0.7.0.1'],
                          ['v0.5.0.1', 'v0.6.0.2', 'v0.6.0.10', 'v0.7.0.1'])
            name, man = previous_version(root, 'v0.6.0.10')
            # numeric sort (10 > 9 > 2); v0.6.0.9 is skipped because it has no manifest.json
            self.assertEqual((name, man['gameVersion']), ('v0.6.0.2', '0.6.0.2'))
            self.assertEqual(previous_version(root, 'v0.8.0.1')[0], 'v0.7.0.1')    # current not in index yet
            self.assertEqual(previous_version(root, 'v0.7.0.1')[0], 'v0.6.0.10')
            self.assertIsNone(previous_version(root, 'v0.5.0.1'))                 # nothing older
            (root / 'index.json').write_text('{broken', encoding='utf-8')
            self.assertIsNone(previous_version(root, 'v0.7.0.1'))

    def test_version_key(self):
        names = ['v0.6.0.10', 'v0.6.0.9', 'v0.6.0', 'v0.6.0.beta', 'v1.0.0.1']
        self.assertEqual(sorted(names, key=version_key), ['v0.6.0', 'v0.6.0.9', 'v0.6.0.10', 'v0.6.0.beta', 'v1.0.0.1'])


class CommittedBaselineTests(unittest.TestCase):
    def test_committed_baseline_shape(self):
        b = load_baseline()
        self.assertIsNotNone(b, f'missing {checks.BASELINE_PATH}')
        self.assertEqual(b['format'], checks.BASELINE_FORMAT)
        self.assertTrue(b['gameVersion'])
        for t in EXPORTED_TYPES:
            self.assertIn(t, b['types'])
            self.assertIn('identifier', b['types'][t]['fields'], t)
        self.assertIn(STAGES_TYPE, b['types'])
        self.assertIn('stages', b['types'][STAGES_TYPE]['fields'])
        expected_enums = {f'{t}.{f.rstrip("|")}' for t, fs in ENUM_FIELDS.items() for f in fs}
        self.assertEqual(set(b['enumValues']), expected_enums)
        for k, vals in b['enumValues'].items():
            self.assertEqual(vals, sorted(set(vals)), k)
        self.assertEqual(b['typeCount'], len(b['types']))
        for t, v in b['types'].items():
            self.assertEqual(v['fields'], sorted(set(v['fields'])), t)

    def test_exported_types_cover_build(self):
        # every template type name build.py mentions must be in EXPORTED_TYPES (else its fields go unchecked)
        src = (Path(checks.__file__).parent / 'build.py').read_text(encoding='utf-8')
        used = {m for m in re.findall(r"'(\w+)'", src) if m in load_baseline()['types']}
        self.assertLessEqual(used, set(EXPORTED_TYPES))

    @require_game
    def test_current_game_matches_committed_baseline(self):
        """Same path as cmd_export: build.Data -> sources.open_template_source(mode='auto', types=EXPORTED_TYPES),
        checks.scan over that source + scan_stages(decoded AL stages), enum_values/enum_warnings."""
        from foundry_export.build import Data
        from foundry_export.game import locate
        d = Data(locate(GAME))
        res = scan(d.source.type_names(), d.source.load) | scan_stages(d.stages)
        baseline = load_baseline()
        w = template_warnings(res, baseline, template_source=d.source.label)
        w += enum_warnings(enum_values(d.source.load), baseline)
        self.assertEqual(w, [], f'game templates ({d.source.label}) differ from foundry_export/baseline/known_templates.json '
                                f'(baseline {baseline["gameVersion"]}); review the warnings, then accept them with '
                                '`python3 extractor/export baseline` (UPDATE.md step d)')
        counts = template_counts(res)
        self.assertLessEqual(set(EXPORTED_TYPES) | {STAGES_TYPE}, set(counts))
        self.assertEqual(counts[STAGES_TYPE], len(d.alots))
        self.assertEqual([x for x in d.warnings if x.startswith(('source-mismatch', 'stages asset'))], [])


if __name__ == '__main__':
    unittest.main()
