# foundry-export

Exportiert die Spieldaten von FOUNDRY (Steam-App 983870) pro Spielversion als versioniertes JSON-Set
im Format `foundry-data` v1: Items, Elemente (Flüssigkeiten/Gase), Crafting-Tags, Rezepte mit echten
Maschinengeschwindigkeiten, Maschinen/Gebäude, Forschung, Assembly Line (Roboterbau) und Lokalisierung.
Ablauf bei einer neuen Spielversion: [`UPDATE.md`](../UPDATE.md).

## Voraussetzungen

- Python ≥ 3.10
- PyYAML (`pip install pyyaml`, mit libyaml schneller). Sonst keine Abhängigkeiten.
  Das Unity-Asset-Bundle wird mit eigenem UnityFS-/LZ4-/TypeTree-Leser gelesen. Ist das Modul `lz4` installiert, wird es genutzt.
- Eine installierte Spielversion (Windows-Build, auch unter Proton/Linux). `decompiled/` und `raw/` werden **nicht** benötigt.

## Befehle

```
python3 extractor/export [<Spielordner>] <Ausgabe> [--source auto|yaml|bundle] [--force] [--overwrite] [--strict]
                                                                         # Export (Spielordner optional: automatisch)
python3 extractor/export check  [--game <Pfad>] [--out out]              # installierte Version vs. out/latest.json
python3 extractor/export locate [--game <Pfad>] [--field gameDir]        # Spielordner, Version, Build (JSON)
python3 extractor/export verify out/v<Version>                           # sha256 aller Dateien (Daten + schemas/) gegen manifest.json
python3 extractor/export diff <out/v<alt>|none> out/v<neu> [--out F]     # CHANGES.md (macht der Export auch selbst)
python3 extractor/export baseline [--game <Pfad>] [--source …]           # geprüften Stand der Templates/Enums/DLL-Klassen übernehmen
python3 extractor/export itemsheet <Identifier oder Name> [--kind item|building|robot] [--json] [--out DIR] [--game <Pfad>] [--source auto|yaml|bundle]
                                                                         # Datenblatt für eine Wiki-Seite (Markdown + JSON)
python3 extractor/export schemas                                         # JSON-Schemas aus schemas.py neu schreiben
FOUNDRY_REQUIRE_GAME=1 python3 -m unittest discover -s extractor/tests -v   # Tests, ca. 35-60 s (FOUNDRY_SKIP_SLOW=1 überspringt langsame)
```

- **Spielordner:** `--game`/Positionsargument, sonst `FOUNDRY_GAME_DIR`, sonst alle Steam-Bibliotheken (`libraryfolders.vdf`,
  `appmanifest_983870.acf`; Linux nativ/Flatpak/Snap, macOS, Windows), zuletzt `game_path.txt` im Repo.
  Ein ungültiger expliziter Pfad bricht ab (Exit-Code 3), es gibt keinen stillen Rückfall.
- **Template-Quelle (`--source`):** `auto` (Standard) nimmt den Template-Dump, wenn er vollständig ist und für die 9 exportierten
  Typen mit `foundry_main_bundle` übereinstimmt. Fehlt er oder hat ein exportierter Typ keine Dateien: Bundle + Warnung
  `source: … (fallback)`. Weichen Dump und Bundle ab: Bundle (das lädt das Spiel) + Warnungen `source-mismatch:`; meldet der
  Bundle-Leser Probleme (`bundle:`), bleibt es beim Dump. `yaml`/`bundle` erzwingen eine Quelle.
- **Schreiben:** Alles wird im Speicher gebaut und gegen die Schemas geprüft, dann nach `<Ausgabe>/.tmp-<Ordner>` geschrieben und
  als Ganzes eingetauscht. Danach `index.json`, `latest.json` und `CHANGES.md`.
- **Exit-Codes Export:** 0 ok · 1 Warnungen mit `--strict` (ohne `--strict`: unerwarteter Fehler) · 2 Schemafehler
  (`SCHEMA ERRORS`) oder falscher Aufruf (`usage:`), nichts geschrieben · 3 Spiel nicht gefunden oder Spielordner unvollständig · 4 CHANGES.md fehlgeschlagen (Daten sind geschrieben) · 5 Template-Typ nicht lesbar
  (`TEMPLATE LOAD ERROR`), nichts geschrieben · 6 Plausibilitätssperre: eine exportierte Datendatei ist leer oder hat weniger als
  50 % der Einträge der Vorversion, nichts geschrieben (`--force` übergeht) · 7 Überschreiben verweigert, nichts geschrieben
  (`--overwrite` übergeht) · 12 Steam-Update unvollständig (`--force` übergeht).
