# Assembly Line – Datenmodell und Produktion

Spielversion: **0.6.0.26518** (`<Spielordner>/version.txt`), Steam-App 983870, Build-ID 23077581,
Unity 2022.3.51f1 (`foundry_Data/globalgamemanagers`).

Pfade: Klassen unter `decompiled/Main/` (Assembly `Main`, **nicht** `Assembly-CSharp`), Assets unter
`raw/ExportedProject/Assets/foundrytemplates/`. In `decompiled/Channel3` und `decompiled/ThirdParty`
gibt es keine Assembly-Line-Klassen (grep nach `assemblyline|alot` ohne Treffer).

## Kurzfassung

Die Assembly Line ist **kein CraftingRecipe**. Ein Produkt entsteht so:

1. Ein **Starter-Item** (der Torso, Flag `AL_STARTER`) kommt in den `AL_Start`. Es verweist auf ein
   `AssemblyLineObjectTemplate` (ALOT, "Bauplan") und auf das **Verkaufs-Item** (fertiger Roboter).
2. Der ALOT verweist auf ein `AssemblyLineStages`-Asset. Darin steht ein **Baum von Aktionen**
   (Stage → Aktion → Unteraktion).
3. Jede Aktion verweist auf ein `AssemblyLineProducerActionTemplate` (ALPA). Dort stehen
   **Zutaten (Items/Fluide), Energie pro Aktion und welches Teil montiert wird**.
4. Jeder `AL_Producer` wird auf **genau eine ALPA** eingestellt. Das Objekt fährt auf Schienen
   von Producer zu Producer, bis alle Aktionen erledigt sind. Danach muss es durch einen `AL_Painter`
   (**Pflicht**, siehe "Reihenfolge und Stationen"). Am `AL_EndConsumer` wird es als Verkaufs-Item gelagert.

Ein "Rezept" ist also: Starter-Item + Summe aller ALPA-Zutaten + Farbe (Liter je nach Farbwahl, Metall = 0 L; der
Painter-Durchlauf selbst ist Pflicht) + Energie (Producer + Start + Painter) → Verkaufs-Item. Alles davon steht in Assets. Es gibt **kein Zeitfeld**. Die Aktionen selbst
brauchen keine Zeit. Der Durchsatz ergibt sich aus der Schiene (siehe "Durchsatz").

> Nativ belegte Aussagen (Painter-Pflicht, Reihenfolge, Energiepuffer, Durchsatz) stammen aus `FoundryNative.dll` mit den
> mitgelieferten Symbolen (`FoundryNative.pdb`). Zwei unabhängige Disassembly-Lesungen stimmen überein, Details in
> `findings/verification.md`. Bestätigung im Spiel: `findings/open_questions.md`.
> Funktionen laut PDB (0.6.0.26518): `AL_ProducerEntity::tickUpdate`, `AL_StartEntity::tickUpdate`,
> `AL_ProducerEntity::recalculatePainterCosts`, `AL_EndConsumerEntity::alcm_validateItemForConsumption`,
> `AL_Item::processPainting`, `AL_Item::_isReadyForActionIterativeCheck` (Größen: `findings/verification.md`).

## Klassen

