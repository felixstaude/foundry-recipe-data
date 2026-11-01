# Export-Schema `foundry-data` v1

Maschinenlesbare JSON-Schemas (Draft 2020-12): `extractor/foundry_export/schemas/*.schema.json`.
Der Extractor prüft jede Ausgabe beim Export gegen diese Schemas. Diese Datei ist die verbindliche Beschreibung.

## Quellen (alle aus dem Spielordner, Spielversion 0.6.0.26518 geprüft)

| Daten | Quelle | Beleg |
|---|---|---|
| Templates (Items, Rezepte, Maschinen, Forschung, Tags, Elemente, Assembly Line) | `foundry_Data/StreamingAssets/Templates/<Typ>/<identifier>.yaml` | Mitgelieferter Dump des Entwickler-Werkzeugs `Main/TemplateExporter.cs` `runExportAll` (Editor-Knopf "Export All Templates To YAML"; nur Templates mit `shouldIncludeInBuild() && shouldIncludeInGame()`, ohne TrainTrack-/Spline-Typen; Felder: public, nicht `[NonSerialized]`, nicht `[HideInInspector]`, `TweakManager.createYamlFromTemplate`). **Das Spiel liest den Dump nicht** (es lädt `foundry_main_bundle`). Er kann also in einem Patch veralten. Darum vergleicht jeder Export die 9 exportierten Typen mit dem Bundle (Warnung `source-mismatch:`) und nimmt bei Abweichung das Bundle (`sources.open_template_source`, `--source auto`). Für 0.6.0.26518: alle 67 Typen, 2750 Templates identisch (bis auf fehlende GUIDs in Referenzen und `null` ↔ `""` bei 14 Feldern, die nicht exportiert werden) |
| Templates aus dem Bundle | `foundry_main_bundle`, MonoBehaviours mit `m_Script` → MonoScript-Klasse ⊂ `C3.FoundryTemplate`, nur Objekte aus `m_Container`, `includeInBuild && includeIngame` | `foundry_export/bundle_templates.py`. Wird benutzt, wenn der Dump fehlt oder für einen exportierten Typ keine Dateien hat (Warnung `source: … (fallback)`), wenn Dump und Bundle abweichen (`source-mismatch:`, außer der Bundle-Leser meldet `bundle:`-Probleme) oder mit `--source bundle`. Liefert für 0.6.0.26518 byte-gleiche Daten. Feldnamen/Enum-Namen aus `Managed/*.dll` (ECMA-335-Metadaten), ohne DLLs aus `foundry_export/data/managed_types.json`. `manifest.templateSource` nennt die benutzte Quelle |
| Assembly-Line-Stages (Odin-binär, kein FoundryTemplate, fehlen im YAML-Dump) | `foundry_Data/StreamingAssets/AssetBundles/foundry_main_bundle`, Objekt laut `m_Container`-Pfad aus `AssemblyLineObjectTemplate.assemblyLineStages` | `Main/AssemblyLineStages.cs`; geladen in `Main/GlobalStateManager.cs` Z. 733 |
| Lokalisierung | `foundry_Data/StreamingAssets/locale/<lang>/LC_MESSAGES/foundry_templates-<lang>.mo` | `Main/PoMgr.cs` Z. 43, Schlüssel aus `PoMgr.generateId` |
| Code-Hashes (keine Daten) | `foundry_Data/Managed/{Main,Channel3,Assembly-CSharp}.dll`, `foundry_Data/Plugins/x86_64/FoundryNative.dll` | `manifest.codeHashes`, Warnung `code-changed:`. Die nativen Konstanten (Handwerk ÷3, ms → Ticks, Assembly Line) prüft `extractor/tools/check_native_constants.py` über die mitgelieferte `FoundryNative.pdb`; C#-Konstanten `extractor/tools/check_code_constants.py` |
| Spielversion | `<Spielordner>/version.txt` (`Application.version` + Revision); Steam-Build und Beta-Branch (`BetaKey`) aus `appmanifest_983870.acf` der Steam-Bibliothek, die das Spiel enthält (`foundry_export/steam.py` durchsucht alle Bibliotheken aus `libraryfolders.vdf`); Unity-Version aus dem Bundle-Header (gleich `globalgamemanagers`) | – |

## Ausgabe-Layout

```
<Ausgabe>/
  index.json                      # alle exportierten Versionen
  latest.json                     # zeigt auf die neueste Version
  v<gameVersion>/                 # z. B. v0.6.0.26518
    manifest.json
    CHANGES.md                    # Änderungen gegenüber der vorherigen exportierten Version (foundry_export/diff.py, deutsch)
    items.json
    elements.json
    crafting_tags.json
    recipes.json
    machines.json
    research.json
    assembly_line.json
    template_fields.json          # Feldpfade aller Template-Typen dieser Version (siehe unten)
    localization/<lang>.json      # af, cs, de, en, es-419, ... (alle Ordner unter locale/)
    schemas/*.schema.json         # Kopie der JSON-Schemas, mit denen geprüft wurde
```

