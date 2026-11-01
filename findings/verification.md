# Unabhängige Prüfung der Findings (Spielversion 0.6.0.26518, Steam-Build 23077581)

Stand 2026-11-01. Geprüft wurden `findings/assembly_line.md`, `findings/schema.md`, `findings/legacy_comparison.md`, die
offenen Punkte (damals ein Abschnitt in `extractor/README.md`, heute `findings/open_questions.md`) und der Export selbst
(`out/v0.6.0.26518`). Runde 3 (unten) prüfte zusätzlich Code, Runbook (`UPDATE.md`) und den Update-Ablauf.

## Vorgehen

1. **Runde 1: drei unabhängige Prüfer** (nur lesend, Auftrag: *widerlegen*, nicht bestätigen). Bereiche: Assembly Line,
   Crafting/Maschinen, Datenmodell/Lokalisierung. Quellen: `decompiled/Main/*.cs`, der Template-Dump
   (`StreamingAssets/Templates`), der AssetRipper-Export (`raw/`) und, über C# hinaus, die native Simulation
   `foundry_Data/Plugins/x86_64/FoundryNative.dll`. Das Spiel liefert die vollständige Symboldatei `FoundryNative.pdb` (142 MB) mit,
   damit lassen sich die nativen Funktionen per Name finden und mit `objdump` disassemblieren.
2. **Runde 2: drei adversariale Prüfer** nur für die nativen Aussagen. Jeder schrieb einen eigenen PDB/MSF-Parser und eigene
   Disassembly-Auswertung, ohne die Ergebnisse von Runde 1 zu übernehmen.
3. **Vollvergleiche:** alle 350 Rezepte, 578 Maschinen, 512 Items, 173 Forschungen gegen den Dump (0 Abweichungen); alle 9
   Stages-Assets mit eigenem Odin-Decoder (9/9 identisch); Dump gegen Bundle für alle 67 Template-Typen (identisch bis auf
   fehlende GUIDs und `null`↔`""` in 14 nicht exportierten Feldern); Lokalisierung de/ja/en komplett gegen die `.mo` (0 Abweichungen).

Native Funktionen werden über ihren Namen in der PDB gefunden (`check_native_constants.py --find <Name>`), Adressen und
Befehlsfolgen stehen nicht in diesem Repository.
**Stolperstein für spätere Prüfungen:** Die globale Festkomma-Basis der nativen Bibliothek steht in der Datei als 100000000 und
wird zur Laufzeit von `preInitializeNativeFixedPointLibrary` und `initializeNativePlugin` auf 10000 gesetzt. Wer den Dateiwert
nimmt, liegt um Faktor 10⁴ daneben.

## Bestätigt