| Klasse | Datei | Rolle |
|---|---|---|
| `AssemblyLineObjectTemplate : FoundryTemplate` | `Main/AssemblyLineObjectTemplate.cs` | Bauplan: `identifier`, `name`, `icon_identifier`, `objectParts[]`, `assemblyLineStages` (Referenz), Collider. Hash-Präfix `alot_` |
| `AssemblyLineObjectTemplate.AssemblyLineObjectPart` | dto. | Teil: `identifier` (`_torso`, `_arms`, `_legs`, `_arm_left`, `_leg_left`, `_head`), `title`, `isInitialPart`, `requiredPowerForPainting_kj_str`, `colorVariants[]` |
| `AssemblyLineObjectTemplate.ComponentColorVariant` | dto. | Farbe: `paintElementTemplate_identifier` (`_base_paint`), `amountLiquidRequired_l_str` (Liter) |
| `AssemblyLineObjectTemplate.AssemblyStage` / `.AssemblyStageAction` | dto. | Stage (`identifier`, `title`, `description`, `stageSubActions[]`). Aktion: `assemblyStageActionType` (1 = `AttachComponent`, 2 = `MachineInteraction`), `identifier`, `identifier_machineAction` (→ ALPA), `subActions[]` (verschachtelt) |
| `AssemblyLineStages : SerializedScriptableObject` | `Main/AssemblyLineStages.cs` | Enthält nur `AssemblyStage[] stages`, **Odin-serialisiert** (`[OdinSerialize]`) |
| `AssemblyLineProducerActionTemplate : FoundryTemplate` | `Main/AssemblyLineProducerActionTemplate.cs` | Aktion an einer Maschine: `name`, `powerCost_kj_str`, `requiredItems[] {identifier, amount}`, `requiredElements[] {identifier, amount}` (max. 8 je Liste), `partIdentifierToAttach`, Animationsfelder. Hash-Präfix `alpa_` |
| `ItemTemplate` (Felder `alStarter_alotIdentifier`, `alStarter_sellItemTemplateIdentifier`) | `Main/ItemTemplate.cs` (Felder bei Z. 358 ff., Verknüpfung in `onLoadPostprocess` Z. 732–744) | Verknüpft Starter-Item ↔ ALOT ↔ Verkaufs-Item. Setzt `alot.parentItemTemplate` |
| `ResearchTemplate.list_alots_str` | `Main/ResearchTemplate.cs` Z. 72, 302–311 | Forschung schaltet ALOTs frei (`crosslinkWithResearchTemplate`) |
| `BuildableObjectTemplate` (`al_start_*`, `al_rail_*`, `al_producer_*`, `al_endConsumer_*`, `al_merger_*`, `al_splitter_*`, `alStart_requiredPowerPerAction_kj_str`) | `Main/BuildableObjectTemplate.cs` Z. 1479–1600 | Maschinenwerte der Blöcke |
| `AssemblyLineSystem` | `Main/AssemblyLineSystem.cs` | Konstanten `SLOTS_PER_METER = 600`, `RAIL_ITEM_LENGTH = 1125`, Fehlercodes |
| `NativeWrapper` | `Main/NativeWrapper.cs` Z. 1686–1765 | Schickt ALOT, Stages, Aktionen und ALPA an `FoundryNative` (`templateManager_registerAssemblyLineObjectTemplate`, `..._addAssemblyLineObjectAssemblyStageAction(_nested)`, `..._registerAssemblyLineProducerActionTemplate`, `..._addAssemblyLineProducerActionItemRequirement`, …) |
| `AL_StartGO`, `AL_ProducerGO`, `AL_RailGO`, `AL_MergerGO`, `AL_SplitterGO`, `AL_EndConsumerGO` | `Main/AL_*GO.cs` | Nur Darstellung und Abfragen. Die Simulation läuft **nativ** (`DllImport("FoundryNative")`) |
| `AL_ProducerSetActionEvent` / `AL_ProducerSetPaintingActionEvent` / `AL_StartSetAlotEvent` | `Main/…Event.cs` | Konfiguration: Producer bekommt **eine** `actionId` (`alProducerEntity_setAction`). Painter bekommt ALOT + Farbe je Teil. Start bekommt ALOT |
| `SPP_AL_Producer`, `SPP_AL_Start` | `Main/SPP_AL_Producer.cs`, `Main/SPP_AL_Start.cs` | UI-Panels. Zeigen, wie Energie und Items/Minute berechnet werden (siehe unten) |

### Ladekette (Beleg)
- `ItemTemplateManager` lädt alle ALOT und ALPA (`ItemTemplateManager.cs` Z. 529–537) und ruft danach
  `AssemblyLineObjectTemplate.onLoadPostprocess()` auf (Z. 849).
- `onLoadPostprocess` geht den Aktionsbaum durch. Für jede Aktion holt es die ALPA über
  `identifier_machineAction`, setzt `alpa.parentAlot`, löst `partIdentifierToAttach` → `partIdxToAttach` auf
  und meldet einen Fehler, wenn eine ALPA mehrfach benutzt wird. **Jede ALPA gehört also zu genau einer Aktion
  eines Roboters.**

## Asset-Format

- `assemblylineobjecttemplates/<Name>.asset`: normales Unity-YAML (ALOT). Das Feld
  `assemblyLineStages: {guid: …}` verweist per GUID auf `<Name> Stages.asset` (die GUID steht in dessen `.meta`).