## Allgemeine Regeln

- Jede Datei hat einen Kopf: `{"schema": "foundry-data/<datei>@1", "gameVersion": "0.6.0.26518", ...}`.
  Listen sind nach `identifier` sortiert. Gleiche Eingabe ergibt gleiche Ausgabe; einzige Ausnahme ist `generatedAt`
  (in `manifest.json`, `index.json`, `latest.json` und `CHANGES.md`). Die Datendateien selbst enthalten keinen Zeitstempel.
  JSON wird ohne `NaN`/`Infinity` geschrieben (nicht endliche Zahlen in Templates sind ein Fehler).
- **Identifier** sind die Spiel-Identifier unverändert (`_base_robot01_head`, Tags ohne Präfix wie `assembler`).
  Verweise zwischen Dateien laufen immer über diese Identifier.
- **Zahlen:** *Numerische* Felder mit `_str` sind Festkomma-Strings (`ExtensionMethods.toFPM`, Faktor 10000, höchstens
  4 Nachkommastellen). Sie werden als JSON-Zahl im natürlichen Wert ausgegeben (`"1.5"` → `1.5`). Einige `_str`-Felder sind
  Identifier oder Identifier-Listen (z. B. `burnable_residualItemTemplate_str`, `list_*_str` der Forschung). Die bleiben Text.
  Leerer String → `null`. Das ist eine Konvention des Exports, das Spiel rechnet `""` als 0.
- **Einheiten** stehen im Feldnamen: `Ms`, `Sec`, `KJ`, `KW`, `Liters`, `PerMin`, `Slots`.
- **Texte:** In den Datendateien steht der englische Originaltext (Template-Feld). Übersetzungen kommen aus `localization/<lang>.json`.
- **Abgeleitete Werte** (vom Exporter berechnet, nicht im Asset) liegen immer unter einem Schlüssel `derived`
  bzw. sind in diesem Dokument als abgeleitet markiert, mit Formel und Quelle.
- Enum-/Flag-Werte stehen als Namen wie im YAML (`"Producer"`, `["SALES_ITEM", "WORKSTATION_ITEM"]`).

## manifest.json (schemaVersion 1.1)

| Feld | Typ | Bedeutung |
|---|---|---|
| `schemaVersion` | string | `"1.1"` |
| `gameVersion` | string | aus `version.txt` |
| `steamBuildId` | string \| null | aus dem Steam-Appmanifest |
| `steamBranch` | string \| null | Beta-Branch (`BetaKey`), `null` = öffentlicher Branch |
| `unityVersion` | string | aus dem Bundle-Header |
| `generatedAt` | string (ISO 8601) | Zeitpunkt des Exports |
| `generator` | string | `foundry-export <Version>` |
| `templateSource` | string | `StreamingAssets/Templates` (Dump) oder `foundry_main_bundle` (Rückfall, Dump ≠ Bundle oder `--source bundle`) |
| `previousVersion` | string \| null | Vorversion in `index.json`, gegen die Anzahlen, DLL-Hashes und `CHANGES.md` verglichen wurden |
| `templateCounts` | object | Template-Typ → Anzahl, für **alle** Typen (auch nicht exportierte; ohne den Pseudo-Typ `AssemblyLineStages`) |
| `codeHashes` | object | sha256 von `Main.dll`, `Channel3.dll`, `Assembly-CSharp.dll` und `Plugins/x86_64/FoundryNative.dll` (Code-Änderung erkennen, ohne zu dekompilieren; Warnung `code-changed:` auch, wenn eine Datei fehlt oder neu ist) |
| `schemaHashes` | object | Dateiname in `schemas/` → sha256 (`export verify` prüft auch diese) |
| `files` | object | Dateiname → `{count, sha256}` aller Daten-, Lokalisierungs- und `template_fields.json`-Dateien (`CHANGES.md` und `schemas/` nicht enthalten) |
| `languages` | string[] | exportierte Sprachen |
| `warnings` | string[] | alles Auffällige, sortiert. Präfixe siehe `extractor/README.md` ("Warnungen im Manifest"): `new-template-type`, `removed-template-type`, `unknown-field`, `removed-field`, `new-enum-value`, `removed-enum-value`, `count-change`, `sanity`, `dll-types`, `code-changed`, `source-mismatch`, `source`, `bundle`, `baseline`, ohne Präfix = Konsistenz. `--strict` bricht dann mit Exit-Code 1 ab |