| Aussage | Beleg |
|---|---|
| Spielversion 0.6.0.26518, Build 23077581, Unity 2022.3.51f1 | `version.txt` (= `Application.version` + `BuildInfo.kRevisionString`, `AppVersion.cs` Z. 47), `appmanifest_983870.acf`, Bundle-Header = `globalgamemanagers` |
| Assembly Line ist kein CraftingRecipe: Starter → ALOT → Stages-Baum → ALPA | `ItemTemplate.cs` Z. 732–744, `AssemblyLineObjectTemplate.onLoadPostprocess`, `NativeWrapper.cs` Z. 1686–1765 |
| Alle 9 Roboter: 5 Attach (200 kJ) mit je verschachteltem Weld (500 kJ), 3500 kJ + 50 kJ Start, keine Fluide, 100 L Komplettlackierung | eigener Odin-Decode aller 9 Stages-Assets, ALPA-YAML; Export 9/9 identisch |
| `AssemblyStageActionType` 1 = Attach, 2 = MachineInteraction | `AssemblyLineObjectTemplate.cs` (Enum), Decode |
| Konstanten 60 Ticks/s, 600 Slots/m, 1125 Slots pro Objekt | `GameRoot.cs` Z. 975, `AssemblyLineSystem.cs` Z. 27/29; PDB-Konstanten `ASSEMBLY_RAIL_ITEM_LENGTH = 1125`, `ASSEMBLY_RAIL_SLOTS_PER_M = 600` |
| Energiepuffer 2 Aktionen | `SPP_AL_Producer.cs` Z. 262; nativ `AL_ProducerEntity::tickUpdate` (lädt nur bis `2 × Kosten`) |
| Stage-Titel nicht lokalisiert | `PoMgr.cs` Z. 400 überspringt `UnityEngine.Object`-Felder; `stages` ist eine Property (`AssemblyLineObjectTemplate.cs` Z. 174); keine Stage-Schlüssel in den `.mo` |
| Producer/AutoProducer/ModularEntityProducer-Annahme von Rezepten | `CraftingRecipe.cs` Z. 310–388; alle 350 Rezepte unabhängig nachgerechnet, gleiche Mengen |
| Raten-Formel `amount × chance × 60 / craftTimeSec` | `CraftingRecipe.getItemsPerMinute` (Z. 481–518), `ProducerGO.getProducerCraftTimeInMsFPM`; nativ s. u. |
| Maschinen-Simulation: `timeMs / modifier / (1 + speedBonus)`, Fortschritt pro Tick = Strom-Zufriedenheit, Rest wird übertragen | nativ `ProducerEntity::tryStartProduction` / `::tickUpdate` / `::tryFinishProduction`, `AutoProducerEntity::tryStartProduction`. Umrechnung mit 166666 statt 166666,67 (≈ 4 ppm, nicht eingerechnet) |
| Nur der Modifier des eigenen BOT-Typs zählt (`_base_smelter_i`: AutoProducer → 1,5) | `NativeWrapper.cs` Z. 945/958; nativ liest `ProducerEntity::tryStartProduction` nur den Producer-, `AutoProducerEntity::tryStartProduction` nur den AutoProducer-Modifier des Gebäudetemplates |
| **Heavy Caster ×32, kein Modul-Term** | nativ `ModularProducerEntity::tryStartProduction` (Modifier im Gebäudetemplate = 320000, also ×32), Workstation-Term immer 0; Module min = max = 1 |
| Base Station Tempo 1, ganze Ticks | nativ `BaseStationFurnace::tickUpdate` |
| **Strommangel wirkt linear**, kein Schwellwert | nativ virtueller Aufruf `getPowerSatisfactionFPM`, `EnergySystem` |
| Erkundungsbonus Handwerk additiv, max. 90 %, nur mit Flag `CharacterCraftingSpeed` | `CharacterManager.cs` Z. 373–381, `ExplorationSystem.cs` Z. 175–178 |
| Festkomma-Faktor 10000, höchstens 4 Nachkommastellen | `ExtensionMethods.cs` Z. 129–187 |
| Lokalisierungs-Schlüssel `PoMgr.generateId`, Rückfall auf Englisch | `PoMgr.cs` Z. 415–506 |
| Erkundungs-Rezeptfreischaltung nur mit Flag `UnlockCraftingRecipe` | `ExplorationUnlockTemplate.cs` Z. 180–194 |
| Warnung `recipes use undefined crafting tag base_station` ist harmlos | Tags sind nur String-Hashes (`ItemTemplateManager.registerCraftingRecipe` Z. 1034–1047); CraftingTag-Objekte braucht nur der AutoProducer |
| `legacy_comparison.md` (Stichprobe aller Zahlen) | eigener Vergleich gegen `foundry-recipe-data` v0.6.0.24200. Handwerks-Zeile nach Korrektur ×5 → ×3 neu erzeugt (Runde 3: `compare_legacy.py` nutzt jetzt `build.CHARACTER_SPEED`) |

## Korrigiert (und umgesetzt)

