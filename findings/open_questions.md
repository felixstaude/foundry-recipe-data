# Offene Punkte und Messungen im Spiel

Hier steht alles, was sich **nicht allein aus Templates/Assets** belegen lässt. Jeder Punkt hat (a) was unklar ist,
(b) warum es sich nicht aus den Dateien klären lässt und (c) eine Mess-Anleitung für das Spiel.

**Status-Werte:**
- `offen`: nicht belegt. Der Export enthält den Wert nicht oder nur als Annahme.
- `nativ belegt`: aus der Simulation (`FoundryNative.dll` + mitgelieferte `FoundryNative.pdb`) disassembliert. Zwei unabhängige
  Lesungen stimmen überein (Details: `findings/verification.md`). Der Export nutzt den Wert. Eine Messung im Spiel bestätigt ihn endgültig.
- `gemessen`: im Spiel bestätigt. Die Version steht in "gemessen am".
- `neu messen`: Ein Update hat die Grundlage berührt (UPDATE.md Schritt g). Die alte Messung gilt nicht mehr.

**Beim Update prüfen:** Jeder Punkt hat eine Zeile "Beim Update prüfen" mit den Auslösern (Warnungen aus dem Export,
Abschnitte/Identifier in `CHANGES.md`, Funktionen aus `extractor/tools/check_native_constants.py`). Die Übersicht steht in
`UPDATE.md` Schritt g. Trifft ein Auslöser zu: Status → `neu messen` (bzw. bei `offen` den Punkt neu bewerten).

**Ergebnis eintragen:** In der Tabelle `Status` auf `gemessen` setzen, unter "gemessen am" die Spielversion eintragen
(`python3 extractor/export locate --field gameVersion`) und den Messwert in die Spalte "Messwert". Weicht er von der Annahme ab:
Das Messergebnis wird in diese Datei eingetragen (z. B. "Messung Nr. X ergab …"), danach wird der Extractor angepasst und neu exportiert.
Allgemein für alle Messungen: Spiel nicht pausieren, Stoppuhr am Handy, jede Messung mindestens 2× (Mittelwert eintragen).
Wenn nicht anders angegeben: voller Strom (Netz-Zufriedenheit 100 %), keine Workstation in Reichweite.

| Nr | Punkt | Annahme im Export | Status | gemessen am (Version) | Messwert |
|---|---|---|---|---|---|
| 1 | **Handwerksfaktor** | Handwerk = `timeMs / 3`, ganze Ticks (Tooltip zeigt `/5`) | nativ belegt | – | – |
| 2 | Erkundungsbonus aufs Handwerk | additiv −10 % je Stufe, max. 90 % (nicht im Export eingerechnet) | nativ belegt | – | – |
| 3 | **Heavy-Caster-Faktor** | ×32, Module ändern nichts | nativ belegt | – | – |
| 4 | **Assembly Line: Zeit pro Aktion / Durchsatz** | Aktionen ohne eigene Zeit; 1 Start = 31,86 Roboter/min, Schiene max. 32/min | nativ belegt | – | – |
| 5 | Assembly Line: Lackieren Pflicht, Painter-Energie | Pflicht; 425 kJ pro Roboter, auch bei Metall | nativ belegt | – | – |
| 6 | Assembly Line: Reihenfolge, Blockade | Attach-Reihenfolge frei, Weld nach Attach; falsche Reihenfolge blockiert | nativ belegt | – | – |
| 7 | Assembly Line: Stromspitzen und Puffer | Puffer 2 Aktionen; Spitze Attach 214 / Weld 536 / Start 54 / Painter 455 kW | nativ belegt | – | – |
| 8 | Assembly Line: Endverbraucher-Auswahl | nimmt jeden fertigen Roboter, solange Platz (400) | offen | – | – |
| 9 | Forschungsdauer | Menge × `secondsPerScienceItem` / Anzahl Server | nativ belegt | – | – |
| 10 | Workstation-Boni, Überlappung | +25 % Tempo pro `_base_robot_01`; 2 überlappende Workstations stoppen die Maschine (nicht exportiert) | nativ belegt | – | – |
| 11 | Strommangel | linear: Dauer / Zufriedenheit, kein Schwellwert (nicht exportiert) | nativ belegt | – | – |
| 12 | Namen mehrdeutiger Gebäude (Bäume/Pflanzen, Decor-Stütze) | Item mit gleichem Identifier, sonst Modus-Item | offen | – | – |
| 13 | Brennwert von Items ohne BURNABLE-Flag | kein Brennstoff (`fuel: null`) | offen | – | – |
| 14 | Base Station: Herstellzeit | Tempo 1, ganze Ticks (3000 ms → 3,0 s), ohne Strom- und Workstation-Einfluss | nativ belegt | – | – |