- `assemblylineobjecttemplates/<Name> Stages.asset`: `serializationData.SerializedBytes` ist ein Hex-String
  im **Odin-Binärformat** (`SerializedFormat: 0`), kein lesbares YAML. Zum Lesen gibt es den Decoder
  `extractor/foundry_export/odin_binary.py` (`decode(bytes)`). Er wurde an allen 9 Stages-Assets getestet, und die unabhängige
  Prüfung bestätigt ihn mit einem eigenen Decoder (9/9 identisch, `findings/verification.md`).
- `assemblylineproduceractions/<roboter>/<Prefix>_<Aktion>.asset`: normales YAML (ALPA). 90 Dateien = 9 Roboter × 10 Aktionen.
- Starter-Items: `items/assemblylines/*_Torso IT.asset`. Teile (Arm, Leg, Head) liegen im selben Ordner.
  Die Teile sind **normale CraftingRecipes**, z. B. `craftingrecipes/drones & robots/Robot01_Head CR.asset`
  (`_base_robot_parts_i` + `_base_cpu` + `_base_glass` → Kopf, 15 s, Tag `assembler`).

## Wie ein Roboter gebaut wird (Daten aus den Assets)

Alle 9 Roboter haben **dieselbe Struktur**. Nur Item-IDs und ALPA-Präfixe unterscheiden sich:

```
Stage "_attach_peripherals" ("Peripherals")
  [1 Attach] _attach_arm_left   → <P>_attachArmLeft   200 kJ, 1× <arm>,  Teil _arm_left
     └[2 Machine] _weld_arm_left  → <P>_weldArmLeft    500 kJ
  [1 Attach] _attach_leg_left   → <P>_attachLegLeft   200 kJ, 1× <leg>,  Teil _leg_left
     └[2 Machine] _weld_leg_left  → <P>_weldLegLeft    500 kJ
  [1 Attach] _attach_arm_right  → <P>_attachArmRight  200 kJ, 1× <arm>,  Teil _arms
     └[2 Machine] _weld_arm_right → <P>_weldArmRight   500 kJ
  [1 Attach] _attach_leg_right  → <P>_attachLegRight  200 kJ, 1× <leg>,  Teil _legs
     └[2 Machine] _weld_leg_right → <P>_weldLegRight   500 kJ
  [1 Attach] _attach_head       → <P>_attachHead      200 kJ, 1× <head>, Teil _head
     └[2 Machine] _weld_head      → <P>_weldHead       500 kJ
```

Pro Roboter: **1 Torso (Starter) + 2 Arme + 2 Beine + 1 Kopf**, 10 Producer-Aktionen,
**3500 kJ** Producer-Energie, dazu **50 kJ** am `AL_Start` (`alStart_requiredPowerPerAction_kj_str: 50`).
Keine Roboter-Aktion braucht Fluide (`requiredElements: []` überall). Das Datenmodell erlaubt Fluide
(`requiredElements`, nativ `templateManager_addAssemblyLineProducerActionElementRequirement`). Der einzige Producer
(`_base_al_producer_i`) hat aber keine Fluid-Box (`hasFluidBoxManager: False`). Nur der Painter hat eine.

