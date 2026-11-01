"""JSON Schemas (Draft 2020-12) for foundry-data v1. Source of truth for schemas/*.schema.json
(regenerate with: python3 -m foundry_export schemas). Human-readable spec: findings/schema.md."""
from __future__ import annotations

S, I, N, B = {'type': 'string'}, {'type': 'integer'}, {'type': 'number'}, {'type': 'boolean'}
NS, NI, NN = {'type': ['string', 'null']}, {'type': ['integer', 'null']}, {'type': ['number', 'null']}
SL = {'type': 'array', 'items': S}


def obj(props: dict, required: list | None = None, nullable=False) -> dict:
    o = {'type': ['object', 'null'] if nullable else 'object', 'properties': props,
         'required': list(props) if required is None else required, 'additionalProperties': False}
    return o


def arr(items) -> dict:
    return {'type': 'array', 'items': items}


REF = lambda n: {'$ref': f'#/$defs/{n}'}  # noqa: E731

COMMON_DEFS = {
    'itemAmount': obj({'item': S, 'amount': I}),
    'fluidAmount': obj({'element': S, 'liters': N}),
    'vec3': obj({'x': NI, 'y': NI, 'z': NI}),
}


def header(name: str) -> dict:
    return {'schema': {'const': f'foundry-data/{name}@1'}, 'gameVersion': S, 'steamBuildId': NS, 'count': I}


def doc(name: str, list_key: str, item_schema: dict, extra_props: dict | None = None, defs: dict | None = None) -> dict:
    props = header(name) | (extra_props or {}) | {list_key: arr(item_schema)}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': f'foundry-data/{name}@1',
            **obj(props), '$defs': COMMON_DEFS | (defs or {})}


ITEM = obj({
    'identifier': S, 'name': NS, 'iconIdentifier': NS, 'description': NS, 'stackSize': NI, 'flags': SL,
    'category': NS, 'creativeModeCategory': NS, 'buildableObject': NS, 'hidden': B, 'entitlement': NS, 'weightGrams': NN,
    'fuel': obj({'fuelValueKJ': N, 'residualItem': NS, 'residualCount': NI}, nullable=True),
    'market': obj({'buyPrice': NN, 'sellPrice': NN, 'tradeableOnStation': B}, nullable=True),
    'sales': obj({'category': NS, 'industry': NS, 'currencyAmount': NN, 'baseDemandPerDay': NN,
                  'skyPlatformBaseCapacity': NN, 'hiddenByResearch': NS}, nullable=True),
    'assemblyLineStarter': obj({'object': S, 'sellItem': S}, nullable=True),
    'autoProducerRecipes': arr(obj({'craftingTag': S, 'recipe': S})),
    'derived': obj({'producedBy': SL, 'usedBy': SL, 'usedByAssemblyLine': SL, 'producedByAssemblyLine': SL}),
})

ITEM_CATEGORY = obj({'identifier': S, 'name': NS, 'iconIdentifier': NS, 'sortOrder': NI})
CREATIVE_MODE_CATEGORY = obj({'identifier': S, 'name': NS, 'sortOrder': NI})

ELEMENT = obj({'identifier': S, 'name': NS, 'iconIdentifier': NS, 'flags': SL, 'pipeContentType': NI,
               'fuel': obj({'fuelValueKJPerLiter': N, 'residualElement': NS, 'residualLitersPerLiter': NN,
                            'minViableLiters': NN, 'flags': SL}, nullable=True)})

TAG = obj({'identifier': S, 'name': NS, 'slotLockDescription': NS,
           'derived': obj({'machines': SL, 'recipeCount': I})})