`index.json`: `{"latest": "v…", "versions": [{"version", "gameVersion", "steamBuildId", "generatedAt"}]}`.
`latest.json`: `{"version", "gameVersion", "steamBuildId", "generatedAt"}`.
Ordnername `v<gameVersion>`. Gibt es ihn schon mit anderem Steam-Build: `v<gameVersion>-b<steamBuildId>`. Ein vorhandener Ordner wird
nur ersetzt, wenn er der neueste Export ist und denselben Build hat; sonst verweigert der Export (Exit-Code 7, `--overwrite`).
Exit-Codes und Optionen: `extractor/README.md`.

## template_fields.json

```
{"schema": "foundry-data/template_fields@1", "gameVersion": "...", "steamBuildId": "...",
 "templateSource": "StreamingAssets/Templates", "count": 68,
 "types": {"<Typ>": {"count": <Templates>, "fields": ["<Feldpfad>", ...]}}}
```

Alle Feldpfade aller Template-Typen (ohne Werte; `a.b` für verschachtelte Objekte, `a[].b` für Objekte in Listen), dazu der
Pseudo-Typ `AssemblyLineStages` (dekodierte Odin-Stufen, `{"stages": [...]}` je ALOT). `types` hat dieselbe Form wie
in `extractor/foundry_export/baseline/known_templates.json` (dort zusätzlich `enumValues`), aber pro Version. Zweck: Auch nachdem die Baseline nach einem Update
neu gesetzt wurde, bleibt festgehalten, welche Felder es in welcher Version gab. CHANGES.md vergleicht die Datei zweier Versionen
(Abschnitt "Template-Felder"). `count` = Anzahl Typen. In 0.6.0.26518: 67 Template-Typen + `AssemblyLineStages`.

## CHANGES.md

Vom Export automatisch gegen `previousVersion` erzeugt (`export diff` macht es von Hand). Einträge werden über `identifier`
verglichen (Assembly-Line-Stufen/-Aktionen über `<Objekt> / <Stufe|Aktion>`, z. B. `_base_droid01 / _weld_head`; bei Aktionen
steht der Identifier der Producer-Aktion, z. B. `_d01_weldHead`, daneben). Geänderte Werte stehen als `alt → neu`.
Zusammengefasst (nicht pro Eintrag) werden nur `items.derived`, `recipes.derived.producers` und `machines.crafting.derived`;
andere `derived.*`-Felder (z. B. `derived.totalPowerKJ` der Roboter) erscheinen pro Eintrag. Felder, die nur eine Seite hat,
weil der Extractor erweitert wurde, stehen einmal unter "Neue Felder im Export". Weitere Abschnitte: "Hinweis zur Template-Quelle"
(oben, bei Rückfall oder Dump ≠ Bundle), neue Template-Typen, "Template-Felder" (neue/entfernte Feldpfade je Typ aus
`template_fields.json`), "Lokalisierung" (Zählung pro Sprache; neue Einträge ohne deutschen/englischen Namen), Warnungen
(neu/entfallen). Warnungen zählen nicht als Datenänderung: Sind die Daten gleich, steht dort **"Ergebnis: keine Datenänderungen"** (mit Zusatz, ob sich Warnungen geändert haben).
Enthält `generatedAt` und ist daher nicht byte-reproduzierbar.

## items.json → `items[]`

| Feld | Quelle (`ItemTemplate`) |
|---|---|
| `identifier`, `name`, `iconIdentifier` | `identifier`, `name`, `icon_identifier` |
| `description` | `tooltipInfoMessage` (oder `null`) |
| `stackSize` | `stackSize` |
| `flags` | `flags` (Namen aus `ItemTemplate.ItemTemplateFlags`) |
| `category`, `creativeModeCategory` | `itemCategoryIdentifier`, `creativeModeCategory_str` |
| `buildableObject` | `buildableObjectIdentifer` → `machines.json`, **nur bei Flag `BUILDABLE_OBJECT`** (sonst ignoriert das Spiel das Feld, `ItemTemplateManager.cs` Z. 653–662) |
| `hidden` | `isHiddenItem` |
| `entitlement` | `entitlementIdentifier` (z. B. `_deluxe_edition`) |
| `weightGrams` | `_baseWeightInGrams` |
| `fuel` | `{fuelValueKJ, residualItem, residualCount}` aus `burnable_*`, **nur bei Flag `BURNABLE`** (`TooltipFrame.cs` Z. 378, Slot-Sperre `CubeInventory.cs` Z. 24–33), sonst `null`. `_base_jetpack_fuel` ist BURNABLE, wird wegen `JET_PACK_FUEL` aber nicht in Brennstoff-Slots angenommen |
| `market` | `{buyPrice, sellPrice, tradeableOnStation}` bzw. `null` |
| `sales` | nur bei Flag `SALES_ITEM` / `SALES_ITEM_ASSEMBLY_LINE`: `{category, industry, currencyAmount, baseDemandPerDay, skyPlatformBaseCapacity, hiddenByResearch}` |
| `assemblyLineStarter` | nur bei Flag `AL_STARTER`: `{object, sellItem}` (→ `assembly_line.json`) |
| `autoProducerRecipes` | `[{craftingTag, recipe}]`: Rezept, das ein AutoProducer mit diesem Tag für das Item automatisch wählt |
| `derived.producedBy` | Rezepte mit diesem Item als Ausgabe |
| `derived.usedBy` | Rezepte mit diesem Item als Eingabe |
| `derived.usedByAssemblyLine` | Assembly-Line-Objekte, die das Item verbrauchen (Starter oder Aktion) |
| `derived.producedByAssemblyLine` | Assembly-Line-Objekte, die das Item als Verkaufs-Item erzeugen |