- **Exit-Codes `check`:** 0 gleich · 10 neue Version · 11 gleiche `version.txt`, anderer Steam-Build · 12 Steam-Update unvollständig
  (auch wenn eine andere Installation mit neuerem `LastUpdated` gerade aktualisiert wird) · 13 noch kein Export ·
  14 installierte Version älter als `out/latest.json` · 15 `out/latest.json` zeigt auf einen Ordner ohne `manifest.json` ·
  3 Spiel nicht gefunden oder Spielordner unvollständig.
- Dauer ca. 6 s (davon ca. 3 s für den Abgleich Template-Dump ↔ Bundle), mit `--source bundle` ca. 4 s.
- Gleiche Spielversion → byte-gleiche Daten. Nur `generatedAt` (in `manifest.json`, `index.json`, `latest.json`, `CHANGES.md`) ändert sich.
- **Vorhandene Versionsordner:** `v<Version>` wird nur ersetzt, wenn er der neueste Export ist **und** denselben Steam-Build hat
  (erneuter Export während eines Updates). Anderer Build → neuer Ordner `v<Version>-b<Build>` (Warnung `source: v… already exists …`).
  Alles andere (älterer Ordner, fehlende Build-ID auf einer Seite) wird verweigert (Exit-Code 7), außer mit `--overwrite`.

## Gelesene Quellen

| Quelle im Spielordner | Wofür |
|---|---|
| `version.txt`, `steamapps/appmanifest_983870.acf` der Bibliothek | Spielversion, Steam-Build, Beta-Branch (`BetaKey`), Update-Status (`StateFlags`) |
| `*_Data/StreamingAssets/Templates/<Typ>/*.yaml` | alle Templates (Dump des Entwickler-Werkzeugs `TemplateExporter`; das Spiel selbst liest ihn nicht) |
| `*_Data/StreamingAssets/AssetBundles/foundry_main_bundle` | Odin-serialisierte `AssemblyLineStages`. Abgleich aller exportierten Template-Typen mit dem Dump. Quelle, wenn der Dump fehlt, unvollständig ist oder abweicht |
| `*_Data/Managed/*.dll` | nur Metadaten: Feldnamen/Enums für den Bundle-Weg, Klassenliste (`dll-types`), Hashes (`code-changed`). Ohne DLLs: `foundry_export/data/managed_types.json` |
| `*_Data/Plugins/x86_64/FoundryNative.dll` (+ mitgelieferte `FoundryNative.pdb`) | nur Hash (`code-changed:`). Die nativen Formeln prüft `tools/check_native_constants.py` (über die `.pdb`) |
| `*_Data/StreamingAssets/locale/*/LC_MESSAGES/foundry_templates-*.mo` | Übersetzungen (Schlüssel wie `PoMgr.generateId`) |

## Ausgabeformat

```
<Ausgabe>/
  index.json            {"latest": "v…", "versions": [{version, gameVersion, steamBuildId, generatedAt}]}
  latest.json
  v<Spielversion>/
    manifest.json       Version, Build, Branch, Unity-Version, Template-Quelle, Vorversion, Template-Anzahlen,
                        Code-Hashes (3 Managed-DLLs + FoundryNative.dll), Schema-Hashes, Dateiliste mit sha256, Warnungen
    CHANGES.md          Änderungen gegenüber der Vorversion (deutsch)
    items.json  elements.json  crafting_tags.json  recipes.json  machines.json  research.json  assembly_line.json
    template_fields.json   Feldpfade aller Template-Typen dieser Version (inkl. Pseudo-Typ AssemblyLineStages)
    localization/<lang>.json
    schemas/*.schema.json
```

Konventionen: Spiel-Identifier unverändert; Festkomma-Strings (`*_str`) als normale Zahlen; Einheiten im Feldnamen
(`Ms`, `Sec`, `KJ`, `KW`, `Liters`, `PerMin`); vom Exporter berechnete Werte stehen unter `derived`.
Vollständige Spezifikation mit Quelle jedes Felds: [`findings/schema.md`](../findings/schema.md).