---

## 1. Handwerksfaktor (wichtigster Punkt)

**(a) Unklar:** Wie lange Handwerk wirklich dauert. Der Tooltip im Spiel rechnet `timeMs / 5` (C# `Character.getCraftingTimeForRecipeInMs`,
`decompiled/Main/Character.cs` Z. 3985). Die Simulation (`FoundryNative.dll`, `CraftingAction::reinitialize`) rechnet `timeMs / 3`,
auf ganze 60-Hz-Ticks abgeschnitten. Zwei unabhängige Disassembly-Lesungen sagen beide `/3`. Der Export nutzt jetzt `/3`.
**(b) Warum nicht aus Dateien:** Das Spiel widerspricht sich selbst (UI-Formel ≠ Simulation). Nur eine Messung zeigt, ob ein Aufrufpfad übersehen wurde.
**(c) Messung:**
1. Spielstand **ohne** Erkundungs-Freischaltung "Charakterherstellungstempo" (Character Crafting Speed). Sonst die Werte unten um 10 % je Stufe kürzen.
2. Ins Inventar: 50× Maschinenteile (Machinery Parts) und 40× Technum-Stäbe (Technum Rods), damit nichts nachgecraftet werden muss.
3. 10× **Forschungspaket I** (Science Pack I, `timeMs` 30000) in die Handwerk-Warteschlange. Stoppuhr ab Klick, Stopp, wenn das 10. Paket im Inventar ist.
4. **Erwartet: 100 s** (10 × 10 s, Faktor 3). Bei 60 s (10 × 6 s) stimmt der Tooltip (Faktor 5), dann Bescheid geben.
5. Gegenprobe: zusätzlich 10× Xenoferrit-Platten (Xenoferrite Plates) und 10× Maschinenteile ins Inventar (die aus Schritt 2 sind
   für die Pakete verbraucht; sonst craftet der Charakter Zwischenprodukte nach und die Zeit stimmt nicht). Dann 10 Aufträge
   **Förderband I** (Conveyor I, `timeMs` 3000, 1 Xenoferrit-Platte + 1 Maschinenteil → 2 Stück, also 20 Stück):
   erwartet 10 s (Faktor 3), bei Faktor 5 6 s.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `CraftingAction::reinitialize` oder
`CraftingQueue::tickUpdate` bzw. `MISMATCH` bei "hand-crafting divisor" (`check_native_constants.py`); `code-changed: Main.dll`
mit `MISMATCH` beim Tooltip-Teiler (`check_code_constants.py`); CHANGES.md → Rezepte `_base_science_pack_i` und `_base_conveyor_i`
(`timeMs`, Zutaten). Bei Änderung Status → `neu messen`.

## 2. Erkundungsbonus aufs Handwerk

**(a) Unklar:** Ob jede Stufe "Charakterherstellungstempo I–V" die Zeit additiv um 10 % kürzt (max. 90 %).
Die Summe bildet C# (`CharacterManager.increasePlayerCharacterCraftingSpeedByResearch`: `min(D + 10 %, 90 %)`), angewendet wird sie nativ:
Ticks × (1 − Σ%/100). Nicht im Export eingerechnet (spielstandabhängig).
**(b) Warum nicht aus Dateien:** Die Anwendung passiert nativ. Die Disassembly ist eindeutig, eine Messung bestätigt nur.
**(c) Messung:** Nach Messung 1 Stufe I freischalten (20× Alien Scrap I, 5 s) und Messung 1 wiederholen: erwartet **90 s**.
Nach Stufe I+II: 80 s. Nach allen fünf: 50 s.

**Beim Update prüfen:** wie Nr. 1, dazu CHANGES.md → Erkundungs-Freischaltungen `_base_character_crafting_speed_i` bis `_v`
(`characterCraftingSpeedBonusPercent`, `requirements`) und `code-changed: Main.dll` (`CharacterManager.increasePlayerCharacterCraftingSpeedByResearch`).

## 3. Heavy-Caster-Faktor