## elements.json → `elements[]` (Flüssigkeiten/Gase, `ElementTemplate`)

`identifier`, `name`, `iconIdentifier`, `flags`, `pipeContentType` (Zahl unverändert; nur Darstellung: Shader-Kategorie
des Rohrinhalts, `PipeGO.cs` Z. 76). **Kein Gas/Flüssig-Kennzeichen:** meist 1 bei Gasen, aber `_base_npp_steam_exhaust`
("Exhaust Steam") hat 2.
`fuel`: `{fuelValueKJPerLiter, residualElement, residualLitersPerLiter, minViableLiters, flags}` bzw. `null`.

## crafting_tags.json → `tags[]`

`identifier`, `name`, `slotLockDescription`, `derived.machines` (Maschinen, deren Rezeptauswahl diesen Tag nutzt, plus
Maschinen mit festem Rezept bzw. Rezeptliste, deren Rezept den Tag trägt, z. B. `_base_geothermal_generator_i` für
`geothermal_generator`), `derived.recipeCount`.

## recipes.json → `recipes[]`

| Feld | Quelle (`CraftingRecipe`) |
|---|---|
| `identifier`, `name`, `iconIdentifier` | |
| `category`, `rowGroup`, `sortOrder` | `category_identifier`, `rowGroup_identifier`, `sortingOrderWithinRowGroup` |
| `timeMs` | `timeMs` (Basiszeit) |
| `tags` | `tags` |
| `inputs` | `[{item, amount}]` aus `input_data` |
| `outputs` | `[{item, amount, chance}]` aus `output_data` (`chance` = `percentage_str`, 1 = 100 %; fehlt der Wert: 1 und Warnung `recipe X: output Y has no percentage_str - chance taken as 1`) |
| `fluidInputs` / `fluidOutputs` | `[{element, liters}]` aus `inputElemental_data` / `outputElemental_data` |
| `relatedItem` | `relatedItemTemplateIdentifier` |
| `hiddenInCharacterCrafting`, `hiddenUntilNarrativeTrigger`, `narrativeTrigger`, `hideInDemo`, `entitlement` | |
| `derived.unlockedBy` | `{research: [...], explorationUnlocks: [...]}` (Forschung `list_craftingUnlocks_str`; Erkundung `craftingRecipeUnlocks_identifier`, nur wenn Flag `UnlockCraftingRecipe` gesetzt ist, `ExplorationUnlockTemplate.onLoad`) |
| `derived.producers` | siehe unten |

### `derived.producers[]`: echte Geschwindigkeiten aus den Maschinen-Assets

Welche Maschine ein Rezept annimmt, ermittelt der Exporter für Producer, AutoProducer und ModularEntityProducer wie
`CraftingRecipe.onLoadPostprocess` (`CraftingRecipe.cs` Z. 310–388, `list_allowedProducers`; unabhängig nachgerechnet: gleiche
Mengen für alle 350 Rezepte). BaseStation und Character sind Ergänzungen des Exporters (BaseStation: Rezeptliste,
`BuildableObjectTemplate.cs` Z. 3002–3011 / `NativeWrapper.cs` Z. 1031; Character: Tag `character`, `TooltipFrame.cs` Z. 1204,
`RecipeSlot.cs` Z. 287). Rezepte mit `isHiddenInCharacterCraftingFrame` bekommen keinen Character-Eintrag (`CraftingSubFrame.cs` Z. 93
blendet sie aus). Nicht über CraftingRecipe laufende Produktion (Hochofen-Modi, Ressourcenwandler, Recycler, Pumpjacks, Miner,
Kessel, Kernkraft) ist **nicht** in `derived.producers` enthalten.