Rate pro Minute: `amount × chance / (timeMs/1000) × speedMultiplier × 60` (wie `CraftingRecipe.getItemsPerMinute`).
`speedMultiplier` kommt aus `*_recipeTimeModifier_str` der Maschine (Producer, AutoProducer, ModularEntityProducer).
Base Station: 1. Handwerk (`character`): 3 (nativ, ganze Ticks; der Tooltip zeigt 5), siehe `findings/schema.md` und
`findings/open_questions.md` Nr. 1.

## Warnungen im Manifest

Nichts soll stillschweigend wegfallen. Alles Auffällige steht in `manifest.json → warnings`. Was jeweils zu tun ist: UPDATE.md Schritt d.

| Präfix | Bedeutung |
|---|---|
| `new-template-type:` / `removed-template-type:` | Template-Typ neu/entfernt gegenüber `foundry_export/baseline/known_templates.json` |
| `unknown-field:` / `removed-field:` | Feld neu/entfernt gegenüber der Baseline (exportierte Typen und `AssemblyLineStages` pro Feld, andere Typen gruppiert `Typ: a, b`) |
| `new-enum-value:` / `removed-enum-value:` | Wert in einem Feld, nach dem `build.py` verzweigt (`checks.ENUM_FIELDS`), neu/entfallen gegenüber `enumValues` der Baseline |
| `count-change:` | Datei- oder Template-Anzahl ändert sich um mehr als 20 % gegenüber der Vorversion |
| `sanity:` | Plausibilitätssperre mit `--force` übergangen |
| `dll-types:` | Klassen in `Main`/`Channel3`/`Assembly-CSharp` neu/entfernt gegenüber `baseline/dll_types.txt` |
| `code-changed:` | Hash anders als in der Vorversion, Datei fehlt (`missing (present in …)`) oder ist neu. Managed-DLL → dekompilieren + `tools/check_code_constants.py`; `FoundryNative.dll` → `tools/check_native_constants.py` (UPDATE.md Schritt g) |
| `source-mismatch:` | Template-Dump und Bundle unterscheiden sich (mit Beispiel `dump X vs bundle Y`) |
| `source:` | Template-Quelle (Rückfall, Dump ≠ Bundle, `--source bundle`), reparierte/abgeschnittene Dump-Werte, nicht lesbarer Typ (`cannot scan`), Baseline aus anderer Quelle, neuer `-b`-Ordner, Steam-Update unvollständig |
| `bundle:` | nur Bundle-Weg: unbekannter Enum-Wert, Feld ohne Typinfo, DLLs fehlen |
| `baseline:` | Baseline fehlt oder hat keine `enumValues` (Prüfungen übersprungen) |
| ohne Präfix | Konsistenz (unbekannte Referenzen, Rezept ohne Maschine, undefinierter Tag, Maschine/Rezept ohne Rate, fehlende Chance) |

Bekannte, erklärte Warnungen in 0.6.0.26518 (5): `recipes use undefined crafting tag base_station` (die Base Station wählt per Liste),
`recipe _base_pipe_adapter: no machine accepts tags ['character']` (Rezept ist im Handwerk versteckt und sonst nirgends herstellbar),
zwei `source: Templates/PlanetTemplate/… is not valid YAML` (Fehler im Dump, wird repariert gelesen) und
`source: Templates/SkyPlatformUpgradeTemplate: 11 unquoted value(s) contain " #" …` (nicht exportierter Typ).

## Offene Punkte

Was sich nicht aus Dateien klären lässt, steht mit Mess-Anleitung in [`findings/open_questions.md`](../findings/open_questions.md).
Ergebnis der unabhängigen Prüfung: [`findings/verification.md`](../findings/verification.md).

## Datenblatt für Wiki-Seiten (`itemsheet`)

```
python3 extractor/export itemsheet "Operator Robot"                 # Markdown auf die Konsole
python3 extractor/export itemsheet "Assembler I" --json             # JSON auf die Konsole
python3 extractor/export itemsheet _base_ore_xenoferrite --out sheets/   # schreibt sheets/<identifier>.<art>.md und .json
python3 extractor/export itemsheet "Operator Robot" --kind item     # Art erzwingen (item | building | robot)
```