**(a) Unklar:** Ob der Heavy Caster (Formgießer, `_base_casting_building_base`, `modularProducer_recipeTimeModifier_str: 32`) wirklich ×32 läuft.
Nativ `ModularProducerEntity::tryStartProduction`: Faktor direkt aus dem Template, Workstation-Term immer 0, kein Modul-Term.
Alle drei Module sind Pflicht (je genau 1), es gibt keine optionalen.
**(b) Warum nicht aus Dateien:** Simulation nativ. Ob Fluid-Zufuhr oder Strom in der Praxis begrenzen, zeigt nur das Spiel.
**(c) Messung:**
1. Heavy Caster mit vollem Strom (2000 kW), Rezept **Xenoferrit-Platten (Tier 3)** (7500 ms, 15 L geschmolzenes XF → 5 Platten).
2. Laufen lassen, bis der Eingangs-Fluidpuffer voll ist (3000 L). Dann ein Rohrstück entfernen (Zufuhr weg), Ausgang leeren, Stoppuhr starten.
3. Stopp, wenn das geschmolzene XF 0 L erreicht (dann sind 1000 Platten entstanden). Platten im Ausgang zählen (erwartet 1000).
4. **Erwartet: ≈ 47 s** (200 Durchläufe × 0,234 s, also 1280 Platten/min). Bei ×1 wären es 25 min.
   Zum Vergleich: Gießmaschine (Casting Machine) auf demselben Rezept: 10 Durchläufe in 75 s.
5. **Vorbehalt Ausgangspuffer:** Ob der Ausgang 1000 Platten fasst, steht in keiner Datei (der Export zeigt nur `itemSlots`
   `Output: 8`, Xenoferrit-Platten stapeln bis 200). Bleibt der Formgießer vorher stehen (Ausgang voll), ist das **kein** Beleg
   gegen ×32: Messung mit Abzug per Lader/Förderband wiederholen oder nur bis zum ersten Stillstand messen und Platten/Zeit
   notieren (erwartet 1280/min = 21,3 Platten/s).

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `ModularProducerEntity::tryStartProduction`
oder `MISMATCH` beim ms→Tick-Teiler (`check_native_constants.py`); CHANGES.md → Maschine `_base_casting_building_base`
(`crafting.speedMultiplier`, `itemSlots`), Rezept `_base_xf_plates_t3` (`timeMs`, Fluid-Menge), neue `modularProducer_*`-Felder
(`unknown-field:`/"Template-Felder").

## 4. Assembly Line: Zeit pro Aktion und Durchsatz

**(a) Unklar:** Ob Aktionen eine Mindestdauer haben und wie viele Roboter pro Minute eine Linie schafft. Nativ: Die Aktion wirkt beim Übergang vom
Eingang auf den Ausgang des Producers, ohne Timer. Die Animation folgt nur der Position. Ein `AL_Start` setzt ein Objekt alle
`ceil(1125/10)` = 113 Ticks → **31,86/min**. Die Schiene erlaubt 32/min.
**(b) Warum nicht aus Dateien:** Assets haben kein Zeitfeld. Die Logik ist nativ (`AL_RailLine::advanceBeltSegment`, `AL_StartEntity`).
**(c) Messung:**
1. Linie: Fertigungslinien-Start (Personal-Assistant-Torso) → 10 Producer (5× Attach, je danach das passende Weld) → Painter → Endverbraucher,
   mit geraden Schienen. Reichlich Strom (Batterien). Producer über Lader vorfüllen (wie viel ein Lader einfüllt, ist nicht
   disassembliert; die PDB nennt die Konstante `AL_ProducerEntity::LOADER_AUTO_INSERT_COST_MULTIPLIER = 3`, also vermutlich bis
   zum 3-fachen Bedarf einer Aktion). Farbe per Rohr.
2. Wenn die Linie voll läuft: 10 min lang die Roboter zählen, die im Endverbraucher ankommen (Inventar vorher und nachher ablesen).
3. **Erwartet: 318–319** (31,86/min). Bei deutlich weniger: Es gibt doch eine Aktionszeit, dann Bescheid geben.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `AL_ProducerEntity::tickUpdate` oder
`AL_StartEntity::tickUpdate` bzw. `MISMATCH` bei `ASSEMBLY_RAIL_ITEM_LENGTH`/`ASSEMBLY_RAIL_SLOTS_PER_M` (`check_native_constants.py`);
CHANGES.md → Assembly-Line-Maschinen (`speedSlotsPerTick`), Konstanten, Roboter `derived.singleStartObjectsPerMinute`/`maxObjectsPerMinute`;
`unknown-field:` bei `AssemblyLineStages`, `AssemblyLineProducerActionTemplate` oder `BuildableObjectTemplate.al_*` (mögliche Zeit pro Aktion).