PRODUCER_KINDS = ['Producer', 'AutoProducer', 'ModularEntityProducer', 'BaseStation', 'Character']
RATES = obj({
    'inputs': arr(obj({'item': S, 'perMin': N})), 'outputs': arr(obj({'item': S, 'perMin': N})),
    'fluidInputs': arr(obj({'element': S, 'litersPerMin': N})), 'fluidOutputs': arr(obj({'element': S, 'litersPerMin': N})),
})
RECIPE = obj({
    'identifier': S, 'name': NS, 'iconIdentifier': NS, 'category': NS, 'rowGroup': NS, 'sortOrder': I,
    'timeMs': {'type': 'integer', 'minimum': 1}, 'tags': SL,
    'inputs': arr(REF('itemAmount')), 'outputs': arr(obj({'item': S, 'amount': I, 'chance': N})),
    'fluidInputs': arr(REF('fluidAmount')), 'fluidOutputs': arr(REF('fluidAmount')),
    'relatedItem': NS, 'hiddenInCharacterCrafting': B, 'hiddenUntilNarrativeTrigger': B, 'narrativeTrigger': NS,
    'hideInDemo': B, 'entitlement': NS,
    'derived': obj({
        'unlockedBy': obj({'research': SL, 'explorationUnlocks': SL}),
        'producers': arr(obj({'machine': S, 'kind': {'enum': PRODUCER_KINDS}, 'speedMultiplier': N,
                              'craftTimeSec': N, 'perMinute': RATES})),
    }),
})

FLUID_BOX = obj({'isInput': B, 'capacityLiters': NN, 'transferRateLitersPerSec': NN, 'pipeType': NS, 'fixedElement': NS})
AL_MACHINE_CORE = {
    'role': {'enum': ['start', 'rail', 'producer', 'painter', 'endConsumer', 'merger', 'splitter']},
    'speedSlotsPerTick': NI, 'slotWidths': {'type': 'object', 'additionalProperties': NI},
    'machineType': NS, 'powerPerActionKJ': NN, 'endConsumerSlotCount': NI,
    'derived': obj({'speedMetersPerSec': NN}),
}
AL_MACHINE_REQ = ['role', 'speedSlotsPerTick', 'slotWidths', 'derived']
MACHINE = obj({
    'identifier': S, 'name': NS, 'item': NS, 'modeName': NS, 'itemAlternatives': SL, 'type': NS, 'size': REF('vec3'),
    'power': obj({'subType': NS, 'componentType': NS, 'consumptionKW': NN, 'hasEnergyGridConnection': B,
                  'hasPoleGridConnection': B, 'poleGridType': NS}),
    'crafting': obj({'kind': {'enum': PRODUCER_KINDS[:4]}, 'speedMultiplier': NN,
                     'recipeSelection': {'enum': ['tags', 'fixed', 'list']}, 'tags': SL, 'fixedRecipe': NS,
                     'derived': obj({'recipes': SL})}, nullable=True),
    'fluidBoxes': arr(FLUID_BOX),
    'itemSlots': {'type': 'object', 'additionalProperties': I},
    'assemblyLine': obj(AL_MACHINE_CORE, AL_MACHINE_REQ, nullable=True),
})

RESEARCH = obj({
    'identifier': S, 'name': NS, 'description': NS, 'iconIdentifier': NS, 'flags': SL, 'context': NS,
    'secondsPerScienceItem': NN, 'cost': arr(REF('itemAmount')), 'dependencies': SL,
    'requiredCompanyRank': NS, 'entitlement': NS, 'endlessManualLevels': NI, 'derived': obj({'timeSecOneServer': NN}),
    'unlocks': obj({k: SL for k in ['recipes', 'assemblyLineObjects', 'blastFurnaceModes', 'oreScanner',
                                     'skyPlatformItemVisibility', 'shippingPadItemVisibility', 'galacticMarketItemVisibility']}),
})
EXPLORATION = obj({
    'identifier': S, 'title': NS, 'description': NS, 'category': NS, 'iconIdentifier': NS, 'flags': SL,
    'secondsToUnlock': NN, 'requirements': arr(REF('itemAmount')), 'dependencies': SL, 'researchDependencies': SL,
    'recipeUnlocks': SL,
    'characterCraftingSpeedBonusPercent': NN,
})