Sammelt für ein Item, ein Gebäude oder einen Assembly-Line-Roboter alle Daten einer Wiki-Seite. Der Befehl liest das
installierte Spiel über dieselbe Ladekette wie der Export (ca. 5 s) und ändert weder `out/` noch andere Dateien.

- **Suche:** Identifier, dann exakter Name in einer beliebigen Sprache, dann eindeutiger Namensteil. Trifft ein Name mehrere
  Arten, gilt Roboter vor Gebäude vor Item. Die anderen Treffer stehen im Kopf ("Ebenfalls gefunden"). Heißen mehrere
  Gebäude gleich (Modi, Module), wird das Gebäude genommen, das ein gleichnamiges Item direkt baut, sonst das einzige mit
  Rezepten. Sonst endet der Befehl mit "mehrdeutig" (Exit-Code 1) und listet die Kandidaten.
- **Quelle je Wert:** In JSON ist jeder Datenwert ein Objekt `{"value": …, "source": …}` (Beschriftungen wie die Art der
  Gewinnung oder die Rolle in der Assembly Line sind einfache Texte), in Markdown gibt es eine Spalte "Quelle".
  - `Templates/<Typ>/<Datei>.yaml : <Feldpfad>`: Das Feld enthält genau diesen Wert (Pfade wie `input_data[1].amount`;
    `Templates/` = `<Spielordner>/foundry_Data/StreamingAssets/Templates`, der Kopf nennt den vollen Pfad).
  - `… : <Feld> = X`, `… enthält X`: Beziehung (z. B. welche Forschung ein Rezept freischaltet).
  - `locale/<Sprache>/LC_MESSAGES/foundry_templates-<Sprache>.mo : <Schlüssel>`: Übersetzung.
  - `berechnet: …` / `abgeleitet: …`: vom Befehl gerechnet, mit Formel und dem Code, dem sie folgt.
  - Assembly-Line-Stufen: `foundry_main_bundle "<Stages-Asset>" (Odin): <Pfad>`. Im Bundle-Weg: `foundry_main_bundle:<Typ>/<Identifier>`.
- **ungemessen:** Werte, die nur aus Code oder Disassembly folgen, tragen `ungemessen` mit der Nummer aus
  `findings/open_questions.md` (z. B. Handwerk Nr. 1, Heavy-Caster-Faktor Nr. 3, Assembly-Line-Durchsatz Nr. 4, Base Station Nr. 14).
  Der Status wird bei jedem Aufruf aus der Tabelle dort gelesen. Steht ein Punkt auf `gemessen`, entfällt die Markierung.
- **Inhalt:**
  - *Item:* Identifier, Namen und Beschreibungen in allen Sprachen (auch der Erkundungs-Text), Stack Size, Kategorie, Flags,
    Verkaufs- und Handelsdaten (Verkaufskategorie, Industrie, Base Price, Base Demand; Verkaufswährung), Brennwert mit
    Brennstoff-Maschinen, Workstation-Effekt, Recycling-Ergebnis. Dazu jedes Rezept mit dem Item als Ausgabe (Tags mit Namen,
    Kategorie, Zeit, Zutaten, Ausgaben mit Wahrscheinlichkeit, Rate pro Minute je Maschine bzw. Geschwindigkeitsstufe,
    freischaltende Forschung mit Kosten und Voraussetzungen), Gewinnung ohne Rezept (Terrain, Welt-Objekte, Sonderfunde,
    Endlos-Miner, Recycling, Assembly Line), Verwendung in Rezepten (Rückwärtssuche, mit Fluiden und Chancen), in der Assembly
    Line, im Hochofen, als Forschungskosten, für Erkundung (mit Wirkung) und in Quests, sowie alle weiteren Template-Verweise.
  - *Gebäude:* Name (alle Sprachen, Modus), Bau-Item, Typ, Tier (aus dem Identifier-Suffix), Umbau-Gruppe, Abmessungen, Strom
    (Verbrauch, Erzeugung, Netztyp, Strommast-Anschluss und -Reichweite; Assembly Line: Energie je Aktion und Spitzenleistung),
    Item-Slots, Fluid-Boxen, Daten- und Modulanschlüsse (mit Modulkosten), Reichweiten, typspezifische Felder, weitere vom Standard
    abweichende Felder, Rezepte auf dieser Maschine mit Zeit und Raten, Geschwindigkeitsfaktor, Baukosten (Rezept des Bau-Items
    bzw. Modulkosten) mit Forschung, Quests.
  - *Roboter:* Starter- und Verkaufs-Item, Forschung, Teile mit Lackverbrauch je Farbe und den Rezepten der Teil-Items,
    Stufen und Aktionen in Reihenfolge (kJ, Teile, Spitzenleistung), Zutaten gesamt, Lack gesamt, Energie (Producer, Start,
    Painter, gesamt), Durchsatz, Verkaufswerte.