| `kind` | Bedingung | `speedMultiplier` |
|---|---|---|
| `Producer` | BOT `type: Producer` und (`producerRecipeType: Tags` und Schnittmenge `producer_recipeType_tags` ∩ `tags` nicht leer, **oder** `Fixed` und `producer_recipeType_fixed` = Rezept) | `producer_recipeTimeModifier_str` |
| `AutoProducer` | BOT `type: AutoProducer` und `autoProducer_recipeType_tag` ∈ `tags` | `autoProducer_recipeTimeModifier_str` |
| `ModularEntityProducer` | BOT `type: ModularEntityProducer` und (fixes Rezept `modularProducer_fixedCraftingRecipeIdentifier`, sonst `modularProducer_recipeType_tags` ∩ `tags`) | `modularProducer_recipeTimeModifier_str` |
| `BaseStation` | Rezept steht in `baseStation_craftingRecipeIdentifier` der BaseStation | 1. Nativ `BaseStationFurnace::tickUpdate`: ganze Ticks `trunc(trunc(timeMs·10⁸/166666)/10⁴)`, ohne Strom-/Workstation-Einfluss |
| `Character` (Pseudo-Maschine `character`) | Tag `character`, nicht `isHiddenInCharacterCraftingFrame` | **3** (Simulation). Nativ `FoundryNative.dll` `CraftingAction::reinitialize`: Ticks = `max(1, trunc(round(trunc(round(timeMs·10⁸/30000)/1000)·600000/10⁴)/10⁴))`, also `timeMs/3` auf ganze 60-Hz-Ticks abgeschnitten. `craftTimeSec` = Ticks/60 (z. B. 5000 ms → 99 Ticks → 1,65 s). **Der Tooltip im Spiel zeigt `timeMs/5`** (`Character.getCraftingTimeForRecipeInMs`, nur UI). Zwei unabhängige Disassembly-Lesungen, Messung im Spiel steht aus (`findings/open_questions.md`). Erkundungsbonus nicht eingerechnet (additiv, je Stufe 10 %, max. 90 %: Ticks × (1 − Σ%/100)) |

Pro Eintrag: `machine`, `kind`, `speedMultiplier`, `craftTimeSec` = `timeMs / 1000 / speedMultiplier` (Character und BaseStation:
ganze Ticks / 60, siehe Tabelle), `perMinute` = `{inputs: [{item, perMin}], outputs: [{item, perMin}], fluidInputs: [{element, litersPerMin}], fluidOutputs: [...]}`
mit `perMin = amount × chance × 60 / craftTimeSec` (`CraftingRecipe.getItemsPerMinute`, `ProducerGO.getProducerCraftTimeInMsFPM`).
Werte auf 4 Nachkommastellen gerundet (das Spiel zeigt 2). Kein Eintrag, sondern eine Warnung (`machine X / recipe Y: no rate …`
bzw. `recipe X: no hand-crafting rate …`), wenn `timeMs` ≤ 0 ist, der Multiplikator fehlt oder 0 ist oder eine Menge fehlt.
Base-Station-Zeiten sind mindestens 1 Tick.

Nativ bestätigt (`ProducerEntity`/`AutoProducerEntity`/`ModularProducerEntity::tryStartProduction` und `::tickUpdate`): Dauer
`timeMs / speedMultiplier / (1 + speedBonus)` in Ticks (Umrechnung mit 166666 statt 166666,67, Abweichung ≈ 4 ppm, nicht eingerechnet).
Fortschritt pro Tick = Strom-Zufriedenheit, Rest wird übertragen. Die Raten pro Minute sind bei vollem Strom also exakt.
**Keine Rundung auf ganze Ticks bei Maschinen:** Die Dauer steht in 1/10⁴ Tick (`ProducerEntity::tryStartProduction`, Division
durch 166666), beim Abschluss wird sie vom Fortschritt abgezogen statt ihn zu löschen (`tryFinishProduction` bei Producer,
AutoProducer und ModularProducer), der nächste Durchlauf startet im selben Tick (`tickUpdate`).
Einzelne Durchläufe enden auf ganzen Ticks, der Mittelwert ist die gebrochene Dauer. Handwerk und Base Station dagegen zählen ganze
Ticks herunter. Beim Handwerk kann die Kürzung einen Tick kosten: 8000 ms ergeben 159 statt 160 Ticks (2,65 s statt 2,6667 s),
weil das Spiel die Sekunden vor dem ×60 auf 4 Nachkommastellen abschneidet (`CraftingAction::reinitialize`).
Nur der `*_recipeTimeModifier_str` des eigenen BOT-Typs wird an die Simulation gegeben (`_base_smelter_i` ist AutoProducer → 1,5,
sein `producer_recipeTimeModifier_str` 2 wird ignoriert). Heavy Caster: ×32 ohne Modul-Term.

Nicht enthalten: Laufzeit-Boni durch Workstation-Roboter (`speedBonus`: Σ `workstationItem_data01` der SPEED_BOOST-Roboter × Skala,
Skala = 1 + Σ Power-Core-Slots `effectScaleIncreasePerPowerCore × xenoPowerCore_multiplier`; Mehrverbrauch Σ `data02` × Skala;
**zwei überlappende Workstations legen die Maschine still**), Effizienz-Boni (EFFICIENCY_BOOST, R&D-Lab) und Strommangel
(wirkt linear: Dauer / Zufriedenheit, kein Schwellwert).

