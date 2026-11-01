"""itemsheet: resolution, every value has a source, template sources really hold the value, 'ungemessen' marks follow
findings/open_questions.md, nothing in out/ changes."""
from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from _util import GAME, REPO, require_game, run_cli

from foundry_export.game import flags, locate, num, read_versions
from foundry_export.itemsheet import OPEN_QUESTIONS, Sheets, _oq_status, render_markdown
from foundry_export.steam import HINT_FILE, find_game

_TEMPLATE_SRC = re.compile(r'^Templates/(\w+)/([^ /]+\.yaml) : ([A-Za-z_][\w]*(?:\[\d+\]|\.[A-Za-z_]\w*)*)$')
_PART = re.compile(r'([A-Za-z_]\w*)|\[(\d+)\]')


def leaves(obj, path='$'):
    """(path, value-dict) for every {'value', 'source'} leaf."""
    if isinstance(obj, dict):
        if 'value' in obj and 'source' in obj:
            yield path, obj
            return
        for k, v in obj.items():
            yield from leaves(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f'{path}[{i}]')


def resolve_field(body, field: str):
    cur = body
    for name, idx in _PART.findall(field):
        cur = cur[name] if name else cur[int(idx)]
    return cur


def same(raw, value) -> bool:
    if value is None:
        return raw in (None, '', [])
    if isinstance(value, bool):
        return bool(raw) == value
    if isinstance(value, (int, float)):
        try:
            return num(raw) == value
        except (ValueError, TypeError):
            return False
    if isinstance(value, list) and isinstance(raw, str):
        return flags(raw) == value or [t.split('|')[0] for t in [raw]] == value
    if isinstance(value, list) and isinstance(raw, list):
        return [r.split('|')[0] if isinstance(r, str) else r for r in raw] == value
    return raw == value


def _v(x):
    return x['value'] if isinstance(x, dict) else x


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + b'\0' + p.read_bytes())
    return h.hexdigest()