| ALOT | Name | Forschung | Starter (Torso) | Verkaufs-Item | Teile (Arm / Leg / Head) | ALPA-Präfix |
|---|---|---|---|---|---|---|
| `_base_droid01` | Personal Assistant Robot | `_base_personal_assistant_robot_i` | `_base_robot01_torso` | `_base_robot_01` | `_base_robot01_{arm,leg,head}` | `_d01_` |
| `_base_admin_robot_i` | Operator Robot | `_base_admin_robot_i` | `_base_admin_robot_01_torso` | `_base_admin_robot_i` | `_base_admin_robot_01_*` | `_ad01_` (Ausnahme: `_admin01_weldArmRight`) |
| `_base_agriculture_robot_i` | Farmer Robot | `_base_agriculture_robot_i` | `_base_agriculture_robot_01_torso` | `_base_agriculture_robot_i` | `_base_agriculture_robot_01_*` | `_ar01_` |
| `_base_hazard_robot_i` | Hazard Robot | `_base_hazard_robot_i` | `_base_robot_hazard_01_torso` | `_base_hazard_robot_i` | `_base_robot_hazard_01_*` | `_hr01_` |
| `_base_military_robot_i` | Combat Robot | `_base_military_robot_i` | `_base_military_robot_01_torso` | `_base_military_robot_i` | `_base_military_robot_01_*` | `_mr01_` |
| `_base_military_robot_ii` | Assault Robot | `_base_military_robot_ii` | `_base_military_robot_02_torso` | `_base_military_robot_ii` | `_base_military_robot_02_*` | `_mr02_` |
| `_base_mining_robot_i` | Miner Robot | `_base_mining_robot_i` | `_base_mining_robot_01_torso` | `_base_mining_robot_i` | `_base_mining_robot_01_*` | `_mir01_` |
| `_base_science_robot_i` | Science Robot | `_base_science_robot_i` | `_base_robot_science_01_torso` | `_base_science_robot_i` | `_base_robot_science_01_*` | `_sr01_` |
| `_base_scout_robot_i` | Scout Robot | `_base_scout_robot_i` | `_base_robot_scout_01_torso` | `_base_scout_robot_i` | `_base_robot_scout_01_*` | `_scr01_` |

Item-Flags: Torso `flags: 512` = `AL_STARTER` (0x200). Verkaufs-Item `flags: 16908288` =
`SALES_ITEM_ASSEMBLY_LINE` (0x20000) | `WORKSTATION_ITEM` (0x1000000) (Enum `ItemTemplate.ItemTemplateFlags`).

### Lackieren (AL_Painter, Pflicht)
Jedes Teil hat Farbvarianten. `_metal` braucht keine Farbe. Die anderen 6 Farben (green, red, yellow, blue, orange, purple)
verbrauchen `_base_paint`: **Torso 30 L, jeder Arm/jedes Bein 15 L, Kopf 10 L** (Komplettlackierung = 100 L).
Energie fürs Lackieren pro Teil: Torso 50 kJ, sonst 75 kJ (`requiredPowerForPainting_kj_str`).
Der Painter (`_base_al_painter_i`, `al_producer_machineType: 1`) hat eine Fluid-Box mit 5000 L und 5000 L/s.
Er wird pro ALOT und pro Teil auf eine Farbe eingestellt (`alProducerEntity_setPaintingStep`).