## 5. Assembly Line: Lackieren Pflicht, Painter-Energie

**(a) Unklar:** Nativ belegt: Der Endverbraucher nimmt nur fertige **und** lackierte Objekte. Der Painter berechnet alle 6 Teile (425 kJ), auch bei Metall.
**(b) Warum nicht aus Dateien:** nur nativ (`alcm_validateItemForConsumption`, `recalculatePainterCosts`).
**(c) Messung:**
- A: Linie ohne Painter: Der Roboter bleibt vor dem Endverbraucher stehen (Tooltip "Target does not accept this object").
- B: Painter vor das letzte Weld: Das Objekt wartet vor dem Painter (Fehler 5, "nicht bereit zum Lackieren").
- C: Painter auf "Metall" für alle Teile: Im Painter-Fenster steht "Required power per task: 425 kJ", der Balken zeigt 425/850 kJ, und es wird keine Farbe verbraucht.
- D: Alle Teile eine Farbe: 100 L Farbe pro Roboter.
Erwartet wie beschrieben. Jede Abweichung eintragen.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `AL_ProducerEntity::recalculatePainterCosts`,
`AL_EndConsumerEntity::alcm_validateItemForConsumption` oder `AL_Item::processPainting`; CHANGES.md → Roboter
(`parts[].paintingPowerKJ`, `parts[].colorVariants[].paintLiters`, `derived.painterPowerKJ`, `derived.fullPaint`), Maschine `_base_al_painter_i`.

## 6. Assembly Line: Reihenfolge und Blockade

**(a) Unklar:** Nativ belegt (`AL_Item::_isReadyForActionIterativeCheck`): Die 5 Attach-Aktionen gehen in beliebiger Reihenfolge, Weld erst nach dem passenden Attach.
Ein Objekt, das die Aktion des nächsten Producers nicht bekommen kann, bleibt stehen und blockiert die Linie.
**(b) Warum nicht aus Dateien:** nur nativ.
**(c) Messung:** A: Reihenfolge Attach Kopf, Arm rechts, Bein rechts, Bein links, Arm links, dann die 5 Welds → fertige Roboter erwartet.
B: Weld Kopf **vor** Attach Kopf → das Objekt steht vor dem Weld-Producer ("This object is not ready to be processed at the upcoming machine"), alles dahinter staut sich.
C: zwei Producer mit derselben Aktion hintereinander → Stau am zweiten.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `AL_Item::_isReadyForActionIterativeCheck`;
CHANGES.md → Assembly-Line-Stufen und -Aktionen (`parentAction`, neue/entfernte Aktionen, Reihenfolge).

## 7. Assembly Line: Stromspitzen und Puffer

**(a) Unklar:** Nativ: Puffer = 2 Aktionen. Laden pro Tick = `min(2 × floor(K/112), 2 × K − geladen)` × Zufriedenheit, K = Kosten
in Festkomma (kJ × 10000), 112 = `floor(1125/Tempo)` bei Tempo 10 (Rechenweg: `findings/assembly_line.md` → Durchsatz).
Spitze beim Nachladen: Attach ≈ 214 kW, Weld ≈ 536 kW, Start ≈ 54 kW, Painter ≈ 455 kW, bei vollem Puffer 0 kW.
**(b) Warum nicht aus Dateien:** Es gibt kein kW-Feld (`energyConsumptionKW_str` leer). Die Werte stehen nur im nativen `tickUpdate`.
**(c) Messung:** Einen Attach-Producer allein ans Netz, Stromnetz-Fenster öffnen. Einen Roboter durchlaufen lassen (Puffer fällt 400 → 200 kJ),
die Leistung beim Nachladen ablesen: **≈ 214 kW**, danach 0. Stoppuhr 200 → 400 kJ: ≈ 0,9 s. Weld: ≈ 536 kW. Start: ≈ 54 kW. Painter: ≈ 455 kW.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `AL_ProducerEntity::tickUpdate` oder
`AL_StartEntity::tickUpdate`; CHANGES.md → Assembly-Line-Aktionen (`producerAction.powerKJ`), Assembly-Line-Maschinen
(`powerPerActionKJ`, `speedSlotsPerTick`), Roboter `derived.*PowerKJ`.

## 8. Assembly Line: Endverbraucher-Auswahl

