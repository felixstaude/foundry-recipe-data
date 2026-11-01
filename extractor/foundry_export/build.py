"""Builds the foundry-data v1 JSON documents (see findings/schema.md)."""
from __future__ import annotations

from collections import Counter, defaultdict

from .game import GamePaths, flags, num, r4, strip_asset_ref, text
from .localization import key as lkey
from .odin_binary import decode as odin_decode
from .unity_bundle import UnityFSBundle, read_odin_scriptable_object

TICKS_PER_SECOND = 60          # GameRoot.LOCKSTEP_TICKS_PER_SECOND
SLOTS_PER_METER = 600          # AssemblyLineSystem.SLOTS_PER_METER
RAIL_ITEM_LENGTH = 1125        # AssemblyLineSystem.RAIL_ITEM_LENGTH
CHARACTER_SPEED = 3            # FoundryNative CraftingAction::reinitialize: timeMs / 3 (the C# tooltip helper
                               # Character.getCraftingTimeForRecipeInMs shows timeMs / 5 - see findings/verification.md)
CHARACTER_MACHINE_ID = 'character'
MACHINE_MS_PER_TICK_FPM = 166666   # FoundryNative *::tryStartProduction / BaseStationFurnace: ms -> ticks (x10000)

AL_ROLES = {'AL_Start': 'start', 'AL_Rail': 'rail', 'AL_EndConsumer': 'endConsumer',
            'AL_Merger': 'merger', 'AL_Splitter': 'splitter'}


class Data:
    def __init__(self, gp: GamePaths, source_mode: str = 'auto'):
        from .checks import EXPORTED_TYPES
        from .sources import open_template_source
        self.gp = gp
        self.warnings: list[str] = []
        self.bundle = UnityFSBundle(str(gp.main_bundle))
        # YAML dump, or the bundle when the dump is missing/incomplete or differs from it (sources.py)
        self.source = open_template_source(gp, self.warnings, bundle=self.bundle, mode=source_mode, types=EXPORTED_TYPES)
        lt = self.source.load
        self.items = lt('ItemTemplate')
        self.elements = lt('ElementTemplate')
        self.tags = lt('CraftingTag')
        self.recipes = lt('CraftingRecipe')
        self.bots = lt('BuildableObjectTemplate')
        self.research = lt('ResearchTemplate')
        self.exploration = lt('ExplorationUnlockTemplate')
        self.alots = lt('AssemblyLineObjectTemplate')
        self.alpas = lt('AssemblyLineProducerActionTemplate')
        self.stages = self._load_stages()

    def _load_stages(self) -> dict[str, list]:
        """ALOT identifier -> decoded AssemblyStage[] from the main bundle."""
        wanted = {}
        for ident, a in self.alots.items():
            path = strip_asset_ref(a.get('assemblyLineStages'))
            if not path:
                self.warnings.append(f'ALOT {ident} has no assemblyLineStages')
                continue
            wanted[path.lower()] = ident
        out = {}
        for sf in self.bundle.serialized_files():
            container = sf.container()
            for path, ident in wanted.items():
                if path in container:
                    _name, fmt, data = read_odin_scriptable_object(sf.object_bytes(container[path]), sf.little)
                    if fmt != 0:
                        raise SystemExit(f'{path}: unsupported Odin SerializedFormat {fmt}')
                    out[ident] = odin_decode(data)['stages']['$items']
        for path, ident in wanted.items():
            if ident not in out:
                self.warnings.append(f'stages asset not found in bundle: {path}')
        return out


def _sorted(d: dict) -> list:
    return [d[k] for k in sorted(d)]


def _io_items(lst) -> list[dict]:
    return [{'item': e['identifier'], 'amount': int(e['amount'])} for e in (lst or [])]


def _chance(d: 'Data', recipe: str, e: dict):
    c = num(e.get('percentage_str', 1))
    if c is None:
        d.warnings.append(f'recipe {recipe}: output {e.get("identifier")} has no percentage_str - chance taken as 1')
        return 1
    return c


def _fluids(lst, amount_key='amount_str') -> list[dict]:
    return [{'element': e['identifier'], 'liters': num(e[amount_key])} for e in (lst or [])]


# ---------------------------------------------------------------- machines / crafting