- Nicht berechnet: Brenndauer pro Item (Verbrauchslogik nativ, nicht geprüft) und Hochofen-Raten (Zykluszeit nicht im Modus-Template).
  Der Kopf gibt Spielversion, Steam-Build und Template-Quelle an.

## Vergleich mit dem alten Datensatz

```
python3 extractor/compare_legacy.py <foundry-recipe-data>/v0.6.0.24200 out/v0.6.0.26518 --out findings/legacy_comparison.md
```
`<foundry-recipe-data>` ist ein Checkout von https://github.com/felixstaude/foundry-recipe-data.

## Module (`foundry_export/`)

| Datei | Inhalt |
|---|---|
| `cli.py` | Befehle, Schreiben (Temp-Ordner, Eintauschen), index/latest, Validierung, Plausibilitätssperre, Warnungen zusammenführen |
| `steam.py` | Spielordner finden (Steam-Bibliotheken, VDF-Parser, App-Manifest, Update-Status) |
| `game.py` | Pfade, Version, Zahlen-Helfer (`num` lehnt NaN/Inf ab) |
| `sources.py` | Template-Quellen: YAML-Dump oder Bundle, Abgleich Dump ↔ Bundle, Quellenwahl (`open_template_source`) |
| `bundle_templates.py`, `typetree.py`, `unity_bundle.py` | Templates aus `foundry_main_bundle` (TypeTrees, MonoScript-Klassen, .NET-Metadaten für Enums) |
| `odin_binary.py` | Odin-Binär-Decoder (`AssemblyLineStages`) |
| `build.py` | baut alle Dokumente (Rezept → Maschine wie `CraftingRecipe.onLoadPostprocess`; `CHARACTER_SPEED`, Tick-Umrechnung) |
| `localization.py` | `.mo` lesen, Schlüssel wie `PoMgr.generateId` |
| `checks.py` | Template-Typen/Felder/Enum-Werte gegen Baseline (inkl. `AssemblyLineStages`), Anzahl-Änderungen, Vorversion finden |
| `dll_types.py` | Klassenliste der Spiel-DLLs (ECMA-335-Metadaten, ohne Dekompilieren) |
| `diff.py` | Vergleich zweier Versionen → `CHANGES.md` |
| `itemsheet.py` | Datenblatt `itemsheet` für Item, Gebäude oder Assembly-Line-Roboter (Markdown/JSON mit Quelle je Wert) |
| `schemas.py`, `jsonschema_lite.py` | Schemas (Quelle für `schemas/*.json`) und Mini-Validator |
| `baseline/` | geprüfter Stand: `known_templates.json` (Typen, Feldpfade, `enumValues`), `dll_types.txt` (Klassen). Neu schreiben: `export baseline` |
| `data/managed_types.json` | Feld-/Enum-Metadaten für den Bundle-Weg ohne DLLs (neu: `export baseline` oder `python3 extractor/tools/gen_enums.py <Spielordner>`) |

Werkzeuge in `extractor/tools/`:
- `check_native_constants.py`: prüft die nativen Formeln, auf die sich der Export stützt (Handwerk ÷3, ms → Ticks, Assembly-Line-
  Konstanten, Vorhandensein und Größe der Assembly-Line-Funktionen), direkt in `FoundryNative.dll` über die mitgelieferte `.pdb`.
  `--find TEXT` sucht Funktionen, `--disasm` zeigt objdump-Kontext. Ca. 0,1 s.
- `check_code_constants.py`: hart kodierte C#-Konstanten gegen `decompiled/Main` prüfen (nach dem Dekompilieren).
- `gen_enums.py`: Metadaten-Snapshot `data/managed_types.json` neu erzeugen.
