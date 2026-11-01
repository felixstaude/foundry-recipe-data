"""Data sheet for one item, building or assembly-line robot ('export itemsheet <identifier-or-name>').

Collects everything a wiki page needs and attaches a source to every value:
  * template values:  'Templates/<Type>/<identifier>.yaml : <field path>'  (or 'foundry_main_bundle:<Type>/<id>' in bundle mode)
  * translations:     'locale/<lang>/LC_MESSAGES/foundry_templates-<lang>.mo : <key>'
  * computed values:  'berechnet: <formula> (<code it follows>)'
Values that follow only from code or disassembly and are not yet measured in game carry 'ungemessen' with the number
of the point in findings/open_questions.md; the status is read from the table there (status 'gemessen' -> no flag).

The sheet is built from the same loading chain as the export (build.Data / build_all) and changes nothing.
JSON: plain data with {"value": ..., "source": ...} leaves. Markdown: rendered from the same data.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .build import CHARACTER_MACHINE_ID, RAIL_ITEM_LENGTH, TICKS_PER_SECOND, Data, _machine_names, build_all
from .game import flags, num, text
from .localization import key as lkey
from .localization import load_catalogs

OPEN_QUESTIONS = Path(__file__).resolve().parents[2] / 'findings' / 'open_questions.md'
KINDS = ('item', 'building', 'robot')

# points in findings/open_questions.md the values depend on
OQ_CHARACTER, OQ_CHARACTER_BONUS, OQ_HEAVY_CASTER, OQ_AL_THROUGHPUT, OQ_AL_PAINTER, OQ_AL_ORDER, OQ_AL_POWER = 1, 2, 3, 4, 5, 6, 7
OQ_RESEARCH, OQ_WORKSTATION, OQ_NAMES, OQ_FUEL, OQ_BASE_STATION = 9, 10, 12, 13, 14

CALC_RATE = 'berechnet: amount × chance × 60 / craftTimeSec (CraftingRecipe.getItemsPerMinute)'
CALC_TIME = ('berechnet: timeMs / 1000 / speedMultiplier (ProducerGO.getProducerCraftTimeInMsFPM). Simulation: Dauer in 1/10⁴ Tick, '
             'Rest wird beim Abschluss übertragen, Neustart im selben Tick, also keine Rundung auf ganze Ticks (FoundryNative.dll '
             'ProducerEntity::tryStartProduction / tryFinishProduction / tickUpdate); '
             'Umrechnung mit 166666 statt 166666,67: ≈ 4 ppm länger, nicht eingerechnet')
CALC_TIME_CHARACTER = ('berechnet: Ticks = max(1, trunc(round(trunc(round(timeMs·10⁸/30000)/1000)·600000/10⁴)/10⁴)), Zeit = Ticks/60 '
                       '(FoundryNative.dll CraftingAction::reinitialize: /3 gerundet, /1000 abgeschnitten, '
                       '×60 gerundet, auf ganze Ticks abgeschnitten; CraftingQueue::tickUpdate zählt 1 je Tick, kein Leer-Tick '
                       'zwischen Aufträgen; der Tooltip zeigt timeMs / 5)')
CALC_TIME_BASE = 'berechnet: ganze Ticks trunc(trunc(timeMs·10⁸/166666)/10⁴) / 60 (FoundryNative.dll BaseStationFurnace::tickUpdate)'
CHARACTER_SRC = 'Export-Konvention: Pseudo-Maschine "character" für Handwerk (Rezept-Tag "character")'
SPEED_FIELD = {'Producer': 'producer_recipeTimeModifier_str', 'AutoProducer': 'autoProducer_recipeTimeModifier_str',
               'ModularEntityProducer': 'modularProducer_recipeTimeModifier_str'}
TAG_FIELD = {'Producer': 'producer_recipeType_tags', 'AutoProducer': 'autoProducer_recipeType_tag',
             'ModularEntityProducer': 'modularProducer_recipeType_tags'}
FIXED_FIELD = {'Producer': 'producer_recipeType_fixed', 'ModularEntityProducer': 'modularProducer_fixedCraftingRecipeIdentifier'}
AL_SPEED_FIELD = {'AL_Start': 'al_start_speedInSlotsPerTick', 'AL_Rail': 'al_rail_speedInSlotsPerTick',
                  'AL_Producer': 'al_producer_speedInSlotsPerTick', 'AL_Merger': 'al_merger_speedInSlotsPerTick',
                  'AL_Splitter': 'al_splitter_speedInSlotsPerTick'}
ROMAN = {'i': 'I', 'ii': 'II', 'iii': 'III', 'iv': 'IV', 'v': 'V', 'vi': 'VI'}
# building fields shown for every building (beyond the type-specific ones)
POWER_FIELDS = ('powerComponentType', 'powerSubType', 'energyConsumptionKW_str', 'spp_gridCheckType', 'hasEnergyGridConnection',
                'hasPoleGridConnection', 'poleGridType', 'poleGrid_connectionRange', 'poleGrid_maxConnections',
                'poleGridConnectionMatrix')
# type-specific field prefixes that do not follow the 'lowerCamelType' rule
EXTRA_PREFIXES = {
    'ModularEntityProducer': ('modularProducer_', 'modularBuilding'), 'ModularEntityModule': ('modularBuildingModule', 'modularBuilding'),
    'LvgGenerator': ('lvgGenerator_', 'powerProducer'), 'BurnerGenerator': ('burnerGenerator', 'powerProducer'),
    'AL_Start': ('al_start_', 'alStart_'), 'AL_Rail': ('al_rail_',), 'AL_Producer': ('al_producer_',),
    'AL_EndConsumer': ('al_endConsumer_', 'alcm_'), 'AL_Merger': ('al_merger_',), 'AL_Splitter': ('al_splitter_',),
    'PowerPole': ('poleGrid',), 'Transformer': ('transformer', 'poleGrid'), 'Battery': ('battery_',),
    'NPP_CoolingTower': ('nppCoolingTower_', 'resourceConverter_'), 'NPP_Reactor': ('nppReactor_',),
    'NPP_SteamTurbine': ('nppSteamTurbine_', 'nppSteamGenerator_', 'powerProducer'),
    'ResourceConverter': ('resourceConverter_', 'nppSteamGenerator_'), 'RadioTower': ('resourceConverter_', 'radioTower'),
    'WorldDecorMineAble': ('worldDecor_',), 'ResourceNode': ('worldDecor_',), 'OreVeinMiner': ('oreVeinMiner', 'minecartDepot_'),
    'FrackingTower': ('frackingTower', 'resourceConverter_'), 'Pump': ('pumpjack',),
    'ConstructionWarehouse': ('constructionWarehouse', 'constructionDronePort'),
    'TransportDronePort': ('transportDronePort', 'constructionDronePort'), 'StationShuttlePad': ('droneTransport',),
    'TrainStation': ('trainStation', 'trainLoadingStation', 'trainTrackLinkable'),
    'TrainLoadingStation': ('trainLoadingStation', 'trainTrackLinkable')}
POWER_LABELS = {'powerComponentType': 'Stromkomponente', 'powerSubType': 'Strom-Rolle', 'energyConsumptionKW_str': 'Verbrauch (kW)',
                'spp_gridCheckType': 'Netztyp', 'hasEnergyGridConnection': 'Anschluss Energienetz',
                'hasPoleGridConnection': 'Anschluss Strommast-Netz', 'poleGridType': 'Strommast-Netz: Rolle',
                'poleGrid_connectionRange': 'Strommast-Netz: Reichweite', 'poleGrid_maxConnections': 'Strommast-Netz: max. Verbindungen',
                'poleGridConnectionMatrix': 'Strommast-Netz: verbindbar mit'}
_POWER_FIELD = re.compile(r'(?i)power|energy|kjPer|_kW|capacityKJ|transmissionRate')
# what a template field refers to; references with another target are only identifier collisions
# (items, recipes, research and buildings often share one identifier)
REF_TARGET = [(re.compile(t), re.compile(f), k) for t, f, k in (
    (r'.', r'^identifier$', 'self'),
    (r'^AchievementDatabaseTemplate$', r'research', 'research'),
    (r'^CraftingRecipe$', r'^((input|output)_data\[\d+\]\.identifier|relatedItemTemplateIdentifier)$', 'item'),
    (r'^ResearchTemplate$', r'^list_craftingUnlocks_str\[\d+\]$', 'recipe'),
    (r'^ResearchTemplate$', r'^list_researchDependencies_str\[\d+\]$', 'research'),
    (r'^ResearchTemplate$', r'^list_alots_str\[\d+\]$', 'robot'),
    (r'^ResearchTemplate$', r'^(input_data\[\d+\]\.identifier|list_\w+ItemVisibility_str\[\d+\])$', 'item'),
    (r'^ExplorationUnlockTemplate$', r'^craftingRecipeUnlocks_identifier\[\d+\]$', 'recipe'),
    (r'^ExplorationUnlockTemplate$', r'^requirements\[\d+\]\.itemTemplateIdentifier$', 'item'),
    (r'^ExplorationUnlockTemplate$', r'^researchDepedencies', 'research'),
    (r'^ItemTemplate$', r'^(buildableObjectIdentifer|toggleableModes\[\d+\]\.identifier)$', 'building'),
    (r'^ItemTemplate$', r'^(altRecipeIdentifier|autoProducerRecipes\[\d+\]\.recipeIdentifier)$', 'recipe'),
    (r'^ItemTemplate$', r'^alStarter_alotIdentifier$', 'robot'),
    (r'^ItemTemplate$', r'^(alStarter_sellItemTemplateIdentifier|burnable_residualItemTemplate_str)$', 'item'),
    (r'^AssemblyLineProducerActionTemplate$', r'^requiredItems\[\d+\]\.identifier$', 'item'),
    (r'^BlastFurnaceModeTemplate$', r'^input_data\[\d+\]\.identifier$', 'item'),
    (r'^QuestTemplate$', r'^conditions\[\d+\]\.identifier01$', 'quest'),
    (r'^BuildableObjectTemplate$', r'^(producer_recipeType_fixed|modularProducer_fixedCraftingRecipeIdentifier|'
                                   r'baseStation_craftingRecipeIdentifier\[\d+\])$', 'recipe'),
)]
# references shown in their own section of a sheet
COVERED = {'item': re.compile(r'^(CraftingRecipe:(input|output)_data|CraftingRecipe:relatedItemTemplateIdentifier|'
                              r'ResearchTemplate:input_data|ExplorationUnlockTemplate:requirements|QuestTemplate:|'
                              r'TerrainBlockType:yieldItemOnDig|BuildableObjectTemplate:worldDecor_miningYield|'
                              r'AssemblyLineProducerActionTemplate:requiredItems|BlastFurnaceModeTemplate:input_data|'
                              r'ItemTemplate:alStarter_sellItemTemplateIdentifier|ItemTemplate:recyclingData|'
                              r'BuildableObjectTemplate:(worldDecor_specialDrops|endlessMiner_outputTemplateIdentifier|'
                              r'oreVeinMineable_yieldItem_identifier))'),
           'building': re.compile(r'^(ItemTemplate:(buildableObjectIdentifer|toggleableModes)|QuestTemplate:)')}


def ref_target(type_name: str, field: str) -> str | None:
    return next((k for t, f, k in REF_TARGET if t.search(type_name) and f.search(field)), None)


_SKIP_FIELD = re.compile(r'(?i)prefab|audio|sound|mesh|color|offset|icon|material|debris|walkway|snap|drag|render|'
                         r'quaternion|position|anchor|collider|uiDescription')


def _oq_status(path: Path = OPEN_QUESTIONS) -> dict[int, dict]:
    """{Nr: {'title', 'status', 'measuredIn'}} from the table in findings/open_questions.md ({} if missing)."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding='utf-8').splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if line.startswith('|') and len(cells) == 6 and cells[0].isdigit():
            out[int(cells[0])] = {'title': cells[1].replace('**', ''), 'status': cells[3], 'measuredIn': cells[4]}
    return out