@require_game
class ItemSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loc = find_game(str(GAME), hint_file=HINT_FILE)
        gp = locate(loc.root)
        cls.sheets = Sheets(gp, read_versions(gp, loc))
        cls.robot = cls.sheets.sheet('Operator Robot')
        cls.building = cls.sheets.sheet('Assembler I')
        cls.item = cls.sheets.sheet('_base_ore_xenoferrite')
        cls.caster = cls.sheets.sheet('Heavy Caster')
        cls.extra = {q: cls.sheets.sheet(q, k) for q, k in (
            ('_base_biomass', None), ('_base_space_ship_fuel', None), ('_base_alien_scrap_i', None), ('_base_firmarlite_sheet', None),
            ('_base_admin_bot_i', 'item'), ('_base_science_pack_i', None), ('_base_power_core_i', None), ('_base_robot_01', 'item'),
            ('_base_al_producer_i', None), ('_base_al_painter_i', None), ('_base_al_rail_curve_left', None),
            ('_base_casting_building_input', None), ('_base_baseStation01', None), ('_base_boreal_forest_tree_01', None),
            ('_base_burner_generator_lvg', None), ('_base_wd_ore_large_xf', 'building'))}
        cls.all = {'robot': cls.robot, 'building': cls.building, 'item': cls.item, 'caster': cls.caster, **cls.extra}

    def test_resolution(self):
        r = self.sheets.resolve
        self.assertEqual(r('Operator Robot')[:2], ('robot', '_base_admin_robot_i'))
        self.assertIn('item _base_admin_robot_i', r('Operator Robot')[2])
        self.assertEqual(r('Operator Robot', 'item')[:2], ('item', '_base_admin_robot_i'))
        self.assertEqual(r('Assembler I')[:2], ('building', '_base_assembler_i'))
        self.assertEqual(r('Fertiger I')[:2], ('building', '_base_assembler_i'))          # German name
        self.assertEqual(r('_BASE_ORE_XENOFERRITE')[:2], ('item', '_base_ore_xenoferrite'))
        self.assertEqual(r('Heavy Caster')[:2], ('building', '_base_casting_building_base'))
        self.assertEqual(r('Assembly Line Rail')[:2], ('building', '_base_al_rail_straight'))
        self.assertEqual(r('Xenoferrite Ore')[:2], ('item', '_base_ore_xenoferrite'))        # hidden world-decor items step back
        self.assertEqual(r('Curve Left (HVG Connector)')[:2], ('building', '_base_al_rail_curve_left'))   # mode name
        with self.assertRaises(LookupError):
            r('   ')
        with self.assertRaises(LookupError):
            r('Robot')                       # many robots/items contain it
        with self.assertRaises(LookupError):
            r('definitely no such thing')

    def test_every_value_has_a_source(self):
        for name, s in self.all.items():
            n = 0
            for path, v in leaves(s):
                n += 1
                self.assertTrue(v['source'], f'{name} {path}: empty source')
                if v['value'] not in (None, [], {}):
                    self.assertNotEqual(v['source'].strip(), '–', f'{name} {path}: value {v["value"]!r} without source')
            self.assertGreater(n, 20, name)

    def test_item_branches(self):
        x = self.extra
        self.assertEqual({_v(m['machine']) for m in x['_base_biomass']['fuel']['machines']},
                         {'_base_biomass_burner', '_base_boiler_i', '_base_burner_generator_lvg'})
        self.assertIn('Nr. 13', x['_base_space_ship_fuel']['fuel']['fuelValueKJ']['ungemessen'])
        self.assertFalse(x['_base_space_ship_fuel']['fuel']['burnable']['value'])
        self.assertTrue(x['_base_alien_scrap_i']['explorationRequirements'])
        self.assertTrue(x['_base_alien_scrap_i']['item']['explorationFlavorText'])
        self.assertEqual([(_v(q['quest']), _v(q['amount'])) for q in x['_base_firmarlite_sheet']['quests']], [('_base_sq_lava_caves', 50)])
        self.assertEqual(x['_base_admin_bot_i']['sales']['basePrice']['value'], 109)
        self.assertEqual(len(x['_base_science_pack_i']['researchCosts']), len(self.sheets.research))
        self.assertTrue(any(g['how'] == 'Sonderfund beim Abbau' for g in x['_base_power_core_i']['gathering']),
                        'power cores drop from xeno scrap (worldDecor_specialDrops)')
        self.assertIn('Nr. 10', x['_base_robot_01']['workstation']['bonusPercent']['ungemessen'])
        self.assertEqual(x['_base_robot_01']['workstation']['bonusPercent']['value'], 25)

    def test_building_branches(self):
        x = self.extra
        self.assertIn('Nr. 7', x['_base_al_producer_i']['power']['peakPowerKW']['ungemessen'])
        self.assertEqual(x['_base_al_producer_i']['power']['energyPerActionKJ']['value'], [200, 500])
        self.assertEqual(x['_base_al_painter_i']['power']['energyPerObjectKJ']['value'], [425])
        self.assertEqual(x['_base_al_rail_curve_left']['building']['modeName']['value'], 'Curve Left (HVG Connector)')
        self.assertTrue(x['_base_casting_building_input']['moduleCost']['cost'])
        self.assertTrue(all(m['cost'] for m in self.caster['connections']['modules']))
        base = x['_base_baseStation01']['crafting']
        self.assertIn('Nr. 14', base['speedMultiplier']['ungemessen'])
        self.assertTrue(all('ungemessen' in r['craftTimeSec'] for r in base['recipes']))
        self.assertIn('Nr. 12', x['_base_boreal_forest_tree_01']['building']['names']['de']['ungemessen'])
        self.assertIn('worldDecor_miningYield', x['_base_boreal_forest_tree_01']['typeFields'])
        self.assertIn('lvgGenerator_transmissionRate_kjPerS_str', x['_base_burner_generator_lvg']['power'])
        self.assertNotIn('ungemessen', self.building['power']['workstationEffectTags'])
        self.assertIn('Nr. 10', self.building['power']['workstationBonus']['ungemessen'])

    def test_template_sources_hold_the_value(self):
        """Every 'Templates/<Type>/<file> : <field>' source: the YAML file has that field with that value."""
        tdir = self.sheets.gp.templates
        cache, checked, bad = {}, 0, []
        for name, s in self.all.items():
            for path, v in leaves(s):
                m = _TEMPLATE_SRC.match(v['source'])
                if not m or isinstance(v['value'], dict):
                    continue
                t, f, field = m.groups()
                key = (t, f)
                if key not in cache:
                    doc = yaml.load((tdir / t / f).read_text(encoding='utf-8'), Loader=yaml.CSafeLoader)
                    cache[key] = next(iter(doc[t].values()))
                try:
                    raw = resolve_field(cache[key], field)
                except (KeyError, IndexError, TypeError):
                    bad.append(f'{name} {path}: {v["source"]} - field missing')
                    continue
                checked += 1
                if not same(raw, v['value']):
                    bad.append(f'{name} {path}: {v["source"]} = {raw!r}, sheet says {v["value"]!r}')
        self.assertGreater(checked, 300)
        self.assertFalse(bad, f'{len(bad)} of {checked} template sources do not match:\n  ' + '\n  '.join(bad[:30]))

    def test_ungemessen_marks(self):
        char = next(p for r in self.building['buildCost'] for p in r['producers'] if p['kind']['value'] == 'Character')
        self.assertIn('Nr. 1', char['craftTimeSec']['ungemessen'])
        self.assertIn('Nr. 1', char['perMinute']['outputs'][0]['perMin']['ungemessen'])
        machine = next(p for r in self.building['buildCost'] for p in r['producers'] if p['machine']['value'] == '_base_assembler_i')
        self.assertNotIn('ungemessen', machine['craftTimeSec'])
        self.assertIn('Nr. 3', self.caster['crafting']['speedMultiplier']['ungemessen'])
        self.assertIn('Nr. 4', self.robot['throughput']['singleStartObjectsPerMinute']['ungemessen'])
        self.assertIn('Nr. 5', self.robot['energy']['painterPowerKJ']['ungemessen'])
        self.assertIn('Nr. 7', self.robot['stages'][0]['actions'][0]['peakPowerKW']['ungemessen'])
        self.assertNotIn('ungemessen', self.robot['energy']['startPowerKJ'])
        for r in self.item['recipesProducing']:
            for p in r['producers']:
                self.assertNotIn('ungemessen', p['craftTimeSec'], 'crusher rates come from templates + UI formula')

    def test_ungemessen_follows_open_questions_status(self):
        text = OPEN_QUESTIONS.read_text(encoding='utf-8')
        measured = re.sub(r'^(\| 1 \|[^|]*\|[^|]*\|)[^|]*\|', r'\1 gemessen |', text, count=1, flags=re.M)
        self.assertNotEqual(measured, text)
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'open_questions.md'
            p.write_text(measured, encoding='utf-8')
            old = self.sheets.oq
            try:
                self.sheets.oq = _oq_status(p)
                s = self.sheets.sheet('Assembler I')
            finally:
                self.sheets.oq = old
        char = next(p for r in s['buildCost'] for p in r['producers'] if p['kind']['value'] == 'Character')
        self.assertNotIn('ungemessen', char['craftTimeSec'])

    def test_content(self):
        it = self.item
        self.assertEqual(it['item']['stackSize']['value'], 200)
        self.assertEqual(it['item']['names']['de']['value'], 'Xenoferrit-Erz')
        self.assertEqual({r['identifier']['value'] for r in it['recipesProducing']}, {'_base_ore_xenoferrite', '_base_ore_xenoferrite_crystals'})
        self.assertTrue(it['recipesUsing'])
        self.assertTrue(any(g['how'].startswith('Abbau Terrain') for g in it['gathering']))
        self.assertTrue(it['blastFurnace'])
        self.assertFalse([r for r in it['otherReferences'] if r['type'] == 'CraftingRecipe' and r['field'] == 'identifier'],
                         'same-named recipe identifiers must not show up as item references')
        b = self.building
        self.assertEqual(b['building']['tier']['value'], 'I')
        self.assertEqual(b['power']['energyConsumptionKW_str']['value'], 50)
        self.assertEqual(len(b['crafting']['recipes']), len(self.sheets.machines['_base_assembler_i']['crafting']['derived']['recipes']))
        self.assertEqual([r['identifier']['value'] for r in b['buildCost']], ['_base_assembler_i'])
        ro = self.robot
        self.assertEqual(ro['robot']['starterItem']['value'], '_base_admin_robot_01_torso')
        self.assertEqual(len(ro['stages'][0]['actions']), 10)
        self.assertEqual(ro['energy']['totalPowerKJ']['value'], 3975)
        self.assertEqual(ro['sales']['basePrice']['value'], 999)
        self.assertEqual(ro['sales']['baseDemandPerDay']['value'], 600)

    def test_markdown(self):
        for name, s in self.all.items():
            md = render_markdown(s)
            self.assertIn('| Feld | Wert | Quelle |', md, name)
            self.assertNotIn('None', md, name)
        self.assertIn('**ungemessen**', render_markdown(self.robot))
        for name, s in self.all.items():   # every table row has as many cells as its header
            for block in render_markdown(s).split('\n\n'):
                rows = [ln for ln in block.splitlines() if ln.startswith('|') and not re.fullmatch(r'\|(-+\|)+', ln)]
                if rows:
                    n = rows[0].count(' | ')
                    self.assertTrue(all(r.replace('\\|', '').count(' | ') == n for r in rows), f'{name}: {rows[0][:60]}')

    def test_cli_writes_files_and_leaves_out_unchanged(self):
        out = REPO / 'out'
        before = tree_hash(out) if out.exists() else None
        with tempfile.TemporaryDirectory() as t:
            code, msg = run_cli(['itemsheet', '--game', str(GAME), '--out', t, 'Assembler', 'I'])
            self.assertEqual(code, 0, msg)
            self.assertTrue((Path(t) / '_base_assembler_i.building.md').exists())
            self.assertTrue((Path(t) / '_base_assembler_i.building.json').exists())
            code, msg = run_cli(['itemsheet', '--game', str(GAME), 'Robot'])
            self.assertEqual(code, 1)
            self.assertIn('mehrdeutig', msg)
        if before is not None:
            self.assertEqual(tree_hash(out), before, 'itemsheet must not change out/')


if __name__ == '__main__':
    unittest.main()