| Bisher | Richtig | Beleg | Umgesetzt in |
|---|---|---|---|
| **Handwerk ×5** | **×3** (Simulation), ganze 60-Hz-Ticks: `max(1, trunc(round(trunc(round(timeMs·10⁸/30000)/1000)·600000/10⁴)/10⁴))`. Der Tooltip zeigt `/5` (C#, nur UI) | nativ `CraftingAction::reinitialize`: `timeMs × 10⁴`, dann gerundete Festkomma-Division durch 30000 (= 3 × 10⁴; timeMs aus `templateManager_registerCraftingRecipe`). Aufrufpfad `character_craftingQueueInteraction` → `CraftingQueue::queueCraftingAction` → `reinitialize`; `CraftingQueue::tickUpdate` zählt 1 pro Tick. **Zwei unabhängige Lesungen** | `build.CHARACTER_SPEED = 3`, `character_ticks()`; Messung: `open_questions.md` Nr. 1 |
| Painter optional | **Pflicht**: Endverbraucher nimmt nur fertige **und** lackierte Objekte (Fehler 8) | nativ `AL_EndConsumerEntity::alcm_validateItemForConsumption` prüft das Lackiert-Flag des Objekts, das nur `AL_Item::processPainting` setzt; Painter-Zweig in `AL_RailLine::advanceBeltSegment` (Fehler 5) | `assembly_line.md`, `schema.md` |
| `totalPowerKJ` = 3550 | **3975** = 3500 + 50 + **425 Painter** (alle Teile, auch Metall) | nativ `recalculatePainterCosts` (unbedingte Summe vor dem Farb-Lookup) | `derived.painterPowerKJ`, `derived.totalPowerKJ` |
| Reihenfolge der Attach-Aktionen offen | frei; nur Eltern vor Kind; falsch sortierte Linie **blockiert** (Fehler 2) | nativ `AL_Item::_isReadyForActionIterativeCheck` | `assembly_line.md` |
| Zeit pro Aktion / PCM-Laderate offen | keine Aktionszeit (Wirkung beim Übergang Eingang → Ausgang); Laden `min(2·floor(Kosten/112), 2·Kosten − geladen)` × Zufriedenheit pro Tick | nativ `AL_ProducerEntity::tickUpdate` (Ladeblock: Grenze `2 × Kosten`, Laderate aus 1125 / Tempo), `AL_StartEntity::tickUpdate` (gleicher Ladeblock) | `assembly_line.md` |
| 32 Objekte/min effektiv | ein Start: **31,86/min** (ein Objekt alle 113 Ticks); 32/min nur Schienengrenze | nativ `AL_StartEntity` (Spawn erst bei Abstand ≥ 1125) | `derived.singleStartObjectsPerMinute` |
| Stromverbrauch der AL-Blöcke "PCM" | nur Start/Producer/Painter verbrauchen; Splitter/Merger/Kurven/HVG sind Strom-Weiterleitung (`PowerPole`) | `raw/…/buildableobjects/*.asset`, Template-YAML | `machines.json → power.poleGridType/hasPoleGridConnection` |
| Decoder-Pfad `extractor/odin_binary.py` | `extractor/foundry_export/odin_binary.py` | Dateisystem | `assembly_line.md` |
| `fullPaint` als Objekt beschrieben | Array | Schema | `schema.md` |
| Template-Dump "vom Spiel erzeugt" | Entwickler-Artefakt, das Spiel liest ihn nie (kann veralten) | `TemplateExporter.cs` (Editor-Knopf, `exportAllTemplates` ohne Aufrufer), `TweakManager.loadTweaksForMod` liest nur Mod-Tweaks | Abgleich Dump ↔ Bundle bei jedem Export (`source-mismatch:`) |
| alle `_str`-Felder Festkomma | nur die numerischen; einige sind Identifier/Listen. `""` → `null` ist Export-Konvention (Spiel: 0) | `ExtensionMethods.cs`, YAML-Umfrage | `schema.md` |
| `pipeContentType` 1 = Gas, 2 = Flüssigkeit | nur Shader-Kategorie; Exhaust Steam = 2 | `PipeGO.cs` Z. 76, Element-YAML | `schema.md` |
| `fuel` für alle Items mit Brennwert | nur mit Flag `BURNABLE` (11 Items betroffen) | `TooltipFrame.cs` Z. 378, `CubeInventory.cs` Z. 24–33 | `build.py` |
| `buildableObject` = Rohfeld | nur mit Flag `BUILDABLE_OBJECT` (`_base_glass`, `_base_ore_mineral_rock` betroffen) | `ItemTemplateManager.cs` Z. 653–662 | `build.py` (+ Warnung bei fehlendem Ziel) |
| Maschinenname = erstes Item alphabetisch; 208 Maschinen ohne Namen | Spiel: Items mit `BUILDABLE_OBJECT`, sonst `toggleableModes` (MultipleBuildings); `hasNameOverride` | `ItemTemplateManager.cs` Z. 653–662, `ItemTemplate.onLoadPostprocess` Z. 650–668 | `machines.json → item/name/modeName/itemAlternatives`, Lokalisierung `modeName`; alle 578 Maschinen haben jetzt einen Namen |
| `crafting_tags.derived.machines` | auch Maschinen mit festem Rezept (`geothermal_generator`, `npp_fuel_mixer` waren leer) | Export-Vergleich | `build.py` |
| Erkundungs-Abhängigkeiten vollständig | Abhängigkeiten zu **Forschungen** fehlten (13 Freischaltungen) | `ExplorationUnlockTemplate.cs` Z. 85, 237–245 | `explorationUnlocks[].researchDependencies` |
| Forschungskosten = `input_data` | Grundkosten. Endless-Forschung: `amount + max(0, n − manuell) × max(1, amount/2)` | `ResearchSystem.cs` Z. 383–394 | `research[].endlessManualLevels`, `schema.md` |
| Forschungsdauer unbekannt | Menge × `secondsPerScienceItem` / Anzahl Server, Pakete parallel | nativ `ResearchEntity`/`ResearchManager` | `research[].derived.timeSecOneServer` |
| Laufzeit-Boni "Workstation-Roboter, Xeno Power Cores" | Formel bekannt; zusätzlich Effizienz-Boni; **zwei überlappende Workstations stoppen die Maschine** | nativ `WorkstationEffectManager::calculateBonusTotals`, `ProducerEntity::onWorkstationEffectsChanged` | `schema.md` (nicht exportiert, Backlog) |
| `_base_pipe_adapter` per Hand herstellbar | im Handwerk versteckt (`isHiddenInCharacterCraftingFrame`), sonst nirgends herstellbar | `CraftingSubFrame.cs` Z. 93 | kein Character-Eintrag; bekannte Warnung |

## Native Funktionsgrößen (0.6.0.26518, Vergleichsbasis für UPDATE.md Schritt g)

Größe laut `FoundryNative.pdb` (ausgegeben von `python3 extractor/tools/check_native_constants.py`, Zeilen
`function present`, bzw. mit `--find <Name>`). Ändert sich eine Größe in einer neuen Version, hat sich der Code der Funktion
geändert, auch wenn alle Prüfungen `OK` sagen: Funktion mit `--disasm` ansehen und die zugehörigen Punkte in
`findings/open_questions.md` auf `neu messen` setzen.

| Funktion | Bytes | Punkte in `open_questions.md` | Ausgabe |
|---|---|---|---|
| `CraftingAction::reinitialize` (Überladung mit `recipe`) | 1006 | 1, 2 | `--find` |
| `CraftingQueue::tickUpdate` | 1684 | 1, 2 | Standardlauf |
| `ProducerEntity::tryStartProduction` | 907 | 10, 11 | `--find` |
| `AutoProducerEntity::tryStartProduction` | 780 | – (Raten) | `--find` |
| `ModularProducerEntity::tryStartProduction` | 999 | 3 | `--find` |
| `BaseStationEntity::BaseStationFurnace::tickUpdate` | 400 | – (Base-Station-Ticks) | `--find` |
| `AL_ProducerEntity::tickUpdate` | 773 | 4, 7 | Standardlauf |
| `AL_StartEntity::tickUpdate` | 895 | 4, 7 | Standardlauf |
| `AL_ProducerEntity::recalculatePainterCosts` | 1753 | 5 | Standardlauf |
| `AL_EndConsumerEntity::alcm_validateItemForConsumption` | 36 | 5 | Standardlauf |
| `AL_Item::processPainting` | 501 | 5 | Standardlauf |
| `AL_Item::_isReadyForActionIterativeCheck` | 175 | 6 | Standardlauf |

Weitere zitierte Funktionen (nicht automatisch geprüft, Größe in Bytes): `ProducerEntity::tickUpdate` (475),
`ResearchEntity::tickUpdate` (1267), `WorkstationEffectManager::calculateBonusTotals` (477),
`ProducerEntity::onWorkstationEffectsChanged` (594), `AL_RailLine::advanceBeltSegment` (1841),
`CraftingQueue::queueCraftingAction` (1845), `templateManager_registerCraftingRecipe` (675),
`preInitializeNativeFixedPointLibrary` (45). Alle Funktionsnamen in diesem Dokument sind gegen die PDB geprüft (Runde 3).

PDB-Konstanten ohne Disassembly der Verwendung (nur Name und Wert): `AL_ProducerEntity::LOADER_AUTO_INSERT_COST_MULTIPLIER = 3`,
`AL_StartEntity::LOADER_AUTO_INSERT_MAX = 3` (genutzt nur als Hinweis in `open_questions.md` Nr. 4). Abfrage:
```
python3 -c "import sys;sys.path.insert(0,'extractor/tools');import check_native_constants as c;from pathlib import Path;d,p=c.native_files(Path(sys.argv[1]));pdb=c.Pdb(p);[print(k,v) for k,v in sorted(pdb.constants.items()) if 'LOADER_AUTO' in k]" "$(python3 extractor/export locate --field gameDir)"
```

## Runde 3: Review und Update-Simulation

Drei weitere Prüfungen (2026-11-01): ein adversariales **Code-Review** des Extractors (Fake-Spielordner mit geänderten Templates
unter `/tmp`), ein **Doku-/Runbook-Review** (jeder Befehl in `UPDATE.md`/README ausgeführt) und eine **Update-Simulation**
(`/update` gegen eine erfundene Version 0.6.1.99999 mit geänderten Dump-Werten, neuem Feld und neuem Steam-Build). Keine falschen
Daten im Export 0.6.0.26518 gefunden. Gefunden wurden Lücken, durch die ein künftiges Update still Daten verlieren oder das Runbook
scheitern könnte. Behoben:

- **Template-Quelle:** Ein veralteter Dump wurde bevorzugt, obwohl das Spiel das Bundle lädt; ein leerer/unvollständiger Dump galt
  als gültig (0 Items, Exit-Code 0). Jetzt: Bundle bei Abweichung (`source-mismatch:` mit Beispielwerten), Rückfall auch bei
  unvollständigem Dump, `--source auto|yaml|bundle`, Ladefehler → Exit-Code 5 statt Abbruch eines anderen Typs.
- **Stillschweigender Verlust:** neue Enum-Werte (`new-enum-value:`), neue Schlüssel in den dekodierten Stufen (Pseudo-Typ
  `AssemblyLineStages`), fehlende/neue Code-Dateien (`code-changed: … missing`), Werte mit ` #` (YAML schneidet ab) werden gemeldet.
- **Schreiben:** atomar über `out/.tmp-<Version>`, Plausibilitätssperre (Exit-Code 6), kein Überschreiben fremder Versionsordner
  (Exit-Code 7), `schemaHashes` im Manifest, `template_fields.json` pro Version.
- **Robustheit von `build.py`:** `timeMs` 0, fehlender Multiplikator, fehlende Chance/Fluidmenge, Base-Station-Rezepte unter
  einem Tick erzeugen Warnungen statt Abstürzen; `NaN`/`Infinity` werden abgelehnt; `hasNameOverride` wie im Spiel;
  `fullPaint.powerKJ` = Painter-Energie.
- **`check`:** Exit-Code 15 bei `latest.json` ohne Ordner, 12 auch bei laufendem Update einer anderen Installation, 3 bei
  unvollständigem Spielordner.
- **CHANGES.md:** Warnungen zählen nicht mehr als Datenänderung (neuer Build mit gleichen Daten ergibt "keine Änderungen"),
  Hinweis zur Template-Quelle, neue Template-Felder und fehlende Übersetzungen neuer Einträge.
- **Doku/Runbook:** Handwerk ×5 in `legacy_comparison.md` (jetzt ×3), AssetRipper-Block (Pfad, Prozess blieb nach `kill %1`
  übrig, `raw.prev` verschachtelt), Dekompilier-Block (`decompiled.prev` verschachtelt, `DOTNET_ROOT`), Trockenlauf ohne Vorversion
  (keine `code-changed:`-Warnungen), `<alt>` undefiniert, erstes Update mit nie committetem `out/`, fehlende Exit-Codes und Warnungen
  in den Tabellen, Baseline bei jeder Version, Zeitangaben (Bundle-Weg ca. 4 s statt "Minuten"), `git add`-Liste, veraltete Aussagen in
  `assembly_line.md` (Painter "optional?", alter Plan, Ladeformel ohne Festkomma), zwei Funktionsangaben in diesem Dokument
  (Stelle im Code statt Funktionsstart), 11 statt 12 mehrdeutige Gebäude, Mess-Anleitungen Nr. 1/3/4, "Beim Update prüfen" für
  jeden offenen Punkt, `setup.py` meldet fehlgeschlagene DLLs mit Exit-Code 1.
- **Native Prüfung:** neues Werkzeug `extractor/tools/check_native_constants.py` (16 Prüfungen über die PDB) und die Größentabelle oben,
  damit eine geänderte Funktion auffällt, auch wenn ihre Konstanten gleich bleiben.

## Nachprüfung Rundung (2026-11-01)

Anlass: Handwerk für `_base_assembler_i` (8000 ms) steht mit 2,65 s im Datenblatt, Maschinen ohne Rundung. Selbst disassembliert
(`objdump`, Funktionen über `FoundryNative.pdb` gefunden):

| Stelle | Befund |
|---|---|
| `CraftingAction::reinitialize` | `timeMs×10⁴` → `jhFixedPointMath_multiplyDivide128BitAccuracyRound(…, 10⁴, 30000)` (rundet) → Division durch 1000 abschneidend → `×600000/10⁴` gerundet → Bonus → Division durch 10⁴ abschneidend, mindestens 1. 8000 ms: 26666667 → 26666 → 1599960 → **159 Ticks = 2,65 s** (exakt wären 160) |
| `CraftingQueue::tickUpdate` | Zähler −1 je Tick, Abschluss im Tick mit Zähler 0, nächster Auftrag ab dem Folgetick: Periode = Ticks, kein Leer-Tick |
| `ProducerEntity::tryStartProduction` | Dauer `trunc(fpm_div(fpm_div_r(timeMs·10⁴, M), 10⁴+S)·10⁴/166666)` in 1/10⁴ Tick |
| `ProducerEntity::tickUpdate` | Fortschritt += Zufriedenheit; bei Fortschritt ≥ Dauer `tryFinishProduction`, danach im selben Tick `tryStartProduction` |
| `tryFinishProduction` (Producer, AutoProducer, ModularProducer) | Fortschritt −= Dauer (Übertrag). Sonst schreibt nur die Addition in `tickUpdate` den Fortschritt, kein Zurücksetzen beim Neustart |
| `BaseStationFurnace::tickUpdate` | ganze Ticks `trunc(trunc(timeMs·10⁸/166666)/10⁴)`, Countdown |

Ergebnis: Die Tick-Kürzung gilt nur für Handwerk (und ganze Ticks bei der Base Station). Beides bildet der Export bereits ab
(`build.character_ticks`, `build.base_station_ticks`). Maschinen runden nicht auf ganze Ticks. Ihre einzige Abweichung ist der
Divisor 166666 (≈ +4 ppm, z. B. 15000 ms → 15,00006 s). Er ist nicht eingerechnet, würde in 4 Nachkommastellen 176 Zeiten und
462 Raten verschieben und ist in `findings/schema.md` dokumentiert.

## Widerlegt

- "Handwerk = `timeMs / 5`" (siehe oben, ersetzt durch `/3`).
- "Painter optional" (siehe oben).

## Offen

Alles, was nur eine Messung im Spiel endgültig klärt, steht in `findings/open_questions.md`. Die nativ belegten Punkte (1–7, 9–11)
haben dort eine Mess-Anleitung zur Bestätigung und eine Zeile "Beim Update prüfen". Ganz offen sind: Endverbraucher-Auswahl (Nr. 8), Namen mehrdeutiger Gebäude (Nr. 12)
und der Brennwert von Items ohne `BURNABLE` in nativen Verbrauchern (Nr. 13).

## Nicht exportiert, aber für Wiki/Calculator relevant

Liste in `findings/schema.md`, Abschnitt "Bewusst nicht exportiert" (Recycler, Workstation-Effekte, Förderband-Tempo, Generatoren,
Hochofen-Modi, Rohrdurchsatz, Miner, …). Das ist kein Fehler im Export, sondern der Backlog.