## machines.json → `machines[]` (alle `BuildableObjectTemplate`)

| Feld | Quelle |
|---|---|
| `identifier`, `type` | `identifier`, `type` (`BuildableObjectTemplate.BuildableObjectType`) |
| `name` | `nameOverride` (wenn `hasNameOverride`), sonst `name` des Items (`item`) |
| `item` | Item, das die Maschine baut, wie im Spiel aufgelöst: Items mit Flag `BUILDABLE_OBJECT` und `buildableObjectIdentifer` = identifier (`ItemTemplateManager.cs` Z. 653–662), sonst das Item, das die Maschine als Modus in `toggleableModes` führt (`toggleableModeType: MultipleBuildings`, `ItemTemplate.onLoadPostprocess` Z. 650–668; z. B. Rail-Kurven, Decor-Teile, Modul-Bauteile). Bei mehreren Kandidaten nimmt das Spiel den letzten in Ladereihenfolge (aus den Assets nicht bestimmbar). Der Export bevorzugt das Item mit gleichem Identifier, dann das, das die Maschine als Modus führt, dann das erste nach Identifier |
| `modeName` | Name des Modus in `toggleableModes` des Items (z. B. "Curve Left (HVG Connector)"), sonst `null` |
| `itemAlternatives` | weitere Items, die dieselbe Maschine bauen (mehrdeutige Fälle, meist Pflanzen/Bäume mit Saat-Item) |
| `size` | `{x, y, z}` |
| `power` | `{subType, componentType, consumptionKW, hasEnergyGridConnection, hasPoleGridConnection, poleGridType}` (`powerSubType`, `powerComponentType`, `energyConsumptionKW_str`, `hasPoleGridConnection`, `poleGridType`). `componentType: PCM` allein heißt nicht Verbraucher: Assembly-Line-Splitter/-Merger, Kurven- und HVG-Schienen sind `subType: GENERIC` mit `poleGridType: PowerPole` (Stromweiterleitung). Verbraucher haben `poleGridType: GenericPowerConsumer` |
| `crafting` | `null` oder `{kind, speedMultiplier, recipeSelection: "tags"\|"fixed"\|"list", tags, fixedRecipe, derived: {recipes}}` |
| `fluidBoxes` | `[{isInput, capacityLiters, transferRateLitersPerSec, pipeType, fixedElement}]` aus `fbm_ioFluidBoxes` (nur bei `hasFluidBoxManager`). Bei modularen Gebäuden (Heavy Caster, Reactor Fuel Mixer) liegen die Boxen auf den Modul-BOTs (z. B. `_base_casting_building_input`), nicht auf der Basis |
| `itemSlots` | Zähler aus `itemBufferSlotMap`: `{<flavorType>: n}` |
| `assemblyLine` | bei `AL_*`-Typen dieselben Werte wie in `assembly_line.json → machines` |

## research.json

`research[]` (`ResearchTemplate`): `identifier`, `name`, `description`, `iconIdentifier`, `flags`, `context` (`researchContext`),
`secondsPerScienceItem`, `cost` `[{item, amount}]` (`input_data`, Grundkosten), `dependencies` (`list_researchDependencies_str`),
`requiredCompanyRank`, `entitlement`, `endlessManualLevels` (nur bei Flag `ENDLESS_RESEARCH`:
`endlessResearch_amountOfManualEndlessResearches`; Kosten der Stufe n laut `ResearchSystem.getRequiredSciencePackInputCount`,
`ResearchSystem.cs` Z. 383–394: `amount + max(0, n − endlessManualLevels) × max(1, amount / 2)`), `unlocks`: `{recipes, assemblyLineObjects, blastFurnaceModes, oreScanner,
skyPlatformItemVisibility, shippingPadItemVisibility, galacticMarketItemVisibility}`,
`derived.timeSecOneServer` = größte Menge in `cost` × `secondsPerScienceItem` (ein Forschungsserver, voller Strom, ohne Workstation).
Nativ (`ResearchEntity`/`ResearchManager`): alle Wissenschafts-Items werden parallel verbraucht, Server addieren sich linear
(Dauer / Anzahl Server), Strommangel und Workstation-Speed-Bonus skalieren linear. Mehr als eine Workstation am Server stoppt ihn.

`explorationUnlocks[]` (`ExplorationUnlockTemplate`): `identifier`, `title`, `description`, `category`, `iconIdentifier`,
`flags` (`unlockFlags`), `secondsToUnlock`, `requirements` `[{item, amount}]`, `dependencies` (andere Erkundungs-Freischaltungen,
`unlockDepedencies`), `researchDependencies` (Forschungen, `researchDepedencies`, `ExplorationUnlockTemplate.onLoadPostprocess` Z. 237–245),
`recipeUnlocks` (nur wirksam mit Flag `UnlockCraftingRecipe`), `characterCraftingSpeedBonusPercent`.