**Lackieren ist Pflicht** (nativ): `AL_EndConsumerEntity::alcm_validateItemForConsumption` nimmt ein Objekt nur, wenn alle Stufen
fertig sind **und** das Lackiert-Flag gesetzt ist. Das setzt nur `AL_Item::processPainting`. Sonst gibt es Fehler 8 ("Target does not accept
this object"). Der Painter nimmt nur fertige, noch nicht lackierte Objekte (sonst Fehler 5) desselben ALOT (sonst Fehler 3).
**Painter-Energie** = Σ `requiredPowerForPainting` **aller** Teile, auch bei Metall (`recalculatePainterCosts`): 50 + 5 × 75 = **425 kJ**
pro Roboter. Metall spart nur die Farbe, nicht die Energie. Export: `derived.painterPowerKJ`, `derived.totalPowerKJ` = 3975 kJ.

## Reihenfolge und Stationen

- **Ein Producer = eine Aktion.** `alProducerEntity_setAction(entityId, characterId, actionId)`
  (`AL_ProducerSetActionEvent.cs`). Für einen Roboter braucht man also 10 Producer-Einstellungen
  (Schleifen über Splitter/Merger sind denkbar, aber nicht geprüft).
- Unteraktionen (Schweißen) hängen im Baum unter ihrer Attach-Aktion. An die native Seite gehen sie als
  `_nested` mit `parentStageActionId` (`NativeWrapper._pushNestedSubActions`, Z. 1735).
- **Reihenfolge (nativ belegt, `AL_Item::_isReadyForActionIterativeCheck`):** Eine Aktion ist dran, wenn sie in der aktuellen
  Stufe noch nicht erledigt ist und ihre Elternaktion erledigt ist. Die 5 Attach-Aktionen gehen also **in beliebiger Reihenfolge**,
  jede Schweiß-Aktion erst nach ihrem Attach, und nichts doppelt. Stufen laufen nacheinander (alle Roboter haben nur eine Stufe).
- **Falsch sortierte Linie blockiert:** Kann ein Objekt die Aktion des nächsten Producers gerade nicht bekommen, bleibt es
  davor stehen (Fehler 2 "This object is not ready to be processed at the upcoming machine"). Die Objekte dahinter stauen sich.
  Es fährt nicht durch.
- **Reihenfolge der Stationen:** Start → 10 Producer (Attach vor zugehörigem Weld) → Painter → Endverbraucher.
- **Endverbraucher** (`AL_EndConsumerEntity::tickUpdate`): legt das Verkaufs-Item des ALOT in sein Inventar, 40 Slots × Stapel 10
  = 400 Roboter, dann staut es. **Offen:** ob die eingestellte Verkaufs-Item-Auswahl andere Roboter abweist.

## Maschinen (Werte aus `buildableobjects/*.asset`)

| BOT | Identifier | `type` | Werte |
|---|---|---|---|
| `AL_Start BOT` | `_base_al_start` | 43 (AL_Start) | slotWidth 2700, speed 10 Slots/Tick, **50 kJ pro Aktion** |
| `AL_Producer BOT` | `_base_al_producer_i` | 45 (AL_Producer), machineType 0 | input 1537 / output 2663 Slots, speed 10 |
| `AL_Painter BOT` | `_base_al_painter_i` | 45, machineType 1 | wie Producer + Fluid-Box `_base_pipe` 5000 L |
| `AL_EndConsumer I BOT` | `_base_al_end_consumer_i` | 46 | `al_endConsumer_slotCount: 40` |
| `AL_Rail_* BOT` (Straight, Curve L/R, Slope Up/Down, HVG-Varianten) | `_base_al_rail_*` | 44 | Straight: slotWidth 600 (= 1 m), speed 10 |
| `AL_Splitter BOT` | `_base_al_splitter` | 47 | speed 10, 3 Ausgänge |
| `AL_Merger BOT` | `_base_al_merger` | 48 | speed 10, 3 Eingänge |

Es gibt **keine Tiers** (nur jeweils "I"). Strom (korrigiert nach unabhängiger Prüfung, `raw/…/buildableobjects/*.asset`):
nur **Start, Producer und Painter verbrauchen** (`powerComponentType: PCM`, `powerSubType: POWER_CONSUMER`,
`poleGridType: GenericPowerConsumer`, Anschluss übers Strommast-Netz). Splitter, Merger, Kurven- und HVG-Schienen sind
`PCM` mit `powerSubType: GENERIC` und `poleGridType: PowerPole`: Sie leiten Strom weiter und verbrauchen nichts.
Endverbraucher und gerade/schräge Schienen ohne HVG haben keine Stromkomponente. `energyConsumptionKW_str` ist leer.
Der Verbrauch ist also kein Dauerwert, sondern hängt an den Aktionen (kJ pro Aktion). In `machines.json` stehen dafür
`power.poleGridType` und `power.hasPoleGridConnection`.

## Durchsatz

- Tick-Rate: `GameRoot.LOCKSTEP_TICKS_PER_SECOND = 60`.
- Schiene: 10 Slots/Tick × 60 = 600 Slots/s = **1 m/s** (`SLOTS_PER_METER = 600`).
- Ein Objekt ist `RAIL_ITEM_LENGTH = 1125` Slots lang (1,875 m).
- Das Spiel rechnet für die UI (`AssemblyLineProducerActionTemplate.getItemsPerMinute`):
  `items/min = amount × speedInSlotsPerTick × 3600 / 1125` → bei speed 10: **32 Objekte/min**,
  also 32 Teile/min pro Attach-Producer. Fluide: `amount / 10000 × 32` (fpm-Festkomma).
  Painter-Farbe genauso (`SPP_AL_Producer.cs` Z. 279).
- Das ist die **Obergrenze der Schiene**. Ein einzelner `AL_Start` erreicht sie nicht ganz: Er setzt ein neues Objekt erst, wenn
  der Abstand zum vorigen 1125 Slots erreicht, und der wächst um 10 pro Tick. Das ergibt ein Objekt alle `ceil(1125/10)` = 113 Ticks,
  also **31,86 Objekte/min** (nativ `AL_StartEntity`, Export `derived.singleStartObjectsPerMinute`). 32/min nur mit mehreren
  zusammengeführten Starts.
- **Aktionen brauchen keine eigene Zeit** (nativ): Die Aktion wirkt in dem Tick, in dem das Objekt vom Eingang auf den Ausgang des Producers
  wechselt (`addFromDirectConnection` → `consumeOperationRequirements`). Die Animation folgt nur der Position
  (`(gap + 562) / 1124`). Mit genug Teilen und Strom begrenzt also nur die Schiene.
- **Energiepuffer** (nativ `AL_ProducerEntity::tickUpdate`, `AL_StartEntity::tickUpdate`): fasst 2 Aktionen (UI: `chargedPower / (2 × powerCost)`,
  `SPP_AL_Producer.cs` Z. 263). Laden pro Tick = `min(2 × floor(K / floor(1125/speed)), 2 × K − geladen)` × Strom-Zufriedenheit,
  mit K = Kosten in Festkomma (kJ × 10000) und `floor(1125/10)` = 112. Beispiel Attach: K = 2 000 000, 2 × floor(2 000 000/112)
  = 35 714 → 3,5714 kJ pro Tick → 214 kW. (Mit K in kJ gerechnet käme fälschlich 2 kJ/Tick = 120 kW heraus.)
  Spitzenlast beim Nachladen: Attach (200 kJ) ≈ 214 kW, Weld (500 kJ) ≈ 536 kW, Start (50 kJ) ≈ 54 kW, Painter (425 kJ) ≈ 455 kW.
  Bei vollem Puffer 0 kW. Durchschnitt bei 31,86/min: Attach ≈ 106 kW, Weld ≈ 266 kW, Start ≈ 27 kW, Painter ≈ 226 kW.
  Eine Aktion lädt in ≈ 56 Ticks nach. Energie begrenzt den Durchsatz also nicht, solange das Netz liefert.

## Export (umgesetzt in `extractor/`, Format: `findings/schema.md` → `assembly_line.json`)

Der Extractor liest ALOT/ALPA/Items/Forschung/Maschinen aus dem mitgelieferten YAML-Dump `foundry_Data/StreamingAssets/Templates/`
(Entwickler-Artefakt, bei jedem Export gegen `foundry_main_bundle` abgeglichen; bei Abweichung oder fehlendem Dump liest er die
Templates aus dem Bundle, `findings/schema.md` → Quellen) und die Stages direkt aus `StreamingAssets/AssetBundles/foundry_main_bundle`
(Pfad aus `assemblyLineStages`, aufgelöst über `m_Container`).

- Umsetzung: `extractor/foundry_export/build.py` (Abschnitt "assembly line"), Stages-Decoder `extractor/foundry_export/odin_binary.py` (`decode`).
- Pro Roboter: Eingaben = Torso + Σ `requiredItems` (`derived.inputs`), Fluide (`derived.fluidInputs`), Energie
  = 50 (Start) + Σ `powerCost` (3500) + 425 (Painter) = `derived.totalPowerKJ` 3975, Farbe für eine Komplettlackierung je Farbstoff
  (`derived.fullPaint`), Aktionsbaum in Tiefensuche-Reihenfolge mit `parentAction`, Ausgabe = Verkaufs-Item. **Keine `timeMs`.**
- Durchsatz (abgeleitet): `derived.maxObjectsPerMinute` = 32 (Schienengrenze), `derived.singleStartObjectsPerMinute` = 31,86 (ein Start).
- Neue Schlüssel in den dekodierten Stages meldet der Export als `unknown-field: AssemblyLineStages.…` (Pseudo-Typ in der Baseline
  und in `template_fields.json`), z. B. falls ein Patch eine Zeit pro Aktion einführt.
- Die nativen Grundlagen prüft `python3 extractor/tools/check_native_constants.py` bei jedem Update (UPDATE.md Schritt g):
  Konstanten 600/1125 und das Vorhandensein der Funktionen oben; die ausgegebenen Funktionsgrößen werden mit der Tabelle in
  `findings/verification.md` verglichen (geänderte Größe = Code geändert, Punkte 4–7 in `open_questions.md` neu bewerten).