def _paths(v, target: str, prefix: str = ''):
    """Field paths below v whose string value is target (or 'target|guid')."""
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _paths(x, target, f'{prefix}.{k}' if prefix else str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _paths(x, target, f'{prefix}[{i}]')
    elif isinstance(v, str) and (v == target or v.split('|', 1)[0] == target):
        yield prefix


class Sheets:
    """Loads the game once; builds sheets for any number of queries."""

    def __init__(self, gp, ver: dict, source_mode: str = 'auto', oq_path: Path = OPEN_QUESTIONS):
        self.gp, self.ver = gp, ver
        self.d = Data(gp, source_mode)
        header = {'gameVersion': ver['gameVersion'], 'steamBuildId': ver['steamBuildId']}
        docs = build_all(self.d, header)
        self.catalogs = load_catalogs(gp.locale)
        self.names = _machine_names(self.d)
        self.items = {x['identifier']: x for x in docs['items.json']['items']}
        self.recipes = {x['identifier']: x for x in docs['recipes.json']['recipes']}
        self.machines = {x['identifier']: x for x in docs['machines.json']['machines']}
        rdoc = docs['research.json']
        self.research = {x['identifier']: x for x in rdoc['research']}
        self.exploration = {x['identifier']: x for x in rdoc['explorationUnlocks']}
        self.al = docs['assembly_line.json']
        self.alobjects = {x['identifier']: x for x in self.al['objects']}
        self.almachines = {x['identifier']: x for x in self.al['machines']}
        self.oq = _oq_status(oq_path)
        self.oq_missing = not oq_path.exists()
        self._files: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------ sources and values

    def file(self, type_name: str, ident: str) -> str:
        if self.d.source.kind != 'yaml':
            return f'foundry_main_bundle:{type_name}/{ident}'
        folder = self.gp.templates / type_name
        if (folder / f'{ident}.yaml').exists():
            return f'Templates/{type_name}/{ident}.yaml'
        if type_name not in self._files:  # file name differs from the identifier: look it up once
            idx = {}
            for f in sorted(folder.glob('*.yaml')):
                m = re.search(r'^    identifier: (.+)$', f.read_text(encoding='utf-8'), re.M)
                if m:
                    idx[m.group(1).strip()] = f.name
            self._files[type_name] = idx
        return f'Templates/{type_name}/{self._files[type_name].get(ident, ident + ".yaml")}'

    def src(self, type_name: str, ident: str, field: str) -> str:
        return f'{self.file(type_name, ident)} : {field}'

    def V(self, value, source: str, oq: int | tuple | None = None, note: str | None = None) -> dict:
        v = {'value': value, 'source': source}
        for n in ((oq,) if isinstance(oq, int) else (oq or ())):
            info = self.oq.get(n)
            if info is None or info['status'] != 'gemessen':
                label = f'findings/open_questions.md Nr. {n}' + (f': {info["title"]} (Status: {info["status"]})' if info else '')
                v['ungemessen'] = (v['ungemessen'] + '; ' + label) if 'ungemessen' in v else label
        if note:
            v['note'] = note
        return v

    def _raw(self, type_name: str, ident: str) -> dict:
        return self.d.source.load(type_name).get(ident, {})

    def loc(self, type_name: str, ident: str, field: str, path=()) -> dict:
        """{lang: V(text, .mo key)} for every language that has the key."""
        k = lkey(type_name, ident, field, list(path))
        return {lang: self.V(cat[k], f'locale/{lang}/LC_MESSAGES/foundry_templates-{lang}.mo : {k}')
                for lang, cat in sorted(self.catalogs.items()) if k in cat}

    def item_name(self, iid: str) -> dict:
        return self.V(self._raw('ItemTemplate', iid).get('name'), self.src('ItemTemplate', iid, 'name'))

    def name_of(self, type_name: str, ident: str, field: str = 'name') -> dict:
        return self.V(self._raw(type_name, ident).get(field), self.src(type_name, ident, field))

    def references(self, target: str, skip_self: tuple[str, str] | None = None) -> list[dict]:
        """Every template field (any type) whose value is target."""
        out = []
        for t in self.d.source.type_names():
            try:
                tpls = self.d.source.load(t)
            except (Exception, SystemExit):  # noqa: BLE001 - reported by the export
                continue
            for ident, body in tpls.items():
                for p in _paths(body, target):
                    if (t, ident) == skip_self and p == 'identifier':
                        continue
                    out.append({'type': t, 'identifier': ident, 'field': p, 'source': self.src(t, ident, p)})
        return out

    # ------------------------------------------------------------ resolving the query

    def resolve(self, query: str, kind: str | None = None) -> tuple[str, str, list[str]]:
        """-> (kind, identifier, other matches). Exact identifier, then exact name (any language), then a unique
        substring of a name. Same match in several kinds: robot > building > item (others are listed)."""
        q = query.strip().casefold()
        cands: dict[tuple[str, str], set[str]] = defaultdict(set)   # (kind, id) -> names

        def add(k, ident, *nms):
            cands[(k, ident)].update(n.casefold() for n in nms if n)
        for aid, a in self.d.alots.items():
            add('robot', aid, aid, a.get('name'), *self._loc_texts('AssemblyLineObjectTemplate', aid, 'name'))
        for bid in self.d.bots:
            nm = self.names[bid]
            extra = self._loc_texts('BuildableObjectTemplate', bid, 'nameOverride') if nm['nameOverride'] else []
            if nm['modeName']:
                extra += [nm['modeName'], *self._loc_texts('ItemTemplate', nm['item'], 'name', [('toggleableModes', nm['modeIndex'])])]
            add('building', bid, bid, nm['name'], *extra)
        for iid, it in self.d.items.items():
            nms = (iid, it.get('name'), *self._loc_texts('ItemTemplate', iid, 'name'))
            bo = self.items[iid]['buildableObject']
            add('building' if bo else 'item', bo if bo else iid, *nms)
            if bo:
                add('item', iid, *nms)
        if not q:
            raise LookupError('leere Suche')
        order = {'robot': 0, 'building': 1, 'item': 2}
        levels = (lambda ident, nms: q == ident.casefold(),        # identifier
                  lambda ident, nms: q in nms,                      # exact name (any language)
                  lambda ident, nms: any(q in n for n in nms))      # part of a name
        for test in levels:
            hits = sorted(((k, i) for (k, i), nms in cands.items() if test(i, nms) and kind in (None, k)),
                          key=lambda h: (self._hidden(*h), order[h[0]], h[1]))
            if not hits:
                continue
            # hidden items (world decor etc.) and the buildings only they name step back behind visible matches
            pool = [h for h in hits if not self._hidden(*h)] or hits
            same_kind = [h for h in pool if h[0] == pool[0][0]]
            if len(same_kind) > 1 and hits[0][0] == 'building':
                # several buildings share the name (modes, modules): the one an equally named item builds, else the one with recipes
                direct = {self.items[i]['buildableObject'] for (k, i), nms in cands.items()
                          if k == 'item' and test(i, nms) and self.items[i]['buildableObject']}
                pick = [h for h in same_kind if h[1] in direct] or [h for h in same_kind if self.machines[h[1]]['crafting']]
                if len(pick) == 1:
                    return pick[0][0], pick[0][1], [f'{k} {i}' for k, i in hits if (k, i) != pick[0]]
            if len(same_kind) > 1:
                raise LookupError(f'"{query}" ist mehrdeutig: ' + ', '.join(f'{k} {i}' for k, i in hits[:15])
                                  + (f' (+{len(hits) - 15})' if len(hits) > 15 else '') + ' - Identifier angeben')
            return pool[0][0], pool[0][1], [f'{k} {i}' for k, i in hits if (k, i) != pool[0]]
        raise LookupError(f'nichts gefunden für "{query}" (Item, Gebäude oder Assembly-Line-Roboter; Identifier oder Name)')

    def _hidden(self, kind: str, ident: str) -> bool:
        if kind == 'item':
            return self.items[ident]['hidden']
        if kind == 'building':
            nm = self.names[ident]
            items = [x for x in [nm['item'], *nm['itemAlternatives']] if x]
            return not nm['nameOverride'] and bool(items) and all(self.items[x]['hidden'] for x in items)
        return False

    def _loc_texts(self, type_name: str, ident: str, field: str, path=()) -> list[str]:
        k = lkey(type_name, ident, field, list(path))
        return [cat[k] for cat in self.catalogs.values() if k in cat]

    # ------------------------------------------------------------ shared blocks

    def recipe(self, rid: str, machine: str | None = None) -> dict:
        """Recipe with sources; producers (all, or only `machine`) with rates per real speed level."""
        r, ex = self._raw('CraftingRecipe', rid), self.recipes[rid]
        S = lambda f: self.src('CraftingRecipe', rid, f)  # noqa: E731
        out = {
            'identifier': self.V(rid, S('identifier')), 'name': self.V(r.get('name'), S('name')),
            'tags': self.V(list(r.get('tags') or []), S('tags')),
            'tagNames': [self.name_of('CraftingTag', t) if t in self.d.tags else self.V(None, f'kein CraftingTag-Template für "{t}"')
                         for t in (r.get('tags') or [])],
            'category': self.V(text(r.get('category_identifier')), S('category_identifier')),
            'categoryName': self.name_of('CraftingRecipeCategory', text(r.get('category_identifier')))
            if text(r.get('category_identifier')) else self.V(None, S('category_identifier')),
            'timeMs': self.V(ex['timeMs'], S('timeMs')),
            'inputs': [{'item': self.V(e['item'], S(f'input_data[{i}].identifier')), 'name': self.item_name(e['item']),
                        'amount': self.V(e['amount'], S(f'input_data[{i}].amount'))} for i, e in enumerate(ex['inputs'])],
            'outputs': [{'item': self.V(e['item'], S(f'output_data[{i}].identifier')), 'name': self.item_name(e['item']),
                         'amount': self.V(e['amount'], S(f'output_data[{i}].amount')),
                         'chance': self.V(e['chance'], S(f'output_data[{i}].percentage_str'))} for i, e in enumerate(ex['outputs'])],
            'fluidInputs': [{'element': self.V(e['element'], S(f'inputElemental_data[{i}].identifier')),
                             'liters': self.V(e['liters'], S(f'inputElemental_data[{i}].amount_str'))}
                            for i, e in enumerate(ex['fluidInputs'])],
            'fluidOutputs': [{'element': self.V(e['element'], S(f'outputElemental_data[{i}].identifier')),
                              'liters': self.V(e['liters'], S(f'outputElemental_data[{i}].amount_str'))}
                             for i, e in enumerate(ex['fluidOutputs'])],
            'hiddenInCharacterCrafting': self.V(ex['hiddenInCharacterCrafting'], S('isHiddenInCharacterCraftingFrame')),
            'producers': [self.producer(rid, p) for p in ex['derived']['producers'] if machine in (None, p['machine'])],
            'unlockedBy': self.unlocks(rid),
        }
        return out

    def machine_recipe(self, rid: str, bid: str) -> dict:
        """Compact recipe entry for a building sheet: amounts plus time and rates on this machine only."""
        ex = self.recipes[rid]
        S = lambda f: self.src('CraftingRecipe', rid, f)  # noqa: E731
        p = next((p for p in ex['derived']['producers'] if p['machine'] == bid), None)
        pr = self.producer(rid, p) if p else None
        return {'recipe': self.V(rid, S('identifier')), 'name': self.V(ex['name'], S('name')), 'timeMs': self.V(ex['timeMs'], S('timeMs')),
                'inputs': [{'item': self.V(e['item'], S(f'input_data[{i}].identifier')), 'name': self.item_name(e['item']),
                            'amount': self.V(e['amount'], S(f'input_data[{i}].amount'))} for i, e in enumerate(ex['inputs'])],
                'fluidInputs': [{'element': self.V(e['element'], S(f'inputElemental_data[{i}].identifier')),
                                 'liters': self.V(e['liters'], S(f'inputElemental_data[{i}].amount_str'))} for i, e in enumerate(ex['fluidInputs'])],
                'outputs': [{'item': self.V(e['item'], S(f'output_data[{i}].identifier')), 'name': self.item_name(e['item']),
                             'amount': self.V(e['amount'], S(f'output_data[{i}].amount')),
                             'chance': self.V(e['chance'], S(f'output_data[{i}].percentage_str'))} for i, e in enumerate(ex['outputs'])],
                'fluidOutputs': [{'element': self.V(e['element'], S(f'outputElemental_data[{i}].identifier')),
                                  'liters': self.V(e['liters'], S(f'outputElemental_data[{i}].amount_str'))} for i, e in enumerate(ex['fluidOutputs'])],
                'craftTimeSec': pr['craftTimeSec'] if pr else self.V(None, 'keine Rate (siehe Warnungen des Exports)'),
                'perMinute': pr['perMinute'] if pr else None}

    def producer(self, rid: str, p: dict) -> dict:
        mid, kind = p['machine'], p['kind']
        rtags = set(self.recipes[rid]['tags'])
        S = lambda f: self.src('CraftingRecipe', rid, f)  # noqa: E731
        if kind == 'Character':
            oq = (OQ_CHARACTER,)
            machine = self.V(CHARACTER_MACHINE_ID, self.src('CraftingRecipe', rid, 'tags') + ' enthält "character" '
                             '(Handwerk; nicht wenn isHiddenInCharacterCraftingFrame)')
            speed = self.V(p['speedMultiplier'], 'FoundryNative.dll CraftingAction::reinitialize: timeMs / 3', oq=oq)
            tsrc = CALC_TIME_CHARACTER
            note = 'ohne Erkundungsbonus (Charakterherstellungstempo: −10 % je Stufe)'
            exact = self.recipes[rid]['timeMs'] * TICKS_PER_SECOND / 3000
            if abs(round(p['craftTimeSec'] * TICKS_PER_SECOND) - exact) > 1e-9:
                note += (f'; ohne die Kürzung im Spiel wären es {exact:.4g} Ticks = {self.recipes[rid]["timeMs"] / 3000:.4f} s, '
                         f'das Spiel rechnet {round(p["craftTimeSec"] * TICKS_PER_SECOND)} Ticks')
        else:
            b = self._raw('BuildableObjectTemplate', mid)
            oq = (OQ_HEAVY_CASTER,) if kind == 'ModularEntityProducer' else (OQ_BASE_STATION,) if kind == 'BaseStation' else ()
            if kind == 'BaseStation':
                why = self.src('BuildableObjectTemplate', mid, 'baseStation_craftingRecipeIdentifier') + f' enthält {rid}'
                speed = self.V(1, 'fest 1: BaseStationFurnace::tickUpdate kennt keinen Modifier (FoundryNative.dll)', oq=oq)
                tsrc = CALC_TIME_BASE
            else:
                fixed = FIXED_FIELD.get(kind)
                if fixed and text(b.get(fixed)) == rid:
                    why = self.src('BuildableObjectTemplate', mid, fixed) + f' = {rid}'
                else:
                    tf = TAG_FIELD[kind]
                    mt = b.get(tf) if isinstance(b.get(tf), list) else [b.get(tf)]
                    why = self.src('BuildableObjectTemplate', mid, tf) + f' ∩ Rezept-tags = {sorted(rtags & set(mt))}'
                speed = self.V(p['speedMultiplier'], self.src('BuildableObjectTemplate', mid, SPEED_FIELD[kind]), oq=oq)
                tsrc = CALC_TIME
            machine = self.V(mid, why)
            note = None
        rates = p['perMinute']
        char = mid == CHARACTER_MACHINE_ID
        return {
            'machine': machine, 'machineName': self.V('Handwerk', CHARACTER_SRC) if char else self.machine_name(mid),
            'kind': self.V(kind, CHARACTER_SRC if char else self.src('BuildableObjectTemplate', mid, 'type')),
            'speedMultiplier': speed,
            'craftTimeSec': self.V(p['craftTimeSec'], tsrc, oq=oq, note=note),
            'perMinute': self._rates(rid, rates, oq),
        }

    def _rates(self, rid: str, rates: dict, oq) -> dict:
        S = lambda f: self.src('CraftingRecipe', rid, f)  # noqa: E731
        return {
            'outputs': [{'item': self.V(e['item'], S(f'output_data[{i}].identifier')), 'name': self.item_name(e['item']),
                         'perMin': self.V(e['perMin'], CALC_RATE, oq=oq)} for i, e in enumerate(rates['outputs'])],
            'inputs': [{'item': self.V(e['item'], S(f'input_data[{i}].identifier')), 'name': self.item_name(e['item']),
                        'perMin': self.V(e['perMin'], CALC_RATE, oq=oq)} for i, e in enumerate(rates['inputs'])],
            'fluidOutputs': [{'element': self.V(e['element'], S(f'outputElemental_data[{i}].identifier')),
                              'litersPerMin': self.V(e['litersPerMin'], CALC_RATE, oq=oq)} for i, e in enumerate(rates['fluidOutputs'])],
            'fluidInputs': [{'element': self.V(e['element'], S(f'inputElemental_data[{i}].identifier')),
                             'litersPerMin': self.V(e['litersPerMin'], CALC_RATE, oq=oq)} for i, e in enumerate(rates['fluidInputs'])]}

    def machine_name(self, bid: str) -> dict:
        nm = self.names[bid]
        if nm['nameOverride']:
            return self.V(nm['name'], self.src('BuildableObjectTemplate', bid, 'nameOverride'))
        if nm['item']:
            return self.V(nm['name'], self.src('ItemTemplate', nm['item'], 'name'), oq=OQ_NAMES if nm['itemAlternatives'] else None)
        return self.V(None, '–')

    def unlocks(self, rid: str) -> dict:
        ub = self.recipes[rid]['derived']['unlockedBy']
        return {'research': [self.research_ref(x, rid) for x in ub['research']],
                'explorationUnlocks': [self.exploration_ref(x, rid) for x in ub['explorationUnlocks']]}

    def research_ref(self, rsid: str, rid: str | None = None) -> dict:
        r = self.research[rsid]
        S = lambda f: self.src('ResearchTemplate', rsid, f)  # noqa: E731
        raw = self._raw('ResearchTemplate', rsid)
        out = {'identifier': self.V(rsid, S('list_craftingUnlocks_str') + f' enthält {rid}' if rid else S('identifier')),
               'name': self.V(r['name'], S('name')),
               'cost': [{'item': self.V(e['item'], S(f'input_data[{i}].identifier')), 'name': self.item_name(e['item']),
                         'amount': self.V(e['amount'], S(f'input_data[{i}].amount'))} for i, e in enumerate(r['cost'])],
               'secondsPerScienceItem': self.V(r['secondsPerScienceItem'], S('secondsPerScienceItem')),
               'timeSecOneServer': self.V(r['derived']['timeSecOneServer'],
                                          'berechnet: größte Menge in input_data × secondsPerScienceItem, 1 Forschungsserver '
                                          '(FoundryNative.dll ResearchEntity/ResearchManager)', oq=OQ_RESEARCH),
               'dependencies': [{'identifier': self.V(dep, S(f'list_researchDependencies_str[{i}]')),
                                 'name': self.name_of('ResearchTemplate', dep)} for i, dep in enumerate(r['dependencies'])
                                if dep in self.research],
               'requiredCompanyRank': self.V(r['requiredCompanyRank'], S('requiredCompanyRankIdentifier'))}
        if 'ENDLESS_RESEARCH' in r['flags']:
            out['endlessManualLevels'] = self.V(raw.get('endlessResearch_amountOfManualEndlessResearches'),
                                                S('endlessResearch_amountOfManualEndlessResearches'))
        return out

    def exploration_ref(self, eid: str, rid: str | None = None) -> dict:
        e = self.exploration[eid]
        S = lambda f: self.src('ExplorationUnlockTemplate', eid, f)  # noqa: E731
        return {'identifier': self.V(eid, S('craftingRecipeUnlocks_identifier') + f' enthält {rid}' if rid else S('identifier')),
                'title': self.V(e['title'], S('title')),
                'requirements': [{'item': self.V(q['item'], S(f'requirements[{i}].itemTemplateIdentifier')),
                                  'amount': self.V(q['amount'], S(f'requirements[{i}].amount'))} for i, q in enumerate(e['requirements'])],
                'secondsToUnlock': self.V(e['secondsToUnlock'], S('secondsToUnlock')),
                'dependencies': [self.V(x, S(f'unlockDepedencies[{i}].explorationUnlockTemplateIdentifier'))
                                 for i, x in enumerate(e['dependencies'])],
                'researchDependencies': [self.V(x, S(f'researchDepedencies[{i}].researchTemplateIdentifier'))
                                         for i, x in enumerate(e['researchDependencies'])]}

    def item_basics(self, iid: str) -> dict:
        it, ex = self._raw('ItemTemplate', iid), self.items[iid]
        S = lambda f: self.src('ItemTemplate', iid, f)  # noqa: E731
        cat = text(it.get('itemCategoryIdentifier'))
        return {
            'identifier': self.V(iid, S('identifier')), 'name': self.V(it.get('name'), S('name')),
            'names': self.loc('ItemTemplate', iid, 'name'),
            'description': self.V(text(it.get('tooltipInfoMessage')), S('tooltipInfoMessage')),
            'descriptions': self.loc('ItemTemplate', iid, 'tooltipInfoMessage'),
            'explorationFlavorText': self.V(text(it.get('explorationUnlockInput_flavorText')), S('explorationUnlockInput_flavorText'))
            if text(it.get('explorationUnlockInput_flavorText')) else None,
            'explorationFlavorTexts': self.loc('ItemTemplate', iid, 'explorationUnlockInput_flavorText'),
            'stackSize': self.V(it.get('stackSize'), S('stackSize')),
            'category': self.V(cat, S('itemCategoryIdentifier')),
            'categoryName': self.name_of('ItemCategoryTemplate', cat) if cat else self.V(None, '–'),
            'flags': self.V(ex['flags'], S('flags')), 'hidden': self.V(ex['hidden'], S('isHiddenItem')),
            'weightGrams': self.V(ex['weightGrams'], S('_baseWeightInGrams')),
        }

    def sales(self, iid: str) -> dict | None:
        it, ex = self._raw('ItemTemplate', iid), self.items[iid]
        S = lambda f: self.src('ItemTemplate', iid, f)  # noqa: E731
        out = {'salesItem': self.V(bool(ex['sales']), S('flags') + (' enthält SALES_ITEM/SALES_ITEM_ASSEMBLY_LINE' if ex['sales']
                                                              else ' (ohne SALES_ITEM/SALES_ITEM_ASSEMBLY_LINE)'))}
        if ex['sales']:
            cat, ind = text(it.get('salesItem_salesItemCategoryIdentifier')), text(it.get('salesItem_industryIdentifier'))
            out |= {'category': self.V(cat, S('salesItem_salesItemCategoryIdentifier')),
                    'categoryName': self.name_of('SalesItemCategoryTemplate', cat) if cat else self.V(None, '–'),
                    'industry': self.V(ind, S('salesItem_industryIdentifier')),
                    'industryName': self.name_of('IndustryTemplate', ind) if ind else self.V(None, '–'),
                    'basePrice': self.V(it.get('salesItem_currencyAmount'), S('salesItem_currencyAmount')),
                    'baseDemandPerDay': self.V(it.get('salesItem_salesPlatformBaseDemandPerDay'),
                                               S('salesItem_salesPlatformBaseDemandPerDay')),
                    'skyPlatformBaseCapacity': self.V(it.get('salesItem_skyPlatformBaseCapacity'), S('salesItem_skyPlatformBaseCapacity')),
                    'hiddenByResearch': self.V(text(it.get('salesItem_hiddenByResearchIdentifier')),
                                               S('salesItem_hiddenByResearchIdentifier'))}
        if 'SALES_CURRENCY' in ex['flags']:
            out |= {'salesCurrency': self.V(True, S('flags') + ' enthält SALES_CURRENCY (Erlös aus Verkäufen)'),
                    'salesCurrencySkyPlatformBaseCapacity': self.V(it.get('salesCurrency_skyPlatformBaseCapacity'),
                                                                   S('salesCurrency_skyPlatformBaseCapacity')),
                    'salesCurrencyHiddenByResearch': self.V(text(it.get('salesCurrency_hiddenByResearchIdentifier')),
                                                            S('salesCurrency_hiddenByResearchIdentifier'))}
        if ex['market']:
            out |= {'marketBuyPrice': self.V(it.get('market_buyPrice'), S('market_buyPrice')),
                    'marketSellPrice': self.V(it.get('market_sellPrice'), S('market_sellPrice')),
                    'tradeableOnStation': self.V(bool(it.get('canBeTradedOnStation')), S('canBeTradedOnStation'))}
        return out

    def workstation(self, iid: str) -> dict | None:
        it = self._raw('ItemTemplate', iid)
        if 'WORKSTATION_ITEM' not in self.items[iid]['flags']:
            return None
        S = lambda f: self.src('ItemTemplate', iid, f)  # noqa: E731
        eff, d1, d2 = it.get('workstationItem_effect'), it.get('workstationItem_data01'), it.get('workstationItem_data02')
        return {'effect': self.V(eff, S('workstationItem_effect')), 'data01': self.V(d1, S('workstationItem_data01')),
                'data02': self.V(d2, S('workstationItem_data02')),
                'requiredTags': self.V([t.split('|')[0] for t in it.get('workstationItem_requiredTags') or []], S('workstationItem_requiredTags')),
                'excludedTags': self.V([t.split('|')[0] for t in it.get('workstationItem_excludedTags') or []], S('workstationItem_excludedTags')),
                'bonusPercent': self.V(num(d1) / 100 if d1 else None, 'berechnet: data01 / 100 (Einheit 0,01 %; FoundryNative.dll '
                                       f'WorkstationEffectManager::calculateBonusTotals, Wirkung {eff})', oq=OQ_WORKSTATION),
                'powerIncreasePercent': self.V(num(d2) / 100 if d2 else None, 'berechnet: data02 / 100 (Mehrverbrauch der Maschine)',
                                               oq=OQ_WORKSTATION,
                                               note='gilt nur, wenn genau eine Workstation die Maschine abdeckt; zwei legen sie still')}

    def recycling(self, iid: str) -> list[dict]:
        it = self._raw('ItemTemplate', iid)
        S = lambda f: self.src('ItemTemplate', iid, f)  # noqa: E731
        return [{'item': self.V(e.get('itemTemplateIdentifier'), S(f'recyclingData[{i}].itemTemplateIdentifier')),
                 'name': self.item_name(e.get('itemTemplateIdentifier')) if e.get('itemTemplateIdentifier') in self.items else self.V(None, '–'),
                 'chance': self.V(num(e.get('chance_str')), S(f'recyclingData[{i}].chance_str'))}
                for i, e in enumerate(it.get('recyclingData') or [])]

    def fuel(self, iid: str) -> dict:
        it, fl = self._raw('ItemTemplate', iid), self.items[iid]['flags']
        value = num(it.get('burnable_fuelValueKJ_str'))
        S = lambda f: self.src('ItemTemplate', iid, f)  # noqa: E731
        if not value:
            return {'fuelValueKJ': self.V(value, S('burnable_fuelValueKJ_str'))}
        burnable = 'BURNABLE' in fl
        out = {'fuelValueKJ': self.V(value, S('burnable_fuelValueKJ_str'), oq=None if burnable else OQ_FUEL,
                                     note=None if burnable else 'kein Flag BURNABLE: C# nimmt das Item nicht als Brennstoff an '
                                                                '(CubeInventory.cs), Export: fuel = null'),
               'burnable': self.V(burnable, S('flags') + (' enthält BURNABLE' if burnable else ' (ohne BURNABLE)')),
               'residualItem': self.V(text(it.get('burnable_residualItemTemplate_str')), S('burnable_residualItemTemplate_str')),
               'machines': []}
        if 'JET_PACK_FUEL' in fl:
            out['jetpackFuel'] = self.V(True, S('flags') + ' enthält JET_PACK_FUEL (nicht in Brennstoff-Slots, CubeInventory.cs)')
        if burnable and 'JET_PACK_FUEL' not in fl:
            for bid, b in sorted(self.d.bots.items()):
                slots = [(g, s) for g, grp in enumerate(b.get('itemBufferSlotMap') or [])
                         for s, sl in enumerate(grp.get('slots') or []) if sl.get('flavorType') == 'Fuel']
                if not slots:
                    continue
                locked = text(b.get('lvgGenerator_lockedItemTemplate_identifier'))
                if locked and locked != iid:
                    continue
                B = lambda f: self.src('BuildableObjectTemplate', bid, f)  # noqa: E731
                m = {'machine': self.V(bid, B(f'itemBufferSlotMap[{slots[0][0]}].slots[{slots[0][1]}].flavorType') + ' = Fuel'),
                     'name': self.machine_name(bid)}
                for f in ('lvgGenerator_transmissionRate_kjPerS_str', 'lvgGenerator_efficiency_str', 'boiler_energyConsumption_kjPerS_str'):
                    if num(b.get(f)):
                        m[f] = self.V(num(b.get(f)), B(f))
                out['machines'].append(m)
            out['burnTime'] = self.V(None, 'nicht berechnet: Verbrauch pro Item hängt an nativer Logik (Wirkungsgrad, Last), nicht geprüft')
        return out

    # ------------------------------------------------------------ item

    def item_sheet(self, iid: str) -> dict:
        ex = self.items[iid]
        produced = sorted(ex['derived']['producedBy'])
        used = sorted(ex['derived']['usedBy'])
        refs = self.references(iid)
        sheet = {'kind': 'item', **self._head(), 'item': self.item_basics(iid), 'sales': self.sales(iid), 'fuel': self.fuel(iid),
                 'workstation': self.workstation(iid), 'recycling': self.recycling(iid),
                 'recipesProducing': [self.recipe(r) for r in produced],
                 'gathering': self._gathering(iid, refs),
                 'recipesUsing': [self._usage(r, iid) for r in used],
                 'assemblyLine': self._al_usage(iid),
                 'researchCosts': self._research_costs(iid),
                 'explorationRequirements': self._exploration_requirements(iid),
                 'blastFurnace': self._blast_furnace(refs),
                 'quests': self._quests('ItemsMade', iid),
                 'otherReferences': self._other(refs, 'item', ('ItemTemplate', iid))}
        return sheet

    def _head(self) -> dict:
        return {'gameVersion': self.ver['gameVersion'], 'steamBuildId': self.ver['steamBuildId'],
                'templateSource': self.d.source.label, 'templatesDir': str(self.gp.templates),
                'openQuestions': 'findings/open_questions.md' + (' (nicht gefunden: alles Nicht-Gemessene gilt als ungemessen)'
                                                                if self.oq_missing else '')}

    def _gathering(self, iid: str, refs: list[dict]) -> list[dict]:
        out = []
        for r in refs:
            if r['type'] == 'TerrainBlockType' and r['field'] == 'yieldItemOnDig':
                tb = self._raw('TerrainBlockType', r['identifier'])
                S = lambda f, i=r['identifier']: self.src('TerrainBlockType', i, f)  # noqa: E731
                out.append({'how': 'Abbau Terrain-Block', 'from': self.V(r['identifier'], S('identifier')),
                            'yields': self.V(iid, r['source']),
                            'fromName': self.V(tb.get('name'), S('name')),
                            'miningTimeSec': self.V(tb.get('miningTimeInSec'), S('miningTimeInSec')),
                            'requiredMiningHardnessLevel': self.V(tb.get('requiredMiningHardnessLevel'), S('requiredMiningHardnessLevel'))})
            elif r['type'] == 'BuildableObjectTemplate' and r['field'].startswith('worldDecor_miningYield'):
                b = self._raw('BuildableObjectTemplate', r['identifier'])
                i = int(re.search(r'\[(\d+)\]', r['field']).group(1))
                S = lambda f, x=r['identifier']: self.src('BuildableObjectTemplate', x, f)  # noqa: E731
                out.append({'how': 'Abbau Welt-Objekt', 'from': self.V(r['identifier'], S('identifier')),
                            'yields': self.V(iid, r['source']),
                            'fromName': self.machine_name(r['identifier']),
                            'amount': self.V(b['worldDecor_miningYield'][i].get('amount'), S(f'worldDecor_miningYield[{i}].amount')),
                            'miningTimeSec': self.V(b.get('worldDecor_miningTimeSec'), S('worldDecor_miningTimeSec'))})
            elif r['type'] == 'BuildableObjectTemplate' and r['field'].startswith('worldDecor_specialDrops'):
                b = self._raw('BuildableObjectTemplate', r['identifier'])
                i = int(re.search(r'\[(\d+)\]', r['field']).group(1))
                S = lambda f, x=r['identifier']: self.src('BuildableObjectTemplate', x, f)  # noqa: E731
                out.append({'how': 'Sonderfund beim Abbau', 'from': self.V(r['identifier'], S('identifier')), 'yields': self.V(iid, r['source']),
                            'fromName': self.machine_name(r['identifier']),
                            'amount': self.V(b['worldDecor_specialDrops'][i].get('amount'), S(f'worldDecor_specialDrops[{i}].amount')),
                            'dropChancePercent': self.V(num(b['worldDecor_specialDrops'][i].get('dropChancePercentage_str')),
                                                        S(f'worldDecor_specialDrops[{i}].dropChancePercentage_str'))})
            elif r['type'] == 'BuildableObjectTemplate' and r['field'] in ('endlessMiner_outputTemplateIdentifier',
                                                                             'oreVeinMineable_yieldItem_identifier'):
                b = self._raw('BuildableObjectTemplate', r['identifier'])
                S = lambda f, x=r['identifier']: self.src('BuildableObjectTemplate', x, f)  # noqa: E731
                g = {'how': 'Endlos-Miner' if r['field'].startswith('endless') else 'Erzader-Abbau',
                     'from': self.V(r['identifier'], S('identifier')), 'yields': self.V(iid, r['source']),
                     'fromName': self.machine_name(r['identifier'])}
                for f in ('endlessMiner_ticksPerItem', 'endlessMiner_powerDemandMining_kjPerSec_str', 'endlessMiner_powerCoreSlots',
                          'endlessMiner_speedIncreasePerPowerCore_str'):
                    if r['field'].startswith('endless') and b.get(f) not in (None, ''):
                        g[f] = self.V(num(b.get(f)), S(f))
                g['rate'] = self.V(None, 'nicht berechnet: Abbau-Logik nativ, nicht geprüft')
                out.append(g)
            elif r['type'] == 'ItemTemplate' and r['field'].startswith('recyclingData'):
                src_it = self._raw('ItemTemplate', r['identifier'])
                i = int(re.search(r'\[(\d+)\]', r['field']).group(1))
                out.append({'how': 'Recycling', 'from': self.V(r['identifier'], self.src('ItemTemplate', r['identifier'], 'identifier')),
                            'yields': self.V(iid, r['source']), 'fromName': self.item_name(r['identifier']),
                            'chance': self.V(num(src_it['recyclingData'][i].get('chance_str')),
                                             self.src('ItemTemplate', r['identifier'], f'recyclingData[{i}].chance_str'))})
        for oid in self.items[iid]['derived']['producedByAssemblyLine']:
            out.append({'how': 'Assembly Line (Verkaufs-Item)', 'from': self.V(oid, self.src('AssemblyLineObjectTemplate', oid, 'identifier')),
                        'yields': self.V(iid, self.src('ItemTemplate', self.alobjects[oid]['starterItem'], 'alStarter_sellItemTemplateIdentifier')),
                        'fromName': self.name_of('AssemblyLineObjectTemplate', oid)})
        return out

    def _usage(self, rid: str, iid: str) -> dict:
        ex = self.recipes[rid]
        i, e = next((i, e) for i, e in enumerate(ex['inputs']) if e['item'] == iid)
        S = lambda f: self.src('CraftingRecipe', rid, f)  # noqa: E731
        return {'recipe': self.V(rid, S('identifier')), 'item': self.V(iid, S(f'input_data[{i}].identifier')),
                'name': self.V(ex['name'], S('name')),
                'amount': self.V(e['amount'], S(f'input_data[{i}].amount')), 'timeMs': self.V(ex['timeMs'], S('timeMs')),
                'tags': self.V(ex['tags'], S('tags')),
                'outputs': [{'item': self.V(o['item'], S(f'output_data[{j}].identifier')), 'name': self.item_name(o['item']),
                             'amount': self.V(o['amount'], S(f'output_data[{j}].amount')),
                             'chance': self.V(o['chance'], S(f'output_data[{j}].percentage_str'))} for j, o in enumerate(ex['outputs'])],
                'fluidInputs': [{'element': self.V(e['element'], S(f'inputElemental_data[{j}].identifier')),
                                 'liters': self.V(e['liters'], S(f'inputElemental_data[{j}].amount_str'))} for j, e in enumerate(ex['fluidInputs'])],
                'fluidOutputs': [{'element': self.V(e['element'], S(f'outputElemental_data[{j}].identifier')),
                                  'liters': self.V(e['liters'], S(f'outputElemental_data[{j}].amount_str'))} for j, e in enumerate(ex['fluidOutputs'])],
                'machines': [{'machine': pr['machine'], 'name': pr['machineName']}
                             for pr in (self.producer(rid, p) for p in ex['derived']['producers'])]}

    def _al_usage(self, iid: str) -> list[dict]:
        out = []
        for oid in self.items[iid]['derived']['usedByAssemblyLine']:
            o = self.alobjects[oid]
            if o['starterItem'] == iid:
                out.append({'object': self.V(oid, self.src('ItemTemplate', iid, 'alStarter_alotIdentifier')),
                            'name': self.name_of('AssemblyLineObjectTemplate', oid), 'role': 'Starter-Item',
                            'amount': self.V(1, self.src('ItemTemplate', iid, 'alStarter_alotIdentifier') + f' = {oid} (ein Starter-Item je Roboter)')})
            for s in o['stages']:
                for a in s['actions']:
                    pa = a['producerAction']
                    for k, e in enumerate(pa['items']):
                        if e['item'] == iid:
                            out.append({'object': self.V(oid, self.src('AssemblyLineObjectTemplate', oid, 'identifier')),
                                        'item': self.V(iid, self.src('AssemblyLineProducerActionTemplate', pa['identifier'],
                                                                     f'requiredItems[{k}].identifier')),
                                        'name': self.name_of('AssemblyLineObjectTemplate', oid),
                                        'role': f'Aktion {a["identifier"]} ({pa["identifier"]})',
                                        'amount': self.V(e['amount'], self.src('AssemblyLineProducerActionTemplate', pa['identifier'],
                                                                              f'requiredItems[{k}].amount'))})
        return out

    def _research_costs(self, iid: str) -> list[dict]:
        out = []
        for rsid, r in sorted(self.research.items()):
            for i, e in enumerate(r['cost']):
                if e['item'] == iid:
                    out.append({'research': self.V(rsid, self.src('ResearchTemplate', rsid, 'identifier')),
                                'item': self.V(iid, self.src('ResearchTemplate', rsid, f'input_data[{i}].identifier')),
                                'name': self.V(r['name'], self.src('ResearchTemplate', rsid, 'name')),
                                'amount': self.V(e['amount'], self.src('ResearchTemplate', rsid, f'input_data[{i}].amount'))})
        return out

    def _exploration_requirements(self, iid: str) -> list[dict]:
        out = []
        for eid, e in sorted(self.exploration.items()):
            for i, q in enumerate(e['requirements']):
                if q['item'] == iid:
                    S = lambda f, x=eid: self.src('ExplorationUnlockTemplate', x, f)  # noqa: E731
                    out.append({'explorationUnlock': self.V(eid, S('identifier')),
                                'item': self.V(iid, S(f'requirements[{i}].itemTemplateIdentifier')),
                                'title': self.V(e['title'], S('title')),
                                'amount': self.V(q['amount'], S(f'requirements[{i}].amount')),
                                'flags': self.V(e['flags'], S('unlockFlags')),
                                'description': self.V(e['description'], S('description')),
                                'recipeUnlocks': [self.V(x, S(f'craftingRecipeUnlocks_identifier[{j}]')) for j, x in enumerate(e['recipeUnlocks'])],
                                'effectFields': self._eut_fields(eid),
                                'effect': self.V(e['characterCraftingSpeedBonusPercent'],
                                                 S('characterCraftingSpeed_additionalDecrementPercentage_str'),
                                                 oq=OQ_CHARACTER_BONUS) if e['characterCraftingSpeedBonusPercent'] else None})
        return out

    def _eut_fields(self, eid: str) -> dict:
        raw = self._raw('ExplorationUnlockTemplate', eid)
        meta = {'identifier', 'title', 'description', 'icon_identifier', 'categoryIdentifier', 'unlockFlags', 'requirements',
                'unlockDepedencies', 'researchDepedencies', 'secondsToUnlock', 'sortOrderASC', 'buildTags',
                'craftingRecipeUnlocks_identifier', 'characterCraftingSpeed_additionalDecrementPercentage_str'}
        return {f: self.V(num(v) if f.endswith('_str') and _is_num(v) else v, self.src('ExplorationUnlockTemplate', eid, f))
                for f, v in raw.items() if f not in meta and not f.startswith(('savegame', 'revision'))
                and v not in (None, '', [], {}, 0, False) and not _SKIP_FIELD.search(f)}

    def _quests(self, ctype: str, ident: str) -> list[dict]:
        out = []
        try:
            quests = self.d.source.load('QuestTemplate')
        except (Exception, SystemExit):  # noqa: BLE001
            return out
        for qid, q in sorted(quests.items()):
            for i, c in enumerate(q.get('conditions') or []):
                if c.get('type') == ctype and c.get('identifier01') == ident:
                    S = lambda f, x=qid: self.src('QuestTemplate', x, f)  # noqa: E731
                    out.append({'quest': self.V(qid, S('identifier')), 'target': self.V(ident, S(f'conditions[{i}].identifier01')),
                                'title': self.V(text(q.get('title')), S('title')),
                                'milestone': self.V(bool(q.get('isMilestoneQuest')), S('isMilestoneQuest')),
                                'condition': self.V(ctype, S(f'conditions[{i}].type')),
                                'amount': self.V(c.get('additionalData01'), S(f'conditions[{i}].additionalData01'))})
        return out

    @staticmethod
    def _other(refs: list[dict], kind: str, own: tuple[str, str]) -> list[dict]:
        """References not shown elsewhere: target kind must be `kind` or unknown, own template excluded."""
        return [r for r in refs if (r['type'], r['identifier']) != own and ref_target(r['type'], r['field']) in (kind, None)
                and not COVERED[kind].match(f'{r["type"]}:{r["field"]}')]

    def _blast_furnace(self, refs: list[dict]) -> list[dict]:
        out = []
        for r in refs:
            if r['type'] != 'BlastFurnaceModeTemplate' or not r['field'].startswith('input_data'):
                continue
            m = self._raw('BlastFurnaceModeTemplate', r['identifier'])
            i = int(re.search(r'\[(\d+)\]', r['field']).group(1))
            S = lambda f, x=r['identifier']: self.src('BlastFurnaceModeTemplate', x, f)  # noqa: E731
            out.append({'mode': self.V(r['identifier'], S('identifier')), 'item': self.V(m['input_data'][i].get('identifier'), r['source']),
                        'name': self.V(m.get('name'), S('name')),
                        'amount': self.V(m['input_data'][i].get('amount'), S(f'input_data[{i}].amount')),
                        'inputs': [{'item': self.V(e.get('identifier'), S(f'input_data[{j}].identifier')),
                                    'amount': self.V(e.get('amount'), S(f'input_data[{j}].amount'))}
                                   for j, e in enumerate(m.get('input_data') or [])],
                        'outputs': [{'element': self.V(e.get('identifier'), S(f'output_data_elemental[{j}].identifier')),
                                     'liters': self.V(num(e.get('amount_str')), S(f'output_data_elemental[{j}].amount_str'))}
                                    for j, e in enumerate(m.get('output_data_elemental') or [])],
                        'note': self.V(None, 'Zykluszeit des Hochofens nicht im Modus-Template (blastFurnace_* der Maschine); '
                                             'Rate nicht berechnet')})
        return out

    # ------------------------------------------------------------ building

    def building_sheet(self, bid: str) -> dict:
        b, ex, nm = self._raw('BuildableObjectTemplate', bid), self.machines[bid], self.names[bid]
        S = lambda f: self.src('BuildableObjectTemplate', bid, f)  # noqa: E731
        item = nm['item']
        tier = re.search(r'_(i|ii|iii|iv|v|vi)$', bid)
        group = text(b.get('conversionGroup_str'))
        general = {
            'identifier': self.V(bid, S('identifier')), 'name': self.machine_name(bid),
            'names': (self.loc('BuildableObjectTemplate', bid, 'nameOverride') if nm['nameOverride']
                      else self._mark(self.loc('ItemTemplate', item, 'name'), OQ_NAMES if nm['itemAlternatives'] else None)
                      if item else {}),
            'modeName': self.V(nm['modeName'], self.src('ItemTemplate', item, f'toggleableModes[{nm["modeIndex"]}].name'))
            if nm['modeName'] else None,
            'modeNames': self.loc('ItemTemplate', item, 'name', [('toggleableModes', nm['modeIndex'])]) if nm['modeName'] else {},
            'item': self.V(item, self.src('ItemTemplate', item, 'buildableObjectIdentifer') + f' = {bid} (Flag BUILDABLE_OBJECT)'
                           if item and self.items[item]['buildableObject'] == bid else
                           self.src('ItemTemplate', item, f'toggleableModes[{nm["modeIndex"]}].identifier') + f' = {bid}' if item
                           else 'kein Item baut dieses Gebäude'),
            'itemAlternatives': self.V(nm['itemAlternatives'], 'weitere Items mit diesem Gebäude (BUILDABLE_OBJECT oder toggleableModes)',
                                       oq=OQ_NAMES) if nm['itemAlternatives'] else None,
            'type': self.V(b.get('type'), S('type')),
            'tier': self.V(ROMAN[tier.group(1)], f'abgeleitet aus dem Identifier-Suffix _{tier.group(1)} (kein Tier-Feld im Template)')
            if tier else None,
            'conversionGroup': self.V(group, S('conversionGroup_str')) if group else None,
            'conversionGroupMembers': [{'identifier': self.V(x, self.src('BuildableObjectTemplate', x, 'conversionGroup_str') + f' = {group}'),
                                        'name': self.machine_name(x)}
                                       for x in sorted(k for k, o in self.d.bots.items() if group and text(o.get('conversionGroup_str')) == group)],
            'size': {a: self.V((b.get('size') or {}).get(a), S(f'size.{a}')) for a in ('x', 'y', 'z')},
            'demolitionTimeSec': self.V(b.get('demolitionTimeSec'), S('demolitionTimeSec')),
            'hasToBeOnFoundation': self.V(bool(b.get('hasToBeOnFoundation')), S('hasToBeOnFoundation')),
        }
        power = {f: self.V(num(b.get(f)) if f.endswith('_str') else b.get(f), S(f)) for f in POWER_FIELDS
                 if f in b and b.get(f) not in (None, '')}
        typed = self._type_fields(bid, b)
        power |= {f: v for f, v in typed.items() if _POWER_FIELD.search(f)}
        power |= self._al_power(bid, b)
        if b.get('hasWorkstationEffectManager'):
            power['workstationEffectTags'] = self.V([t.split('|')[0] for t in b.get('workstationEffectTags') or []], S('workstationEffectTags'))
            power['workstationBonus'] = self.V('nicht eingerechnet', 'Workstation-Roboter mit passendem Tag erhöhen Tempo und Verbrauch '
                                               '(FoundryNative.dll WorkstationEffectManager::calculateBonusTotals)', oq=OQ_WORKSTATION,
                                               note='zwei überlappende Workstations legen die Maschine still')
        connections = {
            'itemSlots': [{'header': self.V(g.get('header'), S(f'itemBufferSlotMap[{gi}].header')),
                           'slots': [self.V(f'{s.get("type")}/{s.get("flavorType")}', S(f'itemBufferSlotMap[{gi}].slots[{si}].type/flavorType'))
                                     for si, s in enumerate(g.get('slots') or [])]}
                          for gi, g in enumerate(b.get('itemBufferSlotMap') or [])],
            'loadersDisabled': self.V(bool(b.get('disableLoaders')), S('disableLoaders')),
            'fluidBoxes': [{k: self.V(v, S(f'fbm_ioFluidBoxes[{i}].{f}')) for k, (v, f) in {
                'isInput': (fb.get('isInput'), 'isInput'), 'capacityLiters': (num(fb.get('capacity_liter')), 'capacity_liter'),
                'transferRateLitersPerSec': (num(fb.get('transferRatePerSecond_liter')), 'transferRatePerSecond_liter'),
                'pipeType': (text(fb.get('pipeTypeIdentifier')), 'pipeTypeIdentifier'),
                'fixedElement': (text(fb.get('fixedElementTemplateIdentifier')), 'fixedElementTemplateIdentifier')}.items()}
                for i, fb in enumerate(b.get('fbm_ioFluidBoxes') or []) if b.get('hasFluidBoxManager')],
            'dataConnections': self.V(len(b.get('dsm_connections') or []) if b.get('hasDataSystemManager') else 0,
                                      'berechnet: Anzahl Einträge in ' + S('dsm_connections') + ' (wenn hasDataSystemManager)'),
        }
        if b.get('isModularBuilding') or b.get('modularBuildingLimits'):
            connections['modules'] = [{'module': self.V(m.get('bot_identifier'), S(f'modularBuildingLimits[{i}].bot_identifier')),
                                       'name': self.machine_name(m.get('bot_identifier')) if m.get('bot_identifier') in self.names else self.V(None, '–'),
                                       'min': self.V(m.get('minAmount'), S(f'modularBuildingLimits[{i}].minAmount')),
                                       'max': self.V(m.get('maxAmount'), S(f'modularBuildingLimits[{i}].maxAmount')),
                                       'cost': self._module_cost(m.get('bot_identifier'))['cost']
                                       if m.get('bot_identifier') in self.d.bots else []}
                                      for i, m in enumerate(b.get('modularBuildingLimits') or [])]
        shown = set(POWER_FIELDS) | set(power) | {SPEED_FIELD.get(b.get('type')), TAG_FIELD.get(b.get('type')), FIXED_FIELD.get(b.get('type'))}
        typed = {f: v for f, v in typed.items() if f not in shown}
        rng = {f: v for f, v in {**power, **typed}.items() if re.search(r'(?i)range|radius', f)}
        module_cost = self._module_cost(bid) if b.get('modularBuildingItemCost') else None
        crafting = None
        if ex['crafting']:
            c = ex['crafting']
            kind = c['kind']
            sel_src = (S('baseStation_craftingRecipeIdentifier') if c['recipeSelection'] == 'list'
                       else S(FIXED_FIELD[kind]) if c['recipeSelection'] == 'fixed' else S(TAG_FIELD[kind]))
            how = {'Producer': f'abgeleitet aus {S("producerRecipeType")} = {b.get("producerRecipeType")}',
                   'AutoProducer': f'abgeleitet: AutoProducer wählt über {S("autoProducer_recipeType_tag")}',
                   'ModularEntityProducer': f'abgeleitet: {S("modularProducer_fixedCraftingRecipeIdentifier")} '
                                            + ('gesetzt' if c['recipeSelection'] == 'fixed' else 'leer'),
                   'BaseStation': f'abgeleitet: Liste {S("baseStation_craftingRecipeIdentifier")}'}[kind]
            if kind == 'BaseStation':
                sel_src = 'abgeleitet: Base Station wählt per Rezeptliste, nicht per Tag'
            crafting = {
                'kind': self.V(kind, S('type')),
                'speedMultiplier': self.V(c['speedMultiplier'], S(SPEED_FIELD[kind]) if kind in SPEED_FIELD else
                                          'fest 1: BaseStationFurnace::tickUpdate (FoundryNative.dll)',
                                          oq=OQ_HEAVY_CASTER if kind == 'ModularEntityProducer' else OQ_BASE_STATION if kind == 'BaseStation'
                                          else None),
                'recipeSelection': self.V(c['recipeSelection'], how),
                'tags': self.V(c['tags'], sel_src),
                'recipes': [self.machine_recipe(r, bid) for r in c['derived']['recipes']],
            }
        al = None
        if ex['assemblyLine']:
            al = {'role': self.V(ex['assemblyLine']['role'], f'abgeleitet aus {S("type")} = {b.get("type")}'
                                 + (f', al_producer_machineType = {b.get("al_producer_machineType")}' if b.get('type') == 'AL_Producer' else ''))}
            alm = self.almachines.get(bid, {})
            sp = alm.get('speedSlotsPerTick')
            if sp:
                al['speedSlotsPerTick'] = self.V(sp, S(AL_SPEED_FIELD[b.get('type')]))
                al['speedMetersPerSec'] = self.V(alm['derived']['speedMetersPerSec'],
                                                 'berechnet: speedSlotsPerTick × 60 / 600 (GameRoot.LOCKSTEP_TICKS_PER_SECOND, '
                                                 'AssemblyLineSystem.SLOTS_PER_METER)')

        build = [self.recipe(r) for r in sorted(self.items[item]['derived']['producedBy'])] if item else []
        return {'kind': 'building', **self._head(), 'building': general, 'power': power, 'connections': connections,
                'range': rng, 'typeFields': typed, 'otherFields': self._other_fields(bid, b, set(typed) | shown),
                'crafting': crafting, 'assemblyLine': al, 'moduleCost': module_cost,
                'buildItem': self.item_basics(item) if item else None, 'buildCost': build,
                'quests': self._quests('BuildingsBuilt', bid),
                'otherReferences': self._other(self.references(bid), 'building', ('BuildableObjectTemplate', bid))}

    def _module_cost(self, bid: str) -> dict:
        b = self._raw('BuildableObjectTemplate', bid)
        S = lambda f: self.src('BuildableObjectTemplate', bid, f)  # noqa: E731
        res = text(b.get('modularBuildingModule_unlockedByResearchTemplateIdentifier'))
        return {'cost': [{'item': self.V(e.get('itemTemplateIdentifier'), S(f'modularBuildingItemCost[{i}].itemTemplateIdentifier')),
                          'name': self.item_name(e.get('itemTemplateIdentifier')),
                          'amount': self.V(e.get('itemCost'), S(f'modularBuildingItemCost[{i}].itemCost'))}
                         for i, e in enumerate(b.get('modularBuildingItemCost') or [])],
                'rubble': [{'item': self.V(e.get('itemTemplateIdentifier'), S(f'modularBuildingRubble[{i}].itemTemplateIdentifier')),
                            'amount': self.V(e.get('itemCost'), S(f'modularBuildingRubble[{i}].itemCost'))}
                           for i, e in enumerate(b.get('modularBuildingRubble') or [])],
                'description': self.V(text(b.get('modularBuildingModule_descriptionName')), S('modularBuildingModule_descriptionName')),
                'unlockedBy': self.research_ref(res) if res in self.research else None}

    def _al_power(self, bid: str, b: dict) -> dict:
        """AL start/producer/painter: no continuous draw, energy per action (+ peak while recharging)."""
        t, S = b.get('type'), (lambda f: self.src('BuildableObjectTemplate', bid, f))
        out = {}
        if t == 'AL_Start':
            kj = num(b.get('alStart_requiredPowerPerAction_kj_str'))
            out['energyPerActionKJ'] = self.V(kj, S('alStart_requiredPowerPerAction_kj_str'))
            out['peakPowerKW'] = self.V(_peak_kw(kj, b.get('al_start_speedInSlotsPerTick')),
                                        'berechnet: 2 × floor(Kosten·10⁴ / floor(1125/al_start_speedInSlotsPerTick)) × 60 / 10⁴ '
                                        '(FoundryNative.dll AL_StartEntity::tickUpdate)', oq=OQ_AL_POWER)
        elif t == 'AL_Producer' and b.get('al_producer_machineType') == 'Painter':
            costs = sorted({o['derived']['painterPowerKJ'] for o in self.alobjects.values()})
            out['energyPerObjectKJ'] = self.V(costs, 'berechnet: Σ objectParts[].requiredPowerForPainting_kj_str je Roboter-Bauplan '
                                              '(alle Teile, auch Metall; AL_ProducerEntity::recalculatePainterCosts)', oq=OQ_AL_PAINTER)
            out['peakPowerKW'] = self.V([_peak_kw(c, b.get('al_producer_speedInSlotsPerTick')) for c in costs],
                                        'berechnet: 2 × floor(Kosten·10⁴ / floor(1125/al_producer_speedInSlotsPerTick)) × 60 / 10⁴ '
                                        '(FoundryNative.dll AL_ProducerEntity::tickUpdate)', oq=OQ_AL_POWER)
        elif t == 'AL_Producer':
            costs = sorted({a['producerAction']['powerKJ'] for o in self.alobjects.values() for st in o['stages'] for a in st['actions']})
            out['energyPerActionKJ'] = self.V(costs, 'Templates/AssemblyLineProducerActionTemplate/*.yaml : powerCost_kj_str '
                                              '(je eingestellter Aktion; vorkommende Werte)')
            out['peakPowerKW'] = self.V([_peak_kw(c, b.get('al_producer_speedInSlotsPerTick')) for c in costs],
                                        'berechnet: 2 × floor(Kosten·10⁴ / floor(1125/al_producer_speedInSlotsPerTick)) × 60 / 10⁴ '
                                        '(FoundryNative.dll AL_ProducerEntity::tickUpdate)', oq=OQ_AL_POWER)
        if out:
            out['continuousDraw'] = self.V('keiner (energyConsumptionKW_str leer); Puffer für 2 Aktionen, lädt nur nach Verbrauch',
                                           S('energyConsumptionKW_str') + ' leer; Puffer: SPP_AL_Producer.cs / AL_*Entity::tickUpdate',
                                           oq=OQ_AL_POWER)
        return out

    _modes: dict | None = None

    def _other_fields(self, bid: str, b: dict, shown: set) -> dict:
        """Further template fields whose value differs from the most common value over all buildings (type relation unchecked)."""
        if Sheets._modes is None:
            from collections import Counter
            bots = self.d.bots.values()
            keys = set().union(*(set(x) for x in bots))
            Sheets._modes = {k: Counter(repr(x.get(k)) for x in bots).most_common(1)[0][0] for k in keys}
        skip = shown | {'identifier', 'type', 'size', 'itemBufferSlotMap', 'fbm_ioFluidBoxes', 'dsm_connections', 'hasFluidBoxManager',
                        'hasDataSystemManager', 'nameOverride', 'hasNameOverride', 'conversionGroup_str', 'demolitionTimeSec',
                        'hasToBeOnFoundation', 'disableLoaders', 'modularBuildingLimits', 'workstationEffectTags',
                        'hasWorkstationEffectManager', 'modularBuildingItemCost', 'modularBuildingRubble'}
        return {f: self.V(v, self.src('BuildableObjectTemplate', bid, f)) for f, v in b.items()
                if f not in skip and repr(v) != Sheets._modes.get(f) and not _SKIP_FIELD.search(f)
                and not f.startswith(('simulation', 'simType', 'spp_show', 'statusOverlay', 'spawnFlying', 'analytics'))}

    def _mark(self, vals: dict, oq) -> dict:
        return {k: self.V(v['value'], v['source'], oq=oq) for k, v in vals.items()} if oq else vals

    def _type_fields(self, bid: str, b: dict) -> dict:
        t = b.get('type') or ''
        prefixes = EXTRA_PREFIXES.get(t, (t[:1].lower() + t[1:] + '_', t[:1].lower() + t[1:]))
        out = {}
        for f, v in b.items():
            if f in POWER_FIELDS or _SKIP_FIELD.search(f) or not any(f.startswith(p) for p in prefixes):
                continue
            if v in (None, '', [], {}) or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0):
                continue
            out[f] = self.V(num(v) if f.endswith('_str') and not isinstance(v, (list, dict)) and _is_num(v) else v,
                            self.src('BuildableObjectTemplate', bid, f))
        return out

    # ------------------------------------------------------------ robot

    def robot_sheet(self, aid: str) -> dict:
        a, o = self._raw('AssemblyLineObjectTemplate', aid), self.alobjects[aid]
        S = lambda f: self.src('AssemblyLineObjectTemplate', aid, f)  # noqa: E731
        st, sell = o['starterItem'], o['sellItem']
        stages_src = f'{S("assemblyLineStages")} → foundry_main_bundle "{str(a.get("assemblyLineStages") or "").split("|")[0]}" (Odin)'
        general = {'identifier': self.V(aid, S('identifier')), 'name': self.V(o['name'], S('name')),
                   'names': self.loc('AssemblyLineObjectTemplate', aid, 'name'),
                   'description': self.V(o['description'], S('description')),
                   'starterItem': self.V(st, self.src('ItemTemplate', st, 'alStarter_alotIdentifier') + f' = {aid}') if st else None,
                   'starterItemName': self.item_name(st) if st else None,
                   'sellItem': self.V(sell, self.src('ItemTemplate', st, 'alStarter_sellItemTemplateIdentifier')) if st else None,
                   'sellItemName': self.item_name(sell) if sell else None}
        research = self.research_ref(o['researchedBy']) if o['researchedBy'] else None
        if research:
            research['identifier'] = self.V(o['researchedBy'], self.src('ResearchTemplate', o['researchedBy'], 'list_alots_str') + f' enthält {aid}')
        part_items = defaultdict(dict)   # part id -> {item: source}
        for s in o['stages']:
            for act in s['actions']:
                pa = act['producerAction']
                if pa['attachesPart']:
                    for k, e in enumerate(pa['items']):
                        part_items[pa['attachesPart']].setdefault(e['item'], self.src(
                            'AssemblyLineProducerActionTemplate', pa['identifier'], f'requiredItems[{k}].identifier')
                            + f' (partIdentifierToAttach = {pa["attachesPart"]})')
        parts = []
        for i, p in enumerate(o['parts']):
            P = lambda f, i=i: S(f'objectParts[{i}].{f}')  # noqa: E731
            items = dict(sorted(part_items.get(p['identifier'], {}).items())) or (
                {st: self.src('ItemTemplate', st, 'alStarter_alotIdentifier') + f' = {aid} (Startteil)'} if p['isInitialPart'] and st else {})
            parts.append({
                'identifier': self.V(p['identifier'], P('identifier')), 'title': self.V(p['title'], P('title')),
                'titles': self.loc('AssemblyLineObjectTemplate', aid, 'title', [('objectParts', i)]),
                'isInitialPart': self.V(p['isInitialPart'], P('isInitialPart')),
                'paintingPowerKJ': self.V(p['paintingPowerKJ'], P('requiredPowerForPainting_kj_str')),
                'paint': [{'variant': self.V(c['identifier'], P(f'colorVariants[{j}].identifier')),
                           'title': self.V(c['title'], P(f'colorVariants[{j}].title')),
                           'element': self.V(c['paintElement'], P(f'colorVariants[{j}].paintElementTemplate_identifier')),
                           'liters': self.V(c['paintLiters'], P(f'colorVariants[{j}].amountLiquidRequired_l_str'))}
                          for j, c in enumerate(p['colorVariants'])],
                'items': [{'item': self.V(x, src), 'name': self.item_name(x),
                           'recipes': [self.recipe(r) for r in sorted(self.items[x]['derived']['producedBy'])]} for x, src in items.items()],
            })
        stages = []
        for si, (s_ex, s_raw) in enumerate(zip(o['stages'], self.d.stages.get(aid, []))):
            acts = []
            for path, raw in _walk_actions(s_raw.get('stageSubActions'), f'stages[{si}].stageSubActions'):
                ex_act = next(x for x in s_ex['actions'] if x['identifier'] == raw.get('identifier'))
                pa = ex_act['producerAction']
                A = lambda f, x=pa['identifier']: self.src('AssemblyLineProducerActionTemplate', x, f)  # noqa: E731
                acts.append({
                    'position': self.V(len(acts) + 1, f'{stages_src}: Reihenfolge im Aktionsbaum (Tiefensuche)'),
                    'identifier': self.V(ex_act['identifier'], f'{stages_src}: {path}.identifier'),
                    'type': self.V(ex_act['type'], f'{stages_src}: {path}.assemblyStageActionType'),
                    'parentAction': self.V(ex_act['parentAction'], f'{stages_src}: übergeordnete Aktion im Baum'),
                    'producerAction': self.V(pa['identifier'], f'{stages_src}: {path}.identifier_machineAction'),
                    'name': self.V(pa['name'], A('name')),
                    'powerKJ': self.V(pa['powerKJ'], A('powerCost_kj_str')),
                    'peakPowerKW': self.V(_peak_kw(pa['powerKJ'], self._producer_speed()),
                                          'berechnet: 2 × floor(Kosten·10⁴ / floor(1125/Tempo)) × 60 / 10⁴ kW beim Nachladen '
                                          '(FoundryNative.dll AL_ProducerEntity::tickUpdate)', oq=OQ_AL_POWER),
                    'items': [{'item': self.V(e['item'], A(f'requiredItems[{k}].identifier')), 'name': self.item_name(e['item']),
                               'amount': self.V(e['amount'], A(f'requiredItems[{k}].amount'))} for k, e in enumerate(pa['items'])],
                    'fluids': [{'element': self.V(e['element'], A(f'requiredElements[{k}].identifier')),
                                'liters': self.V(e['liters'], A(f'requiredElements[{k}].amount') + ' / 10000')}
                               for k, e in enumerate(pa['fluids'])],
                    'attachesPart': self.V(pa['attachesPart'], A('partIdentifierToAttach')),
                })
            stages.append({'identifier': self.V(s_ex['identifier'], f'{stages_src}: stages[{si}].identifier'),
                           'title': self.V(s_ex['title'], f'{stages_src}: stages[{si}].title (nicht lokalisiert)'),
                           'orderRule': self.V('Attach-Aktionen untereinander in beliebiger Reihenfolge, jede Unteraktion (Weld) erst nach '
                                               'ihrer Elternaktion; eine nicht passende Aktion blockiert die Linie',
                                               'FoundryNative.dll AL_Item::_isReadyForActionIterativeCheck', oq=OQ_AL_ORDER),
                           'actions': acts})
        dv = o['derived']
        start_bot = next((k for k, m in self.almachines.items() if m['role'] == 'start'), None)
        prod_bot = next((k for k, m in self.almachines.items() if m['role'] == 'producer'), None)
        painter_bot = next((k for k, m in self.almachines.items() if m['role'] == 'painter'), None)
        energy = {
            'producerPowerKJ': self.V(dv['producerPowerKJ'], 'berechnet: Σ powerCost_kj_str aller Aktionen'),
            'startPowerKJ': self.V(dv['startPowerKJ'], self.src('BuildableObjectTemplate', start_bot, 'alStart_requiredPowerPerAction_kj_str')
                                   if start_bot else '–'),
            'painterPowerKJ': self.V(dv['painterPowerKJ'], 'berechnet: Σ objectParts[].requiredPowerForPainting_kj_str (alle Teile, '
                                     'auch Metall; FoundryNative.dll AL_ProducerEntity::recalculatePainterCosts)', oq=OQ_AL_PAINTER),
            'totalPowerKJ': self.V(dv['totalPowerKJ'], 'berechnet: producer + start + painter (Lackieren ist Pflicht: '
                                   'AL_EndConsumerEntity::alcm_validateItemForConsumption)', oq=OQ_AL_PAINTER),
            'startPeakPowerKW': self.V(_peak_kw(dv['startPowerKJ'], self._start_speed()) if dv['startPowerKJ'] else None,
                                       'berechnet wie peakPowerKW (FoundryNative.dll AL_StartEntity::tickUpdate)', oq=OQ_AL_POWER),
            'painterPeakPowerKW': self.V(_peak_kw(dv['painterPowerKJ'], self._producer_speed()),
                                         'berechnet wie peakPowerKW mit der Painter-Energie', oq=OQ_AL_POWER),
        }
        throughput = {
            'maxObjectsPerMinute': self.V(dv['maxObjectsPerMinute'], 'berechnet: ' + (self.src('BuildableObjectTemplate', prod_bot,
                                          'al_producer_speedInSlotsPerTick') if prod_bot else 'speed') + ' × 3600 / 1125 '
                                          '(AssemblyLineProducerActionTemplate.getItemsPerMinute; Schienengrenze)', oq=OQ_AL_THROUGHPUT),
            'singleStartObjectsPerMinute': self.V(dv['singleStartObjectsPerMinute'], 'berechnet: 3600 / ceil(1125 / '
                                                  + (self.src('BuildableObjectTemplate', start_bot, 'al_start_speedInSlotsPerTick')
                                                     if start_bot else 'speed') + ') (FoundryNative.dll AL_StartEntity::tickUpdate)',
                                                  oq=OQ_AL_THROUGHPUT, note='Aktionen haben keine eigene Dauer (nativ)'),
            'stations': self.V(f'Start → {dv["producerActionCount"]} Producer → Painter → Endverbraucher',
                               'abgeleitet: eine Aktion je Producer (AL_ProducerSetActionEvent), Painter Pflicht', oq=(OQ_AL_ORDER, OQ_AL_PAINTER)),
        }
        paint_total = [{'element': self.V(e['element'], 'abgeleitet aus ' + S('objectParts[].colorVariants[].paintElementTemplate_identifier')),
                        'liters': self.V(e['liters'], 'berechnet: Σ je Teil die größte Literzahl einer Farbe (Metall = 0 L; '
                                         'AL_Item::processPainting)', oq=OQ_AL_PAINTER)}
                       for e in dv['fullPaint']]
        inputs = [{'item': self.V(e['item'], 'berechnet: Starter-Item + Σ requiredItems aller Aktionen'), 'name': self.item_name(e['item']),
                   'amount': self.V(e['amount'], 'berechnet: Starter-Item + Σ requiredItems aller Aktionen')} for e in dv['inputs']]
        B = lambda x, f, v: self.src('BuildableObjectTemplate', x, f) + f' = {v}' if x else '–'  # noqa: E731
        machines = {'start': self.V(start_bot, B(start_bot, 'type', 'AL_Start')),
                    'producer': self.V(prod_bot, B(prod_bot, 'al_producer_machineType', 'Producer')),
                    'painter': self.V(painter_bot, B(painter_bot, 'al_producer_machineType', 'Painter')),
                    'endConsumer': self.V(next((k for k, m in self.almachines.items() if m['role'] == 'endConsumer'), None),
                                          B(next((k for k, m in self.almachines.items() if m['role'] == 'endConsumer'), None), 'type',
                                            'AL_EndConsumer'))}
        return {'kind': 'robot', **self._head(), 'robot': general, 'research': research, 'parts': parts, 'stages': stages,
                'inputs': inputs, 'paintTotal': paint_total, 'energy': energy, 'throughput': throughput, 'machines': machines,
                'sales': self.sales(sell) if sell else None,
                'quests': self._quests('ItemsMade', sell) if sell else []}

    def _producer_speed(self) -> int | None:
        return next((m['speedSlotsPerTick'] for m in self.almachines.values() if m['role'] == 'producer'), None)

    def _start_speed(self) -> int | None:
        return next((m['speedSlotsPerTick'] for m in self.almachines.values() if m['role'] == 'start'), None)

    # ------------------------------------------------------------ entry

    def sheet(self, query: str, kind: str | None = None) -> dict:
        k, ident, others = self.resolve(query, kind)
        s = {'robot': self.robot_sheet, 'building': self.building_sheet, 'item': self.item_sheet}[k](ident)
        s['query'] = query
        s['alsoMatched'] = others
        return s