## assembly_line.json

```
{
  "constants": {"ticksPerSecond": 60, "slotsPerMeter": 600, "railItemLengthSlots": 1125},
  "machines": [ {identifier, name, type, role, speedSlotsPerTick, derived: {speedMetersPerSec},
                 slotWidths: {...}, powerPerActionKJ, endConsumerSlotCount, machineType, fluidBoxes} ],
  "objects":  [ {
     identifier, name, description, iconIdentifier,
     starterItem, sellItem, researchedBy,
     parts: [ {identifier, title, isInitialPart, paintingPowerKJ,
               colorVariants: [{identifier, title, paintElement, paintLiters}]} ],
     stages: [ {identifier, title, description,
                actions: [ {identifier, type: "AttachComponent"|"MachineInteraction", description,
                            parentAction, producerAction: {identifier, name, iconIdentifier, powerKJ,
                            items: [{item, amount}], fluids: [{element, liters}], attachesPart}} ]} ],
     derived: { inputs: [{item, amount}],          # Starter + alle Aktions-Items
                fluidInputs: [{element, liters}],
                producerActionCount, producerPowerKJ, startPowerKJ,
                painterPowerKJ,                          # Σ requiredPowerForPainting aller Teile (Lackieren ist Pflicht)
                totalPowerKJ,                            # producer + start + painter
                fullPaint: [{element, liters, powerKJ}], # je Farbstoff: alle Teile in einer Farbe ≠ Metall (größte Literzahl
                                                         # je Teil); powerKJ = painterPowerKJ
                maxObjectsPerMinute,                     # Schienenlimit, siehe unten
                singleStartObjectsPerMinute }            # Ausstoß eines einzelnen AL-Starts
  } ]
}
```

- `actions` sind der Aktionsbaum in **Tiefensuche-Reihenfolge** (wie im Asset). `parentAction` verweist auf die
  übergeordnete Aktion (Schweißen → zugehöriges Montieren) bzw. ist `null`.
- `role`: `start` (AL_Start), `rail`, `producer` / `painter` (AL_Producer, `al_producer_machineType`), `endConsumer`, `merger`, `splitter`.
- `maxObjectsPerMinute` (abgeleitet) = `speedSlotsPerTick × 60 × 60 / 1125` mit der Producer-Geschwindigkeit
  (`AssemblyLineProducerActionTemplate.getItemsPerMinute`; das Spiel rechnet hier ganzzahlig, bei Tempo 10 exakt 32).
  Das ist die Obergrenze der Schiene.
- `singleStartObjectsPerMinute` (abgeleitet) = `60 × 60 / ceil(1125 / al_start_speedInSlotsPerTick)` = 31,86: Ein AL-Start setzt
  ein neues Objekt erst, wenn der Abstand zum letzten 1125 Slots erreicht (nativ `AL_StartEntity`). 32/min nur mit mehreren
  zusammengeführten Starts.
- Aktionen brauchen **keine eigene Zeit** (nativ: Wirkung beim Übergang Eingang → Ausgang des Producers, Animation folgt der Position).
  Energie begrenzt nicht: Der Puffer fasst 2 Aktionen und lädt pro Tick mit bis zu `2 × floor(K / 112)`, K = Kosten in Festkomma
  (kJ × 10000), 112 = `floor(1125 / Tempo)`. Details: `findings/assembly_line.md`.
- `painterPowerKJ`: Der Painter ist Pflicht (Endverbraucher nimmt nur lackierte, fertige Objekte) und berechnet alle Teile, auch Metall.

## localization/<lang>.json

```
{ "schema": "foundry-data/localization@1", "gameVersion": "...", "language": "de",
  "strings": {
    "items":        { "<id>": {"name": "...", "description": "..."} },
    "recipes":      { "<id>": {"name": "..."} },
    "machines":     { "<id>": {"name": "...", "modeName": "..."} },
    "elements":     { "<id>": {"name": "..."} },
    "craftingTags": { "<id>": {"name": "...", "slotLockDescription": "..."} },
    "research":     { "<id>": {"name": "...", "description": "..."} },
    "explorationUnlocks": { "<id>": {"title": "...", "description": "..."} },
    "assemblyLineObjects": { "<id>": {"name": "...", "description": "...",
                              "parts": {"<partId>": {"title": "...", "colorVariants": {"<cvId>": "..."}}}} },
    "assemblyLineActions": { "<producerActionId>": {"name": "..."} }
  } }
```