def _machine_crafting(b: dict) -> dict | None:
    t = b.get('type')
    if t == 'Producer':
        fixed = b.get('producerRecipeType') == 'Fixed'
        return {'kind': 'Producer', 'speedMultiplier': num(b.get('producer_recipeTimeModifier_str')),
                'recipeSelection': 'fixed' if fixed else 'tags',
                'tags': [] if fixed else list(b.get('producer_recipeType_tags') or []),
                'fixedRecipe': text(b.get('producer_recipeType_fixed')) if fixed else None}
    if t == 'AutoProducer':
        tag = text(b.get('autoProducer_recipeType_tag'))
        return {'kind': 'AutoProducer', 'speedMultiplier': num(b.get('autoProducer_recipeTimeModifier_str')),
                'recipeSelection': 'tags', 'tags': [tag] if tag else [], 'fixedRecipe': None}
    if t == 'ModularEntityProducer':
        fixed = text(b.get('modularProducer_fixedCraftingRecipeIdentifier'))
        return {'kind': 'ModularEntityProducer', 'speedMultiplier': num(b.get('modularProducer_recipeTimeModifier_str')),
                'recipeSelection': 'fixed' if fixed else 'tags',
                'tags': [] if fixed else list(b.get('modularProducer_recipeType_tags') or []),
                'fixedRecipe': fixed}
    if t == 'BaseStation':
        return {'kind': 'BaseStation', 'speedMultiplier': 1, 'recipeSelection': 'list', 'tags': [],
                'fixedRecipe': None, 'recipeList': list(b.get('baseStation_craftingRecipeIdentifier') or [])}
    return None


def _accepts(craft: dict, recipe: dict) -> bool:
    if craft['recipeSelection'] == 'fixed':
        return craft['fixedRecipe'] == recipe['identifier']
    if craft['recipeSelection'] == 'list':
        return recipe['identifier'] in craft['recipeList']
    return bool(set(craft['tags']) & set(recipe.get('tags') or []))


def _rateable(recipe: dict) -> bool:
    return all(e.get('liters') is not None for e in recipe['fluidInputs'] + recipe['fluidOutputs'])


def _round_div(a: int, b: int) -> int:
    """Native muldiv rounding (half away from zero) for non-negative a, positive b."""
    return (2 * a + b) // (2 * b)