def _is_num(v) -> bool:
    try:
        num(v)
        return True
    except ValueError:
        return False


def _walk_actions(lst, path: str):
    """(path, raw action) in depth-first order (decoded Odin stages)."""
    for i, x in enumerate((lst or {}).get('$items', [])):
        p = f'{path}.$items[{i}]'
        yield p, x
        yield from _walk_actions(x.get('subActions'), f'{p}.subActions')


def _peak_kw(cost_kj, speed) -> float | None:
    if not cost_kj or not speed:
        return None
    per_tick = 2 * ((round(cost_kj * 10000)) // (RAIL_ITEM_LENGTH // speed))
    return round(per_tick * TICKS_PER_SECOND / 10000, 2)


# ---------------------------------------------------------------- markdown

def _plain(v) -> str:
    if isinstance(v, dict) and 'value' in v:
        v = v['value']
    if v is None or v == []:
        return '–'
    if isinstance(v, bool):
        return 'ja' if v else 'nein'
    if isinstance(v, float):
        return f'{v:.4f}'.rstrip('0').rstrip('.')
    if isinstance(v, list):
        return ', '.join(_plain(x) for x in v) or '–'
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _cell(v) -> str:
    s = re.sub(r'\s*[\r\n]+\s*', ' ', _plain(v)).replace('|', '\\|')
    if isinstance(v, dict) and v.get('ungemessen'):
        s += ' **ungemessen**'
    return s


def _srccell(v) -> str:
    if not isinstance(v, dict) or 'source' not in v:
        return ''
    s = f'`{v["source"]}`'.replace('|', '\\|')
    if v.get('ungemessen'):
        s += f' · ungemessen: {v["ungemessen"]}'
    if v.get('note'):
        s += f' · {v["note"]}'
    return s


def _table(rows, head=('Feld', 'Wert', 'Quelle')) -> list[str]:
    rows = [(k, v) for k, v in rows if v is not None]
    if not rows:
        return ['–', '']
    out = [f'| {" | ".join(head)} |', '|' + '---|' * len(head)]
    out += [f'| {k} | {_cell(v)} | {_srccell(v)} |' for k, v in rows]
    return out + ['']


def _idn(ident, name=None) -> str:
    """'Name (`identifier`)' or '`identifier`'."""
    n = _plain(name) if name is not None else '–'
    return f'{n} (`{_plain(ident)}`)' if n != '–' else f'`{_plain(ident)}`'


def _join(*parts) -> str:
    return ', '.join(x for part in parts for x in part) or '–'


def _names_rows(names: dict, label: str = 'Name') -> list:
    return [(f'{label} ({lang})', v) for lang, v in names.items()]


def _amounts(items, fluids=()) -> str:
    return _join((f'{_plain(e["amount"])}× {_idn(e["item"], e.get("name"))}'
                  + (f' ({_plain(e["chance"])})' if 'chance' in e and e['chance']['value'] != 1 else '') for e in items),
                 (f'{_plain(e["liters"])} L `{_plain(e["element"])}`' for e in fluids))


def _rates_txt(pm: dict | None, key_items: str, key_fluids: str) -> str:
    if not pm:
        return '–'
    return _join((f'{_cell(e["perMin"])} {_idn(e["item"], e.get("name"))}' for e in pm[key_items]),
                 (f'{_cell(e["litersPerMin"])} L `{_plain(e["element"])}`' for e in pm[key_fluids]))


def _recipe_md(r: dict, title_prefix: str = '') -> list[str]:
    out = [f'#### {title_prefix}{_plain(r["name"])} (`{_plain(r["identifier"])}`)', '']
    rows = [('Identifier', r['identifier']), ('Tags', r['tags'])]
    rows += [(f'Tag-Name `{t}`', n) for t, n in zip(r['tags']['value'], r['tagNames'])]
    rows += [('Kategorie', r['category']), ('Kategorie-Name', r['categoryName']), ('Zeit (timeMs)', r['timeMs']),
             ('Im Handwerk ausgeblendet', r['hiddenInCharacterCrafting'])]
    out += _table(rows)
    rows = [(f'Zutat: {_idn(e["item"], e["name"])}', e['amount']) for e in r['inputs']]
    rows += [(f'Fluid-Zutat: `{_plain(e["element"])}` (L)', e['liters']) for e in r['fluidInputs']]
    rows += [(f'Ausgabe: {_idn(e["item"], e["name"])}', e['amount']) for e in r['outputs']]
    rows += [(f'Wahrscheinlichkeit `{_plain(e["item"])}`', e['chance']) for e in r['outputs']]
    rows += [(f'Fluid-Ausgabe: `{_plain(e["element"])}` (L)', e['liters']) for e in r['fluidOutputs']]
    out += _table(rows, ('Menge', 'Wert', 'Quelle'))
    if r['producers']:
        out += ['| Maschine | Faktor | Zeit (s) | Ausgaben / min | Zutaten / min | Quelle Maschine | Quelle Faktor |',
                '|---|---|---|---|---|---|---|']
        for p in r['producers']:
            out.append(f'| {_idn(p["machine"], p["machineName"])} | {_cell(p["speedMultiplier"])} | {_cell(p["craftTimeSec"])} | '
                       f'{_rates_txt(p["perMinute"], "outputs", "fluidOutputs")} | {_rates_txt(p["perMinute"], "inputs", "fluidInputs")} | '
                       f'{_srccell(p["machine"])} | {_srccell(p["speedMultiplier"])} |')
        src = {p['craftTimeSec']['source'] for p in r['producers']} | {CALC_RATE}
        out += ['', 'Zeit und Raten: ' + '; '.join(f'`{s}`' for s in sorted(src))]
        un = sorted({p['craftTimeSec'].get('ungemessen') for p in r['producers'] if p['craftTimeSec'].get('ungemessen')})
        if un:
            out.append('Ungemessen: ' + '; '.join(un))
        notes = sorted({p['craftTimeSec'].get('note') for p in r['producers'] if p['craftTimeSec'].get('note')})
        if notes:
            out.append('Hinweis: ' + '; '.join(notes))
        out.append('')
    else:
        out += ['Keine Maschine stellt dieses Rezept her.', '']
    out += _unlock_md(r['unlockedBy'])
    return out


def _unlock_md(ub: dict) -> list[str]:
    out = []
    for rs in ub['research']:
        out += [f'Freigeschaltet durch Forschung **{_plain(rs["name"])}** (`{_plain(rs["identifier"])}`)', '']
        out += _research_rows(rs)
    for e in ub['explorationUnlocks']:
        out += [f'Freigeschaltet durch Erkundung **{_plain(e["title"])}** (`{_plain(e["identifier"])}`)', '']
        rows = [('Identifier', e['identifier'])] + [(f'Kosten `{_plain(q["item"])}`', q['amount']) for q in e['requirements']]
        rows += [('Dauer (s)', e['secondsToUnlock'])] + [('Voraussetzung (Erkundung)', x) for x in e['dependencies']]
        rows += [('Voraussetzung (Forschung)', x) for x in e['researchDependencies']]
        out += _table(rows)
    return out


def _research_rows(rs: dict) -> list[str]:
    rows = [('Identifier', rs['identifier'])]
    rows += [(f'Kosten: {_idn(c["item"], c["name"])}', c['amount']) for c in rs['cost']]
    rows += [('Sekunden pro Wissenschafts-Item', rs['secondsPerScienceItem']), ('Dauer mit 1 Server (s)', rs['timeSecOneServer'])]
    rows += [(f'Voraussetzung: {_plain(d["name"])}', d['identifier']) for d in rs['dependencies']]
    rows += [('Firmenrang', rs['requiredCompanyRank'])]
    if 'endlessManualLevels' in rs:
        rows.append(('Endlos: manuelle Stufen', rs['endlessManualLevels']))
    return _table(rows)


def _refs_md(title: str, refs: list[dict]) -> list[str]:
    if not refs:
        return []
    out = [f'## {title} ({len(refs)})', '', '<details><summary>anzeigen</summary>', '', '| Typ | Template | Feld |', '|---|---|---|']
    out += [f'| {r["type"]} | `{r["identifier"]}` | `{r["source"]}` |' for r in refs]
    return out + ['', '</details>', '']


def _head_md(s: dict, title: str) -> list[str]:
    where = (f'`Templates/…` = `{s["templatesDir"]}`. ' if s['templateSource'] == 'StreamingAssets/Templates'
             else '`foundry_main_bundle:<Typ>/<Identifier>` = Template im Asset-Bundle des Spiels. ')
    out = [f'# {title}', '',
           f'Spielversion {s["gameVersion"]} (Steam-Build {s["steamBuildId"] or "?"}), Template-Quelle `{s["templateSource"]}`. {where}'
           f'Jeder Wert mit Quelle; **ungemessen** = nur aus Code/Disassembly belegt, noch nicht im Spiel gemessen ({s["openQuestions"]}).', '']
    if s.get('alsoMatched'):
        out += [f'Ebenfalls gefunden für "{s["query"]}": ' + ', '.join(f'`{x}`' for x in s['alsoMatched'][:10])
                + (f' (+{len(s["alsoMatched"]) - 10})' if len(s['alsoMatched']) > 10 else '')
                + ' (Auswahl mit Identifier oder `--kind item|building|robot`).', '']
    return out


def _item_rows(it: dict) -> list:
    return [('Identifier', it['identifier']), ('Name (Template)', it['name']), *_names_rows(it['names']),
            ('Beschreibung', it['description']), ('Erkundungs-Text', it.get('explorationFlavorText')), ('Stack Size', it['stackSize']),
            ('Kategorie', it['category']), ('Kategorie-Name', it['categoryName']), ('Flags', it['flags']), ('Versteckt', it['hidden']),
            ('Gewicht (g)', it['weightGrams'])]


def _sales_md(sales: dict | None) -> list[str]:
    labels = {'salesItem': 'Verkaufs-Item', 'category': 'Verkaufskategorie', 'categoryName': 'Verkaufskategorie (Name)',
              'industry': 'Industrie', 'industryName': 'Industrie (Name)', 'basePrice': 'Base Price', 'baseDemandPerDay': 'Base Demand pro Tag',
              'skyPlatformBaseCapacity': 'Sky-Platform-Grundkapazität', 'hiddenByResearch': 'verborgen bis Forschung',
              'salesCurrency': 'Verkaufswährung', 'salesCurrencySkyPlatformBaseCapacity': 'Währung: Sky-Platform-Grundkapazität',
              'salesCurrencyHiddenByResearch': 'Währung: verborgen bis Forschung', 'marketBuyPrice': 'Handel: Kaufpreis',
              'marketSellPrice': 'Handel: Verkaufspreis', 'tradeableOnStation': 'auf der Station handelbar'}
    return ['## Verkauf', ''] + _table([(labels.get(k, k), v) for k, v in (sales or {}).items()])


def _texts_details(title: str, texts: dict) -> list[str]:
    if not texts:
        return []
    out = [f'<details><summary>{title}</summary>', '']
    out += _table([(lang, v) for lang, v in texts.items()], ('Sprache', 'Text', 'Quelle'))
    return out + ['</details>', '']


def _gathering_md(gathering: list[dict]) -> list[str]:
    if not gathering:
        return []
    out = ['## Gewinnung ohne Rezept', '', '| Art | Quelle-Objekt | Werte | Quelle |', '|---|---|---|---|']
    for g in gathering:
        vals = '; '.join(f'{k}: {_cell(v)}' for k, v in g.items() if k not in ('how', 'from', 'fromName', 'yields') and v is not None)
        srcs = ' · '.join(_srccell(v) for k, v in g.items() if k not in ('how', 'fromName') and isinstance(v, dict) and 'source' in v)
        out.append(f'| {g["how"]} | {_idn(g["from"], g["fromName"])} | {vals or "–"} | {srcs} |')
    return out + ['']


def _power_rows(power: dict) -> list:
    labels = POWER_LABELS | {'energyPerActionKJ': 'Energie je Aktion (kJ)', 'energyPerObjectKJ': 'Energie je Roboter (kJ)',
                             'peakPowerKW': 'Spitze beim Nachladen (kW)', 'continuousDraw': 'Dauerverbrauch',
                             'workstationEffectTags': 'Workstation-Tags', 'workstationBonus': 'Workstation-Bonus'}
    return [(labels.get(k, k), v) for k, v in power.items()]


def render_markdown(s: dict) -> str:
    k = s['kind']
    out: list[str] = []
    if k == 'item':
        it = s['item']
        out += _head_md(s, f'{_plain(it["name"])} (`{_plain(it["identifier"])}`) – Item')
        out += ['## Allgemein', ''] + _table(_item_rows(it)) + _texts_details('Beschreibung in allen Sprachen', it['descriptions'])
        out += _texts_details('Erkundungs-Text in allen Sprachen', it.get('explorationFlavorTexts') or {})
        out += _sales_md(s['sales'])
        f = s['fuel']
        out += ['## Brennstoff', ''] + _table([('Brennwert (kJ)', f['fuelValueKJ']), ('Flag BURNABLE', f.get('burnable')),
                                               ('Rückstand', f.get('residualItem')), ('Jetpack-Treibstoff', f.get('jetpackFuel')),
                                               ('Brenndauer', f.get('burnTime'))])
        for m in f.get('machines', []):
            out += [f'Brennstoff in **{_idn(m["machine"], m["name"])}**', '']
            out += _table([(kk, vv) for kk, vv in m.items() if kk != 'name'])
        if s.get('workstation'):
            w = s['workstation']
            out += ['## Workstation-Effekt', ''] + _table([('Wirkung', w['effect']), ('data01', w['data01']), ('data02', w['data02']),
                                                          ('Bonus (%)', w['bonusPercent']), ('Mehrverbrauch (%)', w['powerIncreasePercent']),
                                                          ('nur für Tags', w['requiredTags']), ('nicht für Tags', w['excludedTags'])])
        if s.get('recycling'):
            out += ['## Recycling dieses Items ergibt', ''] + _table([(_idn(r['item'], r['name']), r['chance']) for r in s['recycling']],
                                                                    ('Ergebnis', 'Chance', 'Quelle'))
        out += [f'## Herstellung ({len(s["recipesProducing"])} Rezepte)', '']
        for r in s['recipesProducing']:
            out += _recipe_md(r)
        out += _gathering_md(s['gathering'])
        out += [f'## Verwendung in Rezepten ({len(s["recipesUsing"])})', '']
        if s['recipesUsing']:
            out += ['| Rezept | Menge | Zeit (ms) | Ausgaben (Chance) | Maschinen | Quelle |', '|---|---|---|---|---|---|']
            for u in s['recipesUsing']:
                machines = ', '.join(_idn(m['machine'], m['name']) for m in u['machines']) or '–'
                out.append(f'| {_idn(u["recipe"], u["name"])} | {_cell(u["amount"])} | {_cell(u["timeMs"])} | '
                           f'{_amounts(u["outputs"], u["fluidOutputs"])} | {machines} | {_srccell(u["amount"])} |')
            out.append('')
        else:
            out += ['–', '']
        if s['assemblyLine']:
            out += ['## Verwendung in der Assembly Line', '']
            out += _table([(f'{_idn(a["object"], a["name"])}: {_plain(a["role"])}', a['amount']) for a in s['assemblyLine']])
        if s['blastFurnace']:
            out += ['## Verwendung im Hochofen', '']
            for m in s['blastFurnace']:
                out += [f'Modus **{_idn(m["mode"], m["name"])}**', '']
                out += _table([('benötigte Menge dieses Items', m['amount'])] +
                              [(f'Eingang `{_plain(e["item"])}`', e['amount']) for e in m['inputs']] +
                              [(f'Ausgang `{_plain(e["element"])}` (L)', e['liters']) for e in m['outputs']] + [('Rate', m['note'])])
        if s['researchCosts']:
            out += [f'## Forschungskosten ({len(s["researchCosts"])} Forschungen)', '', '<details><summary>anzeigen</summary>', '']
            out += _table([(_idn(r['research'], r['name']), r['amount']) for r in s['researchCosts']],
                          ('Forschung', 'Menge', 'Quelle')) + ['</details>', '']
        if s['explorationRequirements']:
            out += ['## Erkundung (benötigt das Item)', '']
            for e in s['explorationRequirements']:
                out += [f'**{_idn(e["explorationUnlock"], e["title"])}**', '']
                rows = [('benötigte Menge', e['amount']), ('Wirkung (Flags)', e['flags']), ('Beschreibung', e['description']),
                        ('Charakterherstellungstempo (%)', e['effect'])]
                rows += [('schaltet Rezept frei', x) for x in e['recipeUnlocks']] + [(kk, vv) for kk, vv in e['effectFields'].items()]
                out += _table(rows)
        out += _quests_md(s['quests'])
        out += _refs_md('Weitere Verweise in Templates', s['otherReferences'])
    elif k == 'building':
        bd = s['building']
        title_mark = ' (Name **ungemessen**)' if bd['name'].get('ungemessen') else ''
        out += _head_md(s, f'{_plain(bd["name"])} (`{_plain(bd["identifier"])}`) – Gebäude{title_mark}')
        rows = [('Identifier', bd['identifier']), ('Name', bd['name']), *_names_rows(bd['names']), ('Modus', bd['modeName']),
                *_names_rows(bd.get('modeNames') or {}, 'Modus'), ('Bau-Item', bd['item']), ('weitere Bau-Items', bd['itemAlternatives']),
                ('Maschinen-Typ', bd['type']), ('Tier', bd['tier']), ('Umbau-Gruppe', bd['conversionGroup'])]
        rows += [(f'Gruppe: {_plain(m["name"])}', m['identifier']) for m in bd['conversionGroupMembers']]
        rows += [(f'Größe {a}', v) for a, v in bd['size'].items()]
        rows += [('Abrisszeit (s)', bd['demolitionTimeSec']), ('braucht Fundament', bd['hasToBeOnFoundation'])]
        out += ['## Allgemein', ''] + _table(rows)
        out += ['## Strom', ''] + _table(_power_rows(s['power']))
        c = s['connections']
        rows = [(f'Item-Slots „{_plain(g["header"])}“ ({len(g["slots"])})', {'value': ', '.join(_plain(x) for x in g['slots']),
                 'source': g['slots'][0]['source'] if g['slots'] else g['header']['source']}) for g in c['itemSlots']]
        rows += [('Lader gesperrt', c['loadersDisabled']), ('Datenanschlüsse', c['dataConnections'])]
        rows += [(f'Fluid-Box {i + 1}: {kk}', vv) for i, fb in enumerate(c['fluidBoxes']) for kk, vv in fb.items()]
        for m in c.get('modules', []):
            rows.append((f'Modul {_idn(m["module"], m["name"])} min / max', {
                'value': f'{_plain(m["min"])} / {_plain(m["max"])}', 'source': f'{m["min"]["source"]}, maxAmount'}))
            rows += [(f'  Kosten {_idn(e["item"], e["name"])}', e['amount']) for e in m['cost']]
        out += ['## Anschlüsse', ''] + _table(rows)
        out += ['## Reichweite', ''] + _table(list(s['range'].items()))
        out += ['## Typspezifische Felder', ''] + _table(list(s['typeFields'].items()))
        if s['otherFields']:
            out += ['<details><summary>Weitere vom Standard abweichende Template-Felder (Typzugehörigkeit nicht geprüft)</summary>', '']
            out += _table(list(s['otherFields'].items())) + ['</details>', '']
        if s['crafting']:
            cr = s['crafting']
            out += ['## Herstellung', ''] + _table([('Art', cr['kind']), ('Geschwindigkeitsfaktor', cr['speedMultiplier']),
                                                    ('Rezeptauswahl', cr['recipeSelection']), ('Tags', cr['tags'])])
            out += [f'### Rezepte auf dieser Maschine ({len(cr["recipes"])})', '',
                    '| Rezept | Zeit (ms) | Zeit hier (s) | Zutaten | Ausgaben (Chance) | Ausgaben / min | Zutaten / min | Quelle |',
                    '|---|---|---|---|---|---|---|---|']
            for r in cr['recipes']:
                out.append(f'| {_idn(r["recipe"], r["name"])} | {_cell(r["timeMs"])} | {_cell(r["craftTimeSec"])} | '
                           f'{_amounts(r["inputs"], r["fluidInputs"])} | {_amounts(r["outputs"], r["fluidOutputs"])} | '
                           f'{_rates_txt(r["perMinute"], "outputs", "fluidOutputs")} | {_rates_txt(r["perMinute"], "inputs", "fluidInputs")} | '
                           f'`{r["recipe"]["source"].rsplit(" : ", 1)[0]}` : input_data / output_data |')
            if cr['recipes']:
                r0 = next((r for r in cr['recipes'] if r['perMinute']), cr['recipes'][0])
                out += ['', f'Zeit hier: {_srccell(r0["craftTimeSec"])}', f'Raten: `{CALC_RATE}`', '']
        if s['assemblyLine']:
            out += ['## Assembly Line', ''] + _table(list(s['assemblyLine'].items()))
        if s['buildItem']:
            out += ['## Bau-Item', ''] + _table(_item_rows(s['buildItem'])) + _texts_details('Beschreibung in allen Sprachen',
                                                                                         s['buildItem']['descriptions'])
        if s.get('moduleCost'):
            mc = s['moduleCost']
            out += ['## Baukosten als Modul', ''] + _table([('Beschreibung', mc['description'])] +
                                                           [(f'Kosten {_idn(e["item"], e["name"])}', e['amount']) for e in mc['cost']] +
                                                           [(f'Schutt beim Abriss `{_plain(e["item"])}`', e['amount']) for e in mc['rubble']])
            if mc['unlockedBy']:
                out += [f'Freigeschaltet durch Forschung **{_plain(mc["unlockedBy"]["name"])}**', ''] + _research_rows(mc['unlockedBy'])
        out += [f'## Baukosten ({len(s["buildCost"])} Rezepte)', '']
        for r in s['buildCost']:
            out += _recipe_md(r)
        out += _quests_md(s['quests'])
        out += _refs_md('Weitere Verweise in Templates', s['otherReferences'])
    else:
        ro = s['robot']
        out += _head_md(s, f'{_plain(ro["name"])} (`{_plain(ro["identifier"])}`) – Assembly-Line-Roboter')
        out += ['## Allgemein', ''] + _table([('Identifier', ro['identifier']), ('Name', ro['name']), *_names_rows(ro['names']),
                                              ('Beschreibung', ro['description']), ('Starter-Item', ro['starterItem']),
                                              ('Starter-Item (Name)', ro['starterItemName']), ('Verkaufs-Item', ro['sellItem']),
                                              ('Verkaufs-Item (Name)', ro['sellItemName'])])
        out += ['## Maschinen der Linie', ''] + _table([(kk, vv) for kk, vv in s['machines'].items()])
        if s['research']:
            out += [f'## Forschung: {_plain(s["research"]["name"])}', ''] + _research_rows(s['research'])
        out += ['## Teile', '']
        seen: dict[str, str] = {}
        for p in s['parts']:
            out += [f'### {_plain(p["title"])} (`{_plain(p["identifier"])}`)', '']
            rows = [('Identifier', p['identifier']), ('Startteil', p['isInitialPart']), ('Lackier-Energie (kJ)', p['paintingPowerKJ'])]
            rows += [(f'Name ({lang})', v) for lang, v in p['titles'].items()]
            rows += [(f'Lack {_plain(c["title"])} ({_plain(c["element"])}), L', c['liters']) for c in p['paint']]
            out += _table(rows)
            for x in p['items']:
                iid = _plain(x['item'])
                out += [f'Teil-Item **{_idn(x["item"], x["name"])}**, Quelle: `{x["item"]["source"]}`', '']
                if iid in seen:
                    out += [f'Rezept siehe Teil {seen[iid]}.', '']
                    continue
                seen[iid] = _plain(p['title'])
                for r in x['recipes']:
                    out += _recipe_md(r, 'Rezept: ')
        out += ['## Stufen und Aktionen (Reihenfolge)', '']
        for st in s['stages']:
            out += [f'### Stufe {_plain(st["title"])} (`{_plain(st["identifier"])}`)', '',
                    f'Quelle: `{st["identifier"]["source"]}`', '',
                    f'Reihenfolge-Regel: {_cell(st["orderRule"])} – {_srccell(st["orderRule"])}', '',
                    '| # | Aktion | Typ | Producer-Aktion | kJ | Spitze kW | Items / Fluide | Teil | Quelle kJ |', '|---|---|---|---|---|---|---|---|---|']
            for a in st['actions']:
                ind = '↳ ' if a['parentAction']['value'] else ''
                out.append(f'| {_cell(a["position"])} | {ind}`{_plain(a["identifier"])}` | {_plain(a["type"])} | '
                           f'`{_plain(a["producerAction"])}` {_plain(a["name"])} | {_cell(a["powerKJ"])} | {_cell(a["peakPowerKW"])} | '
                           f'{_amounts(a["items"], a["fluids"])} | {_plain(a["attachesPart"])} | {_srccell(a["powerKJ"])} |')
            if st['actions']:
                a0 = st['actions'][0]
                out += ['', f'#: {_srccell(a0["position"])}', f'Spitze kW: {_srccell(a0["peakPowerKW"])}']
            out.append('')
        out += ['## Zutaten gesamt', ''] + _table([(_idn(e['item'], e['name']), e['amount']) for e in s['inputs']])
        out += ['## Lack gesamt (alle Teile in einer Farbe außer Metall)', ''] + _table([(_plain(e['element']), e['liters']) for e in s['paintTotal']])
        labels = {'producerPowerKJ': 'Producer-Energie (kJ)', 'startPowerKJ': 'Start-Energie (kJ)', 'painterPowerKJ': 'Painter-Energie (kJ)',
                  'totalPowerKJ': 'Gesamtenergie pro Roboter (kJ)', 'startPeakPowerKW': 'Start: Spitze beim Nachladen (kW)',
                  'painterPeakPowerKW': 'Painter: Spitze beim Nachladen (kW)'}
        out += ['## Energie', ''] + _table([(labels[k2], v) for k2, v in s['energy'].items()])
        labels = {'maxObjectsPerMinute': 'Schienengrenze (Roboter/min)', 'singleStartObjectsPerMinute': 'ein AL-Start (Roboter/min)',
                  'stations': 'Stationen'}
        out += ['## Durchsatz', ''] + _table([(labels[k2], v) for k2, v in s['throughput'].items()])
        out += _sales_md(s['sales'])
        out += _quests_md(s['quests'])
    return '\n'.join(out).rstrip() + '\n'


def _quests_md(quests: list[dict]) -> list[str]:
    if not quests:
        return []
    out = ['## Quests', '']
    return out + _table([(f'{_plain(q["title"]) if _plain(q["title"]) != "–" else _plain(q["quest"])} (`{_plain(q["quest"])}`), '
                          f'{_plain(q["condition"])}{", Meilenstein" if q["milestone"]["value"] else ""}', q['amount']) for q in quests],
                        ('Quest', 'Menge', 'Quelle'))