Schlüssel im `.mo` (`PoMgr.generateId`): `TYPNAME` + `IDENTIFIER` (beides groß) + Pfad + `_FELD`.
Bei Array-Elementen wird `_<FELD>_<i>` an den Pfad und `_<i>` an das Feld gehängt, z. B.
`ASSEMBLYLINEOBJECTTEMPLATE_BASE_DROID01_OBJECTPARTS_0_COLORVARIANTS_1_TITLE_1`.
Fehlt ein Schlüssel, fällt das Spiel auf den englischen Originaltext zurück. Der Export lässt den Eintrag dann weg.
Maschinennamen kommen über das Item (bzw. `NAMEOVERRIDE`), Modus-Namen über
`ITEMTEMPLATE<ITEM>_TOGGLEABLEMODES_<i>_NAME_<i>`. Stage-Titel/-Beschreibungen sind **nicht** lokalisiert:
`AssemblyLineStages` ist ein eigenes Unity-Objekt und wird von `PoMgr.setFieldsRecursively` übersprungen; im `.mo` gibt es keine Stage-Schlüssel.

## Bewusst nicht exportiert (Stand 0.6.0.26518)

Die Feld-Baseline (`extractor/foundry_export/baseline/known_templates.json`) enthält **alle** Felder aller 67 Template-Typen,
die Feldpfade der dekodierten `AssemblyLineStages` und die bekannten Werte der Enum-/Flag-Felder, nach denen `build.py` verzweigt
(`enumValues`, `checks.ENUM_FIELDS`). Was dort steht und hier nicht exportiert wird, ist gesehen, aber (noch) nicht übernommen.
Neue Felder in späteren Versionen meldet der Export als `unknown-field:`, neue Enum-Werte als `new-enum-value:`. Wird ein Typ oder
Feld nach Prüfung bewusst ignoriert, kommt er in diese Liste (mit Version und Grund). Die Baseline wird bei jeder neuen Version
nach der Prüfung neu gesetzt (`export baseline`, UPDATE.md Schritt d); welche Felder neu waren, steht danach weiter in
`template_fields.json` und CHANGES.md ("Template-Felder").

**Für Wiki/Calculator relevant, noch nicht exportiert** (Hinweise der unabhängigen Prüfung, `findings/verification.md`):
- *ItemTemplate:* `recyclingData` (Recycler-Ausbeute mit Chancen), `workstationItem_effect`/`_data01`/`_data02`/`requiredTags`/`excludedTags`
  (Workstation-Roboter: SPEED_BOOST/EFFICIENCY_BOOST), `xenoPowerCore_multiplier_str`, `warehouse_stackSize`, `itemCategorySortOrder`,
  `miningTimeReductionInSec`/`miningRange`, `salesItem_rdLabEfficiencyCrIdentifiers`, `explorationUnlockInput_flavorText`.
- *BuildableObjectTemplate:* `conveyor_speed_slotsPerTick`, `pumpjack_amountPerSec_str`, `boiler_*`, `burnerGenerator_*`, `lvgGenerator_*`,
  `solarPanel_output*`, `battery_capacityKJ_str`, `nppSteamTurbine_*`, `nppReactor_*`, `resourceConverter_*` (z. B. Luftansaugung),
  `droneMiner_*`, `endlessMiner_*`, `oreVeinMiner_ticksPerOre_str`, `blastFurnace_*`, `frackingTower_*`, `workstation_*`, `loader_ticksPerAction`,
  `freightContainer_speedPerTick`, `demolitionTimeSec`, `modularBuildingLimits`.
- *BlastFurnaceModeTemplate* (Hochofen-Modi, einzige Quelle für flüssiges XF/TE), *PipeTypeTemplate* (`throughputPerMinute_l_str`).
- *ResearchTemplate:* `manualEndlessResearchTemplate_str`, `inventorySize_additionalInventorySlots`, `miningHardness_unlockedLevel`,
  `jetpackSpeed_speedIncreasmentPercent_str`.
- *ExplorationUnlockTemplate:* `sortOrderASC`, `miningDrillSpeed_*`, `personalMiningDrones_*`, `personalLogistics*`, `buildingDrone_additionalRange`.
- Namen der Kategorie-Templates (CraftingRecipeCategory, CraftingRecipeRowGroup, ItemCategory, CreativeModeCategory, SalesItemCategory, Industry).
- `items.derived.usedBy` zählt nur Rezepte, nicht Forschungskosten oder Erkundungs-Anforderungen.

**Ohne Bedeutung für Wiki/Calculator** (nicht exportiert): Biome-, Terrain-, Noise-, Planeten-, Sektor-, Galaxie-, Höhlen-, Kritter-, Skin-, UI-,
Voice-Line-, Tipp-, Achievement-, Info-Datenbank-, Quest-, Zug-Gleis-, Session-Settings- und Test-Templates.