def character_ticks(time_ms: int) -> int:
    """Hand-crafting duration in 60 Hz ticks without exploration bonus, exactly as FoundryNative
    CraftingAction::reinitialize: round(timeMs*1e4*1e4/30000) -> /1000 -> round(*600000/1e4) -> /1e4, min 1 tick."""
    a = _round_div(time_ms * 10**8, 30000)
    return max(1, _round_div((a // 1000) * 600000, 10000) // 10000)


def base_station_ticks(time_ms: int) -> int:
    """Base station furnace duration in whole ticks (BaseStationFurnace::tickUpdate: timeMs*1e8/166666, /1e4)."""
    return max(1, (time_ms * 10**8 // MACHINE_MS_PER_TICK_FPM) // 10**4)


def _rates(recipe: dict, speed: float, craft_sec: float | None = None) -> dict:
    t = recipe['timeMs'] / 1000.0
    f = speed * 60.0 / t if craft_sec is None else 60.0 / craft_sec
    return {
        'inputs': [{'item': e['item'], 'perMin': r4(e['amount'] * f)} for e in recipe['inputs']],
        'outputs': [{'item': e['item'], 'perMin': r4(e['amount'] * e['chance'] * f)} for e in recipe['outputs']],
        'fluidInputs': [{'element': e['element'], 'litersPerMin': r4(e['liters'] * f)} for e in recipe['fluidInputs']],
        'fluidOutputs': [{'element': e['element'], 'litersPerMin': r4(e['liters'] * f)} for e in recipe['fluidOutputs']],
    }


def _machine_names(d: Data) -> dict[str, dict]:
    """BOT -> {name, item, modeName, modeIndex, itemAlternatives}, resolved like the game:
    items with flag BUILDABLE_OBJECT set bot.parentItemTemplate (ItemTemplateManager.cs, after the template load; with
    several such items the last one in load order wins, which the assets do not define -> we prefer the item with the
    BOT's own identifier, then the item that lists the BOT as a mode, then the first by identifier, and list the others);
    items with toggleableModeType MultipleBuildings fill BOTs that have no parent item yet (ItemTemplate.onLoadPostprocess);
    hasNameOverride/nameOverride wins over the item name (CraftingTT_MachineRowEntry, PowerGridFrame)."""
    direct, modes = defaultdict(list), {}
    for ident in sorted(d.items):
        it = d.items[ident]
        bo = text(it.get('buildableObjectIdentifer'))
        if bo and 'BUILDABLE_OBJECT' in flags(it.get('flags')):
            direct[bo].append(ident)
        if it.get('toggleableModeType') == 'MultipleBuildings':
            for i, m in enumerate(it.get('toggleableModes') or []):
                mid = text(m.get('identifier'))
                if mid:
                    modes.setdefault(mid, []).append((ident, i, text(m.get('name'))))
    out = {}
    for ident, b in d.bots.items():
        cands, mode_of = direct.get(ident, []), modes.get(ident, [])
        mode_items = [m[0] for m in mode_of]
        if cands:
            item = next((c for c in cands if c == ident), None) or next((c for c in cands if c in mode_items), None) or cands[0]
        else:
            item = mode_items[0] if mode_items else None
        mode = next((m for m in mode_of if m[0] == item), None)
        override = text(b.get('nameOverride')) if b.get('hasNameOverride') else None
        out[ident] = {'name': override or (d.items[item].get('name') if item else None), 'item': item,
                      'nameOverride': bool(override), 'modeName': mode[2] if mode else None,
                      'modeIndex': mode[1] if mode else None,
                      'itemAlternatives': sorted(set(cands + mode_items) - {item})}
    return out


def _al_machine(b: dict, name) -> dict | None:
    t = b.get('type')
    if t not in AL_ROLES and t != 'AL_Producer':
        return None
    m = {'identifier': b['identifier'], 'name': name, 'type': t}
    if t == 'AL_Producer':
        m['role'] = 'painter' if b.get('al_producer_machineType') == 'Painter' else 'producer'
        m['machineType'] = b.get('al_producer_machineType')
        m['speedSlotsPerTick'] = b.get('al_producer_speedInSlotsPerTick')
        m['slotWidths'] = {'input': b.get('al_producer_slotWidth_input'), 'output': b.get('al_producer_slotWidth_output')}
    elif t == 'AL_Start':
        m['role'] = 'start'
        m['speedSlotsPerTick'] = b.get('al_start_speedInSlotsPerTick')
        m['slotWidths'] = {'output': b.get('al_start_slotWidth')}
        m['powerPerActionKJ'] = num(b.get('alStart_requiredPowerPerAction_kj_str'))
    elif t == 'AL_Rail':
        m['role'] = 'rail'
        m['speedSlotsPerTick'] = b.get('al_rail_speedInSlotsPerTick')
        m['slotWidths'] = {'rail': b.get('al_rail_slotWidth')}
    elif t == 'AL_EndConsumer':
        m['role'] = 'endConsumer'
        m['speedSlotsPerTick'] = None
        m['slotWidths'] = {}
        m['endConsumerSlotCount'] = b.get('al_endConsumer_slotCount')
    elif t == 'AL_Merger':
        m['role'] = 'merger'
        m['speedSlotsPerTick'] = b.get('al_merger_speedInSlotsPerTick')
        m['slotWidths'] = {k[len('al_merger_slotWidth_'):]: b.get(k) for k in sorted(b) if k.startswith('al_merger_slotWidth_')}
    elif t == 'AL_Splitter':
        m['role'] = 'splitter'
        m['speedSlotsPerTick'] = b.get('al_splitter_speedInSlotsPerTick')
        m['slotWidths'] = {k[len('al_splitter_slotWidth_'):]: b.get(k) for k in sorted(b) if k.startswith('al_splitter_slotWidth_')}
    sp = m.get('speedSlotsPerTick')
    m['derived'] = {'speedMetersPerSec': r4(sp * TICKS_PER_SECOND / SLOTS_PER_METER) if sp else None}
    m['fluidBoxes'] = _fluid_boxes(b)
    return m


def _fluid_boxes(b: dict) -> list[dict]:
    if not b.get('hasFluidBoxManager'):
        return []
    return [{'isInput': bool(fb.get('isInput')), 'capacityLiters': num(fb.get('capacity_liter')),
             'transferRateLitersPerSec': num(fb.get('transferRatePerSecond_liter')),
             'pipeType': text(fb.get('pipeTypeIdentifier')), 'fixedElement': text(fb.get('fixedElementTemplateIdentifier'))}
            for fb in (b.get('fbm_ioFluidBoxes') or [])]


# ---------------------------------------------------------------- documents

def build_all(d: Data, header: dict) -> dict[str, dict]:
    names = _machine_names(d)

    # ---- recipes (base part)
    recipes = {}
    for ident, r in d.recipes.items():
        recipes[ident] = {
            'identifier': ident, 'name': r.get('name'), 'iconIdentifier': text(r.get('icon_identifier')),
            'category': text(r.get('category_identifier')), 'rowGroup': text(r.get('rowGroup_identifier')),
            'sortOrder': r.get('sortingOrderWithinRowGroup', 0),
            'timeMs': int(r['timeMs']), 'tags': list(r.get('tags') or []),
            'inputs': _io_items(r.get('input_data')),
            'outputs': [{'item': e['identifier'], 'amount': int(e['amount']), 'chance': _chance(d, ident, e)}
                        for e in (r.get('output_data') or [])],
            'fluidInputs': _fluids(r.get('inputElemental_data')),
            'fluidOutputs': _fluids(r.get('outputElemental_data')),
            'relatedItem': text(r.get('relatedItemTemplateIdentifier')),
            'hiddenInCharacterCrafting': bool(r.get('isHiddenInCharacterCraftingFrame')),
            'hiddenUntilNarrativeTrigger': bool(r.get('isHiddenByNarrativeTrigger')),
            'narrativeTrigger': text(r.get('narrativeTrigger')),
            'hideInDemo': bool(r.get('hideInDemo')),
            'entitlement': text(r.get('entitlementIdentifier')),
            'derived': {'unlockedBy': {'research': [], 'explorationUnlocks': []}, 'producers': []},
        }

    # ---- machines
    machines = {}
    tag_machines = defaultdict(set)
    for ident, b in d.bots.items():
        nm = names[ident]
        name, item = nm['name'], nm['item']
        craft = _machine_crafting(b)
        size = b.get('size') or {}
        m = {
            'identifier': ident, 'name': name, 'item': item, 'modeName': nm['modeName'],
            'itemAlternatives': nm['itemAlternatives'], 'type': b.get('type'),
            'size': {'x': size.get('x'), 'y': size.get('y'), 'z': size.get('z')},
            'power': {'subType': text(b.get('powerSubType')), 'componentType': text(b.get('powerComponentType')),
                      'consumptionKW': num(b.get('energyConsumptionKW_str')),
                      'hasEnergyGridConnection': bool(b.get('hasEnergyGridConnection')),
                      'hasPoleGridConnection': bool(b.get('hasPoleGridConnection')),
                      'poleGridType': text(b.get('poleGridType'))},
            'crafting': None, 'fluidBoxes': _fluid_boxes(b),
            'itemSlots': dict(sorted(Counter(s.get('flavorType') or s.get('type') or 'Unknown'
                                             for g in (b.get('itemBufferSlotMap') or []) for s in (g.get('slots') or [])).items())),
            'assemblyLine': None,
        }
        if craft:
            if not craft['speedMultiplier']:
                d.warnings.append(f'machine {ident}: recipe time modifier missing/zero')
            accepted = sorted(rid for rid, rr in recipes.items() if _accepts(craft, rr))
            craft = {k: v for k, v in craft.items() if k != 'recipeList'} | {'derived': {'recipes': accepted}}
            m['crafting'] = craft
            for tg in craft['tags']:
                tag_machines[tg].add(ident)
            if craft['recipeSelection'] != 'tags':
                for rid in accepted:
                    for tg in recipes[rid]['tags']:
                        tag_machines[tg].add(ident)
            for rid in accepted:
                rr = recipes[rid]
                if rr['timeMs'] <= 0 or not craft['speedMultiplier'] or not _rateable(rr):
                    d.warnings.append(f'machine {ident} / recipe {rid}: no rate (timeMs {rr["timeMs"]}, '
                                      f'speed {craft["speedMultiplier"]}, or an amount is missing)')
                    continue
                sec = base_station_ticks(rr['timeMs']) / TICKS_PER_SECOND if craft['kind'] == 'BaseStation' else None
                rr['derived']['producers'].append({
                    'machine': ident, 'kind': craft['kind'], 'speedMultiplier': craft['speedMultiplier'],
                    'craftTimeSec': r4(sec if sec is not None else rr['timeMs'] / 1000.0 / craft['speedMultiplier']),
                    'perMinute': _rates(rr, craft['speedMultiplier'], sec)})
        alm = _al_machine(b, name)
        if alm:
            m['assemblyLine'] = {k: v for k, v in alm.items() if k not in ('identifier', 'name', 'type', 'fluidBoxes')}
        machines[ident] = m

    for rr in recipes.values():
        if 'character' in rr['tags'] and not rr['hiddenInCharacterCrafting']:  # CraftingSubFrame hides the others
            if rr['timeMs'] <= 0 or not _rateable(rr):
                d.warnings.append(f'recipe {rr["identifier"]}: no hand-crafting rate (timeMs {rr["timeMs"]} or an amount is missing)')
                continue
            sec = character_ticks(rr['timeMs']) / TICKS_PER_SECOND
            rr['derived']['producers'].append({
                'machine': CHARACTER_MACHINE_ID, 'kind': 'Character', 'speedMultiplier': CHARACTER_SPEED,
                'craftTimeSec': r4(sec), 'perMinute': _rates(rr, CHARACTER_SPEED, sec)})
        rr['derived']['producers'].sort(key=lambda p: (p['kind'] != 'Character', p['machine']))
        if not rr['derived']['producers']:
            d.warnings.append(f'recipe {rr["identifier"]}: no machine accepts tags {rr["tags"]}')
    tag_machines['character'].add(CHARACTER_MACHINE_ID)

    # ---- research
    research = {}
    for ident, r in d.research.items():
        research[ident] = {
            'identifier': ident, 'name': r.get('name'), 'description': text(r.get('description')),
            'iconIdentifier': text(r.get('icon_identifier')), 'flags': flags(r.get('flags')),
            'context': text(r.get('researchContext')),
            'secondsPerScienceItem': num(r.get('secondsPerScienceItem')),
            'cost': _io_items(r.get('input_data')),
            'dependencies': list(r.get('list_researchDependencies_str') or []),
            'requiredCompanyRank': text(r.get('requiredCompanyRankIdentifier')),
            'entitlement': text(r.get('entitlementIdentifier')),
            'endlessManualLevels': r.get('endlessResearch_amountOfManualEndlessResearches')
            if 'ENDLESS_RESEARCH' in flags(r.get('flags')) else None,
            'derived': {'timeSecOneServer': None},
            'unlocks': {
                'recipes': list(r.get('list_craftingUnlocks_str') or []),
                'assemblyLineObjects': list(r.get('list_alots_str') or []),
                'blastFurnaceModes': list(r.get('list_blastFurnaceModes_str') or []),
                'oreScanner': list(r.get('list_oreScannerUnlocks_str') or []),
                'skyPlatformItemVisibility': list(r.get('list_skyPlatformItemVisibility_str') or []),
                'shippingPadItemVisibility': list(r.get('list_shippingPadItemVisibility_str') or []),
                'galacticMarketItemVisibility': list(r.get('list_galacticMarketItemVisibility_str') or []),
            },
        }
        cost, secs = research[ident]['cost'], research[ident]['secondsPerScienceItem']
        if cost and secs:  # all item types are consumed in parallel (ResearchEntity native, findings/verification.md)
            research[ident]['derived']['timeSecOneServer'] = r4(max(e['amount'] for e in cost) * secs)
        for rid in research[ident]['unlocks']['recipes']:
            if rid in recipes:
                recipes[rid]['derived']['unlockedBy']['research'].append(ident)
            else:
                d.warnings.append(f'research {ident}: unknown recipe unlock {rid}')
    exploration = {}
    for ident, e in d.exploration.items():
        fl = flags(e.get('unlockFlags'))
        unl = list(e.get('craftingRecipeUnlocks_identifier') or []) if 'UnlockCraftingRecipe' in fl else []
        exploration[ident] = {
            'identifier': ident, 'title': e.get('title'), 'description': text(e.get('description')),
            'category': text(e.get('categoryIdentifier')), 'iconIdentifier': text(e.get('icon_identifier')),
            'flags': fl, 'secondsToUnlock': num(e.get('secondsToUnlock')),
            'requirements': [{'item': q['itemTemplateIdentifier'], 'amount': int(q['amount'])} for q in (e.get('requirements') or [])],
            'dependencies': [q['explorationUnlockTemplateIdentifier'] for q in (e.get('unlockDepedencies') or [])],
            'researchDependencies': [q['researchTemplateIdentifier'] for q in (e.get('researchDepedencies') or [])],
            'recipeUnlocks': unl,
            'characterCraftingSpeedBonusPercent': num(e.get('characterCraftingSpeed_additionalDecrementPercentage_str'))
            if 'CharacterCraftingSpeed' in fl else None,
        }
        for rid in unl:
            if rid in recipes:
                recipes[rid]['derived']['unlockedBy']['explorationUnlocks'].append(ident)
    for rr in recipes.values():
        for v in rr['derived']['unlockedBy'].values():
            v.sort()

    # ---- assembly line
    research_by_alot = {a: rid for rid, r in research.items() for a in r['unlocks']['assemblyLineObjects']}
    starter_by_alot = {}
    for it in d.items.values():
        if 'AL_STARTER' in flags(it.get('flags')):
            starter_by_alot[it.get('alStarter_alotIdentifier')] = it
    al_machines = {}
    for ident, b in d.bots.items():
        alm = _al_machine(b, names[ident]['name'])
        if alm:
            al_machines[ident] = alm
    producer_speeds = sorted({m['speedSlotsPerTick'] for m in al_machines.values() if m['role'] == 'producer'} - {None})
    start_power = sorted({m.get('powerPerActionKJ') for m in al_machines.values() if m['role'] == 'start'} - {None})
    start_speeds = sorted({m['speedSlotsPerTick'] for m in al_machines.values() if m['role'] == 'start'} - {None})
    if len(producer_speeds) != 1 or len(start_power) != 1 or len(start_speeds) != 1:
        d.warnings.append(f'assembly line: expected exactly one producer speed / start power / start speed, got '
                          f'{producer_speeds} / {start_power} / {start_speeds} - derived throughput uses the first')
    objects = {}
    used_alpas = set()
    for ident, a in d.alots.items():
        st = starter_by_alot.get(ident)
        parts = []
        for p in a.get('objectParts') or []:
            parts.append({'identifier': p['identifier'], 'title': p.get('title'), 'isInitialPart': bool(p.get('isInitialPart')),
                          'paintingPowerKJ': num(p.get('requiredPowerForPainting_kj_str')),
                          'colorVariants': [{'identifier': c['identifier'], 'title': c.get('title'),
                                             'paintElement': text(c.get('paintElementTemplate_identifier')),
                                             'paintLiters': num(c.get('amountLiquidRequired_l_str'))}
                                            for c in (p.get('colorVariants') or [])]})
        stages = []
        tot_items, tot_fluids, power, nact = Counter(), Counter(), 0, 0
        if st:
            tot_items[st['identifier']] += 1
        for s in d.stages.get(ident, []):
            acts = []

            def walk(lst, parent):
                nonlocal power, nact
                for x in (lst or {}).get('$items', []):
                    pa_id = x.get('identifier_machineAction')
                    pa = d.alpas.get(pa_id)
                    if pa is None:
                        d.warnings.append(f'ALOT {ident}: unknown producer action {pa_id}')
                        continue
                    used_alpas.add(pa_id)
                    act = {'identifier': x.get('identifier'),
                           'type': {1: 'AttachComponent', 2: 'MachineInteraction'}.get(x.get('assemblyStageActionType'), str(x.get('assemblyStageActionType'))),
                           'description': text(x.get('description')), 'parentAction': parent,
                           'producerAction': {'identifier': pa_id, 'name': pa.get('name'), 'iconIdentifier': text(pa.get('icon_identifier')),
                                              'powerKJ': num(pa.get('powerCost_kj_str')),
                                              'items': _io_items(pa.get('requiredItems')),
                                              'fluids': [{'element': e['identifier'], 'liters': num(e['amount']) / 10000 if num(e['amount']) else 0}
                                                         for e in (pa.get('requiredElements') or [])],
                                              'attachesPart': text(pa.get('partIdentifierToAttach'))}}
                    acts.append(act)
                    nact += 1
                    power += act['producerAction']['powerKJ'] or 0
                    for e in act['producerAction']['items']:
                        tot_items[e['item']] += e['amount']
                    for e in act['producerAction']['fluids']:
                        tot_fluids[e['element']] += e['liters']
                    walk(x.get('subActions'), act['identifier'])
            walk(s.get('stageSubActions'), None)
            stages.append({'identifier': s.get('identifier'), 'title': s.get('title'), 'description': text(s.get('description')), 'actions': acts})
        paint = defaultdict(float)  # per paint element: Σ over parts of the largest amount of a variant using it
        for p in parts:
            per_el = defaultdict(float)
            for c in p['colorVariants']:
                if c['paintElement'] and c['paintLiters']:
                    per_el[c['paintElement']] = max(per_el[c['paintElement']], c['paintLiters'])
            for el, liters in per_el.items():
                paint[el] += liters
        speed = producer_speeds[0] if producer_speeds else None
        start_speed = start_speeds[0] if start_speeds else None
        painter_power = sum(p['paintingPowerKJ'] or 0 for p in parts)  # recalculatePainterCosts: every part, Metal too
        objects[ident] = {
            'identifier': ident, 'name': a.get('name'), 'description': text(a.get('description')),
            'iconIdentifier': text(a.get('icon_identifier')),
            'starterItem': st['identifier'] if st else None,
            'sellItem': text(st.get('alStarter_sellItemTemplateIdentifier')) if st else None,
            'researchedBy': research_by_alot.get(ident),
            'parts': parts, 'stages': stages,
            'derived': {
                'inputs': [{'item': k, 'amount': v} for k, v in sorted(tot_items.items())],
                'fluidInputs': [{'element': k, 'liters': r4(v)} for k, v in sorted(tot_fluids.items())],
                'producerActionCount': nact, 'producerPowerKJ': power,
                'startPowerKJ': start_power[0] if start_power else None,
                'painterPowerKJ': painter_power,
                'totalPowerKJ': power + (start_power[0] if start_power else 0) + painter_power,
                'fullPaint': [{'element': k, 'liters': r4(v), 'powerKJ': painter_power} for k, v in sorted(paint.items())],
                'maxObjectsPerMinute': r4(speed * TICKS_PER_SECOND * 60 / RAIL_ITEM_LENGTH) if speed else None,
                # AL_Start spawns when the last object's gap reaches RAIL_ITEM_LENGTH: one per ceil(1125/speed) ticks
                'singleStartObjectsPerMinute': r4(TICKS_PER_SECOND * 60 / -(-RAIL_ITEM_LENGTH // start_speed)) if start_speed else None,
            },
        }
        if not st:
            d.warnings.append(f'ALOT {ident}: no AL_STARTER item references it')
    for pa_id in sorted(set(d.alpas) - used_alpas):
        d.warnings.append(f'producer action {pa_id} not used by any ALOT stage')

    # ---- items
    produced_by, used_by = defaultdict(set), defaultdict(set)
    for rr in recipes.values():
        for e in rr['outputs']:
            produced_by[e['item']].add(rr['identifier'])
        for e in rr['inputs']:
            used_by[e['item']].add(rr['identifier'])
    al_used, al_produced = defaultdict(set), defaultdict(set)
    for o in objects.values():
        for e in o['derived']['inputs']:
            al_used[e['item']].add(o['identifier'])
        if o['sellItem']:
            al_produced[o['sellItem']].add(o['identifier'])
    items = {}
    for ident, it in d.items.items():
        fl = flags(it.get('flags'))
        fuel = None
        if 'BURNABLE' in fl and num(it.get('burnable_fuelValueKJ_str')):  # TooltipFrame / CubeInventory: only BURNABLE
            fuel = {'fuelValueKJ': num(it.get('burnable_fuelValueKJ_str')),
                    'residualItem': text(it.get('burnable_residualItemTemplate_str')),
                    'residualCount': it.get('burnable_residualItemTemplate_count') or None}
        market = None
        if it.get('market_buyPrice') or it.get('market_sellPrice') or it.get('canBeTradedOnStation'):
            market = {'buyPrice': it.get('market_buyPrice'), 'sellPrice': it.get('market_sellPrice'),
                      'tradeableOnStation': bool(it.get('canBeTradedOnStation'))}
        sales = None
        if 'SALES_ITEM' in fl or 'SALES_ITEM_ASSEMBLY_LINE' in fl:
            sales = {'category': text(it.get('salesItem_salesItemCategoryIdentifier')),
                     'industry': text(it.get('salesItem_industryIdentifier')),
                     'currencyAmount': it.get('salesItem_currencyAmount'),
                     'baseDemandPerDay': it.get('salesItem_salesPlatformBaseDemandPerDay'),
                     'skyPlatformBaseCapacity': it.get('salesItem_skyPlatformBaseCapacity'),
                     'hiddenByResearch': text(it.get('salesItem_hiddenByResearchIdentifier'))}
        bo_ref = text(it.get('buildableObjectIdentifer')) if 'BUILDABLE_OBJECT' in fl else None  # ItemTemplateManager
        if bo_ref and bo_ref not in d.bots:
            d.warnings.append(f'item {ident}: buildableObject {bo_ref} does not exist')
        items[ident] = {
            'identifier': ident, 'name': it.get('name'), 'iconIdentifier': text(it.get('icon_identifier')),
            'description': text(it.get('tooltipInfoMessage')), 'stackSize': it.get('stackSize'), 'flags': fl,
            'category': text(it.get('itemCategoryIdentifier')), 'creativeModeCategory': text(it.get('creativeModeCategory_str')),
            'buildableObject': bo_ref, 'hidden': bool(it.get('isHiddenItem')),
            'entitlement': text(it.get('entitlementIdentifier')), 'weightGrams': it.get('_baseWeightInGrams'),
            'fuel': fuel, 'market': market, 'sales': sales,
            'assemblyLineStarter': {'object': it.get('alStarter_alotIdentifier'), 'sellItem': it.get('alStarter_sellItemTemplateIdentifier')}
            if 'AL_STARTER' in fl else None,
            'autoProducerRecipes': [{'craftingTag': e.get('craftingTagIdentifier'), 'recipe': e.get('recipeIdentifier')}
                                    for e in (it.get('autoProducerRecipes') or [])],
            'derived': {'producedBy': sorted(produced_by[ident]), 'usedBy': sorted(used_by[ident]),
                        'usedByAssemblyLine': sorted(al_used[ident]), 'producedByAssemblyLine': sorted(al_produced[ident])},
        }

    # ---- referential checks
    for rr in recipes.values():
        for e in rr['inputs'] + rr['outputs']:
            if e['item'] not in items:
                d.warnings.append(f'recipe {rr["identifier"]}: unknown item {e["item"]}')
        for e in rr['fluidInputs'] + rr['fluidOutputs']:
            if e['element'] not in d.elements:
                d.warnings.append(f'recipe {rr["identifier"]}: unknown element {e["element"]}')
    for o in objects.values():
        for e in o['derived']['inputs']:
            if e['item'] not in items:
                d.warnings.append(f'ALOT {o["identifier"]}: unknown item {e["item"]}')

    elements = {}
    for ident, e in d.elements.items():
        fuel = None
        if num(e.get('fuel_fuelValueKJPerL_str')):
            fuel = {'fuelValueKJPerLiter': num(e.get('fuel_fuelValueKJPerL_str')),
                    'residualElement': text(e.get('fuel_residualTemplate_identifier')),
                    'residualLitersPerLiter': num(e.get('fuel_residualAmountPerL_str')),
                    'minViableLiters': num(e.get('fuel_minViableVolumeL_str')),
                    'flags': flags(e.get('fuel_flags'))}
        elements[ident] = {'identifier': ident, 'name': e.get('name'), 'iconIdentifier': text(e.get('icon_identifier')),
                           'flags': flags(e.get('flags')), 'pipeContentType': e.get('pipeContentType'), 'fuel': fuel}

    tag_recipes = Counter(t for rr in recipes.values() for t in rr['tags'])
    tags = {}
    for ident, t in d.tags.items():
        tags[ident] = {'identifier': ident, 'name': t.get('name'), 'slotLockDescription': text(t.get('slotLockDescription')),
                       'derived': {'machines': sorted(tag_machines.get(ident, ())), 'recipeCount': tag_recipes.get(ident, 0)}}
    for t in sorted(set(tag_recipes) - set(tags)):
        d.warnings.append(f'recipes use undefined crafting tag {t}')

    def doc(name, key, values, **extra):
        return {'schema': f'foundry-data/{name}@1', **header, **extra, 'count': len(values), key: values}

    docs = {
        'items.json': doc('items', 'items', _sorted(items)),
        'elements.json': doc('elements', 'elements', _sorted(elements)),
        'crafting_tags.json': doc('crafting_tags', 'tags', _sorted(tags)),
        'recipes.json': doc('recipes', 'recipes', _sorted(recipes)),
        'machines.json': doc('machines', 'machines', _sorted(machines)),
        'research.json': {'schema': 'foundry-data/research@1', **header, 'count': len(research),
                          'research': _sorted(research), 'explorationUnlocks': _sorted(exploration)},
        'assembly_line.json': {'schema': 'foundry-data/assembly_line@1', **header,
                               'constants': {'ticksPerSecond': TICKS_PER_SECOND, 'slotsPerMeter': SLOTS_PER_METER,
                                             'railItemLengthSlots': RAIL_ITEM_LENGTH},
                               'count': len(objects), 'machines': _sorted(al_machines), 'objects': _sorted(objects)},
    }
    return docs


# ---------------------------------------------------------------- localization

def build_localization(d: Data, catalogs: dict[str, dict[str, str]], header: dict) -> dict[str, dict]:
    names = _machine_names(d)
    out = {}
    for lang, cat in catalogs.items():
        s = defaultdict(dict)

        def put(section, ident, field, k):
            if k in cat:
                s[section].setdefault(ident, {})[field] = cat[k]

        for i in d.items:
            put('items', i, 'name', lkey('ItemTemplate', i, 'name'))
            put('items', i, 'description', lkey('ItemTemplate', i, 'tooltipInfoMessage'))
        for i in d.recipes:
            put('recipes', i, 'name', lkey('CraftingRecipe', i, 'name'))
        for i, b in d.bots.items():
            nm = names[i]
            if nm['nameOverride']:
                put('machines', i, 'name', lkey('BuildableObjectTemplate', i, 'nameOverride'))
            elif nm['item']:
                put('machines', i, 'name', lkey('ItemTemplate', nm['item'], 'name'))
            if nm['modeName'] is not None:
                put('machines', i, 'modeName', lkey('ItemTemplate', nm['item'], 'name', [('toggleableModes', nm['modeIndex'])]))
        for i in d.elements:
            put('elements', i, 'name', lkey('ElementTemplate', i, 'name'))
        for i in d.tags:
            put('craftingTags', i, 'name', lkey('CraftingTag', i, 'name'))
            put('craftingTags', i, 'slotLockDescription', lkey('CraftingTag', i, 'slotLockDescription'))
        for i in d.research:
            put('research', i, 'name', lkey('ResearchTemplate', i, 'name'))
            put('research', i, 'description', lkey('ResearchTemplate', i, 'description'))
        for i in d.exploration:
            put('explorationUnlocks', i, 'title', lkey('ExplorationUnlockTemplate', i, 'title'))
            put('explorationUnlocks', i, 'description', lkey('ExplorationUnlockTemplate', i, 'description'))
        for i, a in d.alots.items():
            put('assemblyLineObjects', i, 'name', lkey('AssemblyLineObjectTemplate', i, 'name'))
            put('assemblyLineObjects', i, 'description', lkey('AssemblyLineObjectTemplate', i, 'description'))
            parts = {}
            for pi, p in enumerate(a.get('objectParts') or []):
                entry = {}
                k = lkey('AssemblyLineObjectTemplate', i, 'title', [('objectParts', pi)])
                if k in cat:
                    entry['title'] = cat[k]
                cvs = {}
                for ci, c in enumerate(p.get('colorVariants') or []):
                    k = lkey('AssemblyLineObjectTemplate', i, 'title', [('objectParts', pi), ('colorVariants', ci)])
                    if k in cat:
                        cvs[c['identifier']] = cat[k]
                if cvs:
                    entry['colorVariants'] = cvs
                if entry:
                    parts[p['identifier']] = entry
            if parts:
                s['assemblyLineObjects'].setdefault(i, {})['parts'] = parts
        for i in d.alpas:
            put('assemblyLineActions', i, 'name', lkey('AssemblyLineProducerActionTemplate', i, 'name'))
        strings = {sec: dict(sorted(v.items())) for sec, v in sorted(s.items())}
        out[lang] = {'schema': 'foundry-data/localization@1', **header, 'language': lang,
                     'count': sum(len(f) for v in strings.values() for f in v.values()), 'strings': strings}
    return out