AL_ACTION = obj({
    'identifier': S, 'type': {'enum': ['AttachComponent', 'MachineInteraction']}, 'description': NS, 'parentAction': NS,
    'producerAction': obj({'identifier': S, 'name': NS, 'iconIdentifier': NS, 'powerKJ': NN,
                           'items': arr(REF('itemAmount')), 'fluids': arr(REF('fluidAmount')), 'attachesPart': NS}),
})
AL_OBJECT = obj({
    'identifier': S, 'name': NS, 'description': NS, 'iconIdentifier': NS,
    'starterItem': NS, 'sellItem': NS, 'researchedBy': NS,
    'parts': arr(obj({'identifier': S, 'title': NS, 'isInitialPart': B, 'paintingPowerKJ': NN,
                      'colorVariants': arr(obj({'identifier': S, 'title': NS, 'paintElement': NS, 'paintLiters': NN}))})),
    'stages': arr(obj({'identifier': S, 'title': NS, 'description': NS, 'actions': arr(AL_ACTION)})),
    'derived': obj({'inputs': arr(REF('itemAmount')), 'fluidInputs': arr(REF('fluidAmount')),
                    'producerActionCount': I, 'producerPowerKJ': N, 'startPowerKJ': NN, 'painterPowerKJ': N, 'totalPowerKJ': N,
                    'fullPaint': arr(obj({'element': S, 'liters': N, 'powerKJ': N})),
                    'maxObjectsPerMinute': NN, 'singleStartObjectsPerMinute': NN}),
})
AL_MACHINE = obj({'identifier': S, 'name': NS, 'type': S, **AL_MACHINE_CORE, 'fluidBoxes': arr(FLUID_BOX)},
                 ['identifier', 'name', 'type', 'fluidBoxes'] + AL_MACHINE_REQ)

MANIFEST_SCHEMA_VERSION = '1.2'   # 1.1: steamBranch, templateSource, previousVersion, templateCounts, codeHashes, schemaHashes
                                  # 1.2: items.json categories/creativeModeCategories, localization itemCategories/creativeModeCategories

LOC_SECTION = {'type': 'object', 'additionalProperties': {'type': 'object'}}

SCHEMAS = {
    'items': doc('items', 'items', ITEM, {'categories': arr(ITEM_CATEGORY), 'creativeModeCategories': arr(CREATIVE_MODE_CATEGORY)}),
    'elements': doc('elements', 'elements', ELEMENT),
    'crafting_tags': doc('crafting_tags', 'tags', TAG),
    'recipes': doc('recipes', 'recipes', RECIPE),
    'machines': doc('machines', 'machines', MACHINE),
    'research': doc('research', 'research', RESEARCH, {'explorationUnlocks': arr(EXPLORATION)}),
    'assembly_line': doc('assembly_line', 'objects', AL_OBJECT, {
        'constants': obj({'ticksPerSecond': I, 'slotsPerMeter': I, 'railItemLengthSlots': I}),
        'machines': arr(AL_MACHINE)}),
    'localization': {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'foundry-data/localization@1',
                     **obj(header('localization') | {'language': S, 'strings': {'type': 'object', 'additionalProperties': LOC_SECTION}})},
    'template_fields': {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'foundry-data/template_fields@1',
                        **obj(header('template_fields') | {'templateSource': S, 'types': {
                            'type': 'object', 'additionalProperties': obj({'count': I, 'fields': SL})}})},
    'manifest': {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'foundry-data/manifest@1',
                 **obj({'schemaVersion': {'const': MANIFEST_SCHEMA_VERSION}, 'gameVersion': S, 'steamBuildId': NS, 'steamBranch': NS,
                        'title': NS, 'description': NS, 'unityVersion': S, 'generatedAt': S, 'generator': S,
                        'templateSource': {'enum': ['StreamingAssets/Templates', 'foundry_main_bundle']},
                        'previousVersion': NS, 'languages': SL, 'warnings': SL,
                        'templateCounts': {'type': 'object', 'additionalProperties': I},
                        'codeHashes': {'type': 'object', 'additionalProperties': S},
                        'schemaHashes': {'type': 'object', 'additionalProperties': S},
                        'files': {'type': 'object', 'additionalProperties': obj({'count': I, 'sha256': S})}})},
}

FILE_SCHEMA = {'items.json': 'items', 'elements.json': 'elements', 'crafting_tags.json': 'crafting_tags',
               'recipes.json': 'recipes', 'machines.json': 'machines', 'research.json': 'research',
               'assembly_line.json': 'assembly_line', 'template_fields.json': 'template_fields',
               'manifest.json': 'manifest'}