**(a) Unklar:** Ob der am Endverbraucher (Fertigungslinien-Logistikcontainer) eingestellte Roboter andere Roboter abweist. Nativ nachgewiesen ist nur:
Er legt das Verkaufs-Item des ankommenden ALOT ins Inventar, solange Platz ist (40 Slots × 10 = 400).
**(b) Warum nicht aus Dateien:** Ob die Einstellung eine Inventar-Sperre setzt, wurde nativ nicht verfolgt.
**(c) Messung:** Endverbraucher auf "Combat Robot" stellen und fertige Personal-Assistant-Roboter zuführen. Werden sie angenommen? (ja/nein, Fehlertext notieren).
Danach richtig einstellen und nicht leeren: nimmt er 400 Roboter, bevor es staut?

**Beim Update prüfen:** CHANGES.md → Maschine `_base_al_end_consumer_i` (`endConsumerSlotCount`), Items der Roboter (`stackSize`),
neue `al_endConsumer_*`-Felder (`unknown-field:`/"Template-Felder").

## 9. Forschungsdauer

**(a) Unklar:** Nativ (`ResearchEntity`/`ResearchManager`): Alle Pakettypen werden parallel verbraucht, ein Server braucht `secondsPerScienceItem` pro Paket,
Server addieren sich linear. Export: `research[].derived.timeSecOneServer`.
**(b) Warum nicht aus Dateien:** Die UI zeigt nur "Sekunden pro Item". Die Logik ist nativ.
**(c) Messung:** Forschung **Datenkabel** (Data Cable, je 25× Forschungspaket I/II/III, 60 s pro Item) mit genau 1 Forschungsserver, voller Strom,
alle Pakete vorrätig: **erwartet 25:00 min**. Mit 2 Servern: 12:30 min.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` (Forschungslogik; nicht von `check_native_constants.py` abgedeckt,
`ResearchEntity`/`ResearchManager` bei Bedarf mit `--find ResearchEntity::` und `--disasm` ansehen); CHANGES.md → Forschung
`_base_data_cable` (`secondsPerScienceItem`, `cost`), Maschine des Forschungsservers.

## 10. Workstation-Boni und Überlappung

**(a) Unklar:** Nativ: Tempo-Bonus = Σ `workstationItem_data01` der SPEED_BOOST-Roboter (`_base_robot_01`: 2500 = +25 %) × Skala.
Skala = 1 + Power-Cores × `effectScaleIncreasePerPowerCore` × `xenoPowerCore_multiplier`. Mehrverbrauch = Σ `data02` × Skala.
**Zwei überlappende Workstations setzen alle Boni auf 0 und stoppen die Maschine.** Nicht im Export (Workstation-Felder fehlen noch, `findings/schema.md`).
**(b) Warum nicht aus Dateien:** Berechnung nativ (`WorkstationEffectManager::calculateBonusTotals`).
**(c) Messung:** Fertiger I mit Forschungspaket I (30 s) in Reichweite einer Roboter-Arbeitsstation I mit einem `_base_robot_01`:
erwartet **24 s** pro Paket (30 / 1,25) und +15 % Strom. Dann eine zweite Arbeitsstation so stellen, dass sie den Fertiger auch abdeckt:
erwartet **Stillstand**.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `ProducerEntity::tryStartProduction`
(`WorkstationEffectManager::calculateBonusTotals` und `ProducerEntity::onWorkstationEffectsChanged` sind nicht abgedeckt, bei Bedarf
mit `--find` ansehen); CHANGES.md → Item `_base_robot_01`, Rezept `_base_science_pack_i`; "Template-Felder"/`unknown-field:`
bei `workstationItem_*` und `workstation_*`.

## 11. Strommangel

**(a) Unklar:** Nativ: Fortschritt pro Tick = Netz-Zufriedenheit, also linear und ohne Schwellwert. Bei 0 % kein Fortschritt.
**(b) Warum nicht aus Dateien:** nur nativ (`ProducerEntity::tickUpdate`, `EnergySystem`).
**(c) Messung:** Fertiger I mit Forschungspaket I allein an ein Netz, Erzeugung so wählen, dass das Netz-Fenster ≈ 50 % Zufriedenheit zeigt.
Erwartet ≈ 60 s pro Paket. Bei ≈ 25 %: ≈ 120 s. Genauen Prozentwert notieren.

**Beim Update prüfen:** `code-changed: FoundryNative.dll` mit geänderter Größe von `ProducerEntity::tryStartProduction`
(`ProducerEntity::tickUpdate` ist nicht abgedeckt, bei Bedarf mit `--find ProducerEntity::tickUpdate` ansehen); CHANGES.md →
Rezept `_base_science_pack_i`, Maschine `_base_assembler_i` (`power.consumptionKW`, `crafting.speedMultiplier`).

## 12. Namen mehrdeutiger Gebäude

**(a) Unklar:** 11 Gebäude (10 natürliche Bäume/Pflanzen, deren Saat-Item sie per `BUILDABLE_OBJECT` ebenfalls baut, und
`_base_decor_support_straight`) haben zwei Bau-Items mit `BUILDABLE_OBJECT`/`buildableObjectIdentifer`. Das Spiel nimmt das letzte
Item in Ladereihenfolge. Der Export bevorzugt das Item mit gleichem Identifier und listet die anderen in `itemAlternatives`
(`itemAlternatives` ist bei 43 Maschinen gesetzt; bei den übrigen 32 kommt das zweite Item nur über `toggleableModes`).
**(b) Warum nicht aus Dateien:** Die Ladereihenfolge (Dictionary-Reihenfolge im `AssetManager`) steht in keiner Datei.
**(c) Messung:** Mit der Maus auf einen natürlichen Borealwald-Baum und einen Tundra-Baum zeigen und den angezeigten Namen notieren
(Export: "Boreal Forest Tree", "Tundra Tree 01"). "Decor (Support Truss)" platzieren und den angezeigten Namen notieren (Export: "Decor (Support)").

**Beim Update prüfen:** CHANGES.md → Maschinen (`item`, `name`, `itemAlternatives`); `code-changed: Main.dll`
(`ItemTemplateManager` Z. 653–662, `ItemTemplate.onLoadPostprocess`).

## 13. Brennwert von Items ohne BURNABLE-Flag

**(a) Unklar:** 11 Items haben einen Brennwert, aber kein Flag `BURNABLE` (z. B. Space Ship Fuel Canister 25000 kJ, Construction Material 5000 kJ).
C# lehnt sie in Brennstoff-Slots ab (`CubeInventory.cs` Z. 24–33). Der Export setzt `fuel: null`.
**(b) Warum nicht aus Dateien:** Der Wert geht trotzdem an die native Seite (`NativeWrapper.cs` Z. 656). Ob irgendein nativer Verbraucher ihn nutzt, ist nicht geprüft.
**(c) Messung:** Space Ship Fuel Canister und Construction Material in den Brennstoff-Slot eines Brenngenerators und eines Kessels legen (auch per Shift-Klick).
Erwartet: abgelehnt. Wird es angenommen: Bescheid geben.

**Beim Update prüfen:** CHANGES.md → Items (`fuel`, `flags` mit/ohne `BURNABLE`), `new-enum-value:`/`removed-enum-value:` bei
`ItemTemplate.flags`; `code-changed: Main.dll` (`CubeInventory.cs` Z. 24–33, `TooltipFrame.cs` Z. 378).

## 14. Base Station: Herstellzeit

**(a) Unklar:** Wie schnell die Öfen der Base Station (`_base_baseStation01`) ihre zwei Rezepte herstellen (`_base_xf_plates_t1_primitive`,
`_base_technum_rods_t1_primitive`, je 3000 ms). Nativ (`FoundryNative.dll` `BaseStationEntity::BaseStationFurnace::tickUpdate`): Dauer in ganzen
Ticks `trunc(trunc(timeMs·10⁸/166666)/10⁴)`, ohne Geschwindigkeitsfaktor, ohne Strom- oder Workstation-Einfluss. 3000 ms ergeben 180 Ticks, also 3,0 s
(20 pro Minute und Ofen). Der Export nutzt diesen Wert (`derived.producers`, `kind: BaseStation`).
**(b) Warum nicht aus Dateien:** Das Template enthält nur die Rezeptliste. C# zeigt nur das gesperrte Rezept (`SPP_BaseStationFurnace.cs`).
Die Zeit steht nur im nativen Code.
**(c) Messung:** Einen Ofen der Base Station auf primitive Xenoferrit-Platten stellen, genug Erz einfüllen und 10 Platten abwarten.
**Erwartet: 30 s** (10 × 3,0 s). Gegenprobe: dasselbe bei leerem bzw. schwachem Stromnetz, erwartet ebenfalls 30 s.

**Beim Update prüfen:** CHANGES.md → Rezepte `_base_xf_plates_t1_primitive`, `_base_technum_rods_t1_primitive` (`timeMs`), Maschine
`_base_baseStation01`; `code-changed: FoundryNative.dll` und die Größe von `BaseStationEntity::BaseStationFurnace::tickUpdate` (Schritt g).
