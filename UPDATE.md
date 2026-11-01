# UPDATE.md: Ablauf bei neuer FOUNDRY-Version

Dieses Runbook wird bei `/update` (oder "Neue Version ist da") **Schritt für Schritt** abgearbeitet.
Es setzt kein Vorwissen aus früheren Chats voraus. Alle Befehle laufen im Projektwurzelordner.
Die exakten Befehle stehen in den Schritten und im [Anhang](#anhang-befehle). Wer sie zum ersten Mal ausführt, liest den Anhang zuerst.

Grundregeln für den ganzen Lauf:
- **Nicht nachfragen**, außer ein Schritt ist nicht rückgängig zu machen (Löschen fremder Daten, `--overwrite`, `--force`,
  Commit, Push, Veröffentlichen) oder dieses Runbook verlangt es ausdrücklich.
- **Nichts committen, pushen oder veröffentlichen**, bevor der Nutzer der Zusammenfassung (Schritt h) zugestimmt hat.
- Vorhandene Versionsordner in `out/` werden **nie** gelöscht oder überschrieben. Einzige Ausnahme: der Ordner, den der Export
  in diesem Lauf neu angelegt hat (erneuter Export in Schritt d). Das erzwingt der Export selbst (Exit-Code 7).
- Fehlschläge nicht schönreden: immer Ursache nennen (Datei, Wert, Befehl, Ausgabe).
- Behauptungen nur mit Beleg. Was sich nicht klären lässt: als "offen" in `findings/open_questions.md`.

Begriffe: `<alt>` ist der Ordnername der Vorversion (z. B. `v0.6.0.26518`, Schritt b), `<neu>` der Ordnername, den der Export
in Schritt c ausgibt (`written to out/<neu>`, z. B. `v0.6.1.12345` oder `v0.6.0.26518-b23100000`).

## Trockenmodus (`/update trocken`)

Im Trockenmodus wird **nichts im Repository geschrieben** (kein `out/`, kein `findings/`, keine Baseline, kein Code).
1. Schritt a ausführen. Exit-Code 0: melden "Keine neue Version (installiert X, Build Y = out/latest.json)" und fertig.
   3, 12, 14, 15: wie in Schritt a. 10, 11, 13: weiter mit 2. Jeder andere Exit-Code (z. B. 1 Absturz, 2 falscher Aufruf):
   abbrechen und Ausgabe melden.
2. `out/` in ein Temp-Verzeichnis kopieren und dorthin exportieren. Durch die Kopie vergleicht der Export gegen die
   Vorversion (`count-change:`, `code-changed:`) und schreibt `/tmp/fx_dry/out/<neu>/CHANGES.md` gleich mit:
   ```
   rm -rf /tmp/fx_dry && mkdir -p /tmp/fx_dry && { [ ! -d out ] || cp -r out /tmp/fx_dry/out; } && PYTHONDONTWRITEBYTECODE=1 python3 extractor/export /tmp/fx_dry/out
   ```
   Exit-Codes wie in Schritt c. Lesende Prüfungen sind erlaubt (Schritt d: Werte ansehen; Schritt g:
   `check_native_constants.py`), schreibende nicht (kein `export baseline`, kein erneuter Export nach `out/`).
3. Kurzbericht (höchstens 15 Zeilen; er ersetzt im Trockenmodus die Zusammenfassung aus Schritt h, eine Zustimmung ist
   nicht nötig, weil nichts geschrieben wurde): Version alt → neu, was wäre neu/geändert (aus CHANGES.md), welche Warnungen,
   welche Punkte aus `findings/open_questions.md` wären nach Schritt g auf `neu messen` zu setzen.

---

## Schritte

### a. Version feststellen und vergleichen
```
python3 extractor/export check --out out
```
Der Befehl findet den Spielordner selbst (Steam-Bibliotheken, `libraryfolders.vdf`; Überschreiben mit `--game <Pfad>`
oder Umgebungsvariable `FOUNDRY_GAME_DIR`). Er liest die Spielversion aus `<Spielordner>/version.txt` und den Steam-Build
aus `steamapps/appmanifest_983870.acf`. Beides vergleicht er mit `out/latest.json`.

| Exit-Code | Status | Was tun |
|---|---|---|
| 0  | `same`: Version und Build gleich | **Abbrechen** und dem Nutzer melden: "Keine neue Version (installiert X, Build Y = out/latest.json)". |
| 10 | `new-version`: neue Spielversion | weiter mit b |
| 11 | `new-build`: gleiche `version.txt`, anderer Steam-Build | weiter mit b. Der Export schreibt nach `out/v<Version>-b<Build>/` (Warnung `source: v<Version> already exists with Steam build …`). Siehe unten "Neuer Build ohne neue Daten". |
| 12 | `update-pending`: Steam lädt noch (`StateFlags` ≠ 4), auch wenn eine **andere** Steam-Installation mit neuerem `LastUpdated` gerade aktualisiert wird | **Abbrechen**: "Steam-Update noch nicht fertig". |
| 13 | `first-export`: `out/latest.json` fehlt | weiter mit c (b entfällt mangels Vorversion). CHANGES.md wird "Erster Export". |
| 14 | `older-version`: installierte Version ist **älter** als `out/latest.json` | **Abbrechen** und den Nutzer fragen (Beta-Branch gewechselt? `locate` zeigt `steamBranch`). |
| 15 | `inconsistent`: `out/latest.json` zeigt auf einen Ordner ohne `manifest.json` | **Abbrechen** und melden. Meist wurde ein Versionsordner gelöscht, aber `out/index.json`/`out/latest.json` nicht zurückgesetzt. Nicht selbst reparieren: Der Nutzer entscheidet, ob der Ordner wiederhergestellt (`git checkout -- out/`, geht nur, wenn `out/` schon committet war; sonst neu exportieren, falls das Spiel noch diese Version hat) oder index/latest zurückgesetzt werden. |
| 3  | Spiel nicht gefunden oder Spielordner unvollständig (`version.txt`/Bundle fehlt) | Abbrechen, durchsuchte Orte bzw. fehlende Datei nennen. Nutzer nach dem Pfad fragen (oder `--game`). |

**Neuer Build ohne neue Daten (Exit-Code 11):** Steht in `out/<neu>/CHANGES.md` die Zeile **"Ergebnis: keine Datenänderungen"**
(ggf. mit dem Zusatz "nur Warnungen geändert", z. B. durch die `-b`-Ordner-Warnung), sind alle Daten gleich. Dasselbe gilt, wenn die Übersicht überall 0 zeigt und nur
"Neue Felder/Dateien im Export" auftauchen (der Extractor wurde zwischendurch erweitert). Den `-b`-Ordner trotzdem **nicht löschen**. Der Export hat
`out/index.json` und `out/latest.json` schon auf ihn umgestellt. In Schritt h beide Möglichkeiten nennen und den Nutzer entscheiden lassen:
- **(A) behalten und committen (Vorschlag):** belegt "Build geprüft, Daten gleich". `check` meldet danach 0.
- **(B) verwerfen:** Ordner löschen **und** `git checkout -- out/index.json out/latest.json`. Nur den Ordner zu löschen
  ergibt beim nächsten `check` Exit-Code 15. Nach (B) meldet `check` bei jedem Lauf wieder 11, weil nirgends steht, dass
  der Build schon geprüft wurde. (B) geht nur, wenn `out/` schon committet war.

### b. Vorherige Version sichern (nur prüfen, nichts kopieren)
Die vorherige Version bleibt unverändert in `out/<alt>/` liegen. Sie ist das einzige Abbild der alten Spieldaten,
denn nach dem Steam-Update gibt es die alten Spieldateien nicht mehr. **Vor Schritt c** `<alt>` notieren (danach zeigt
`out/latest.json` schon auf die neue Version):
```
python3 -c "import json;print(json.load(open('out/latest.json'))['version'])"    # = <alt>
python3 extractor/export verify out/<alt>       # sha256 aller Dateien (Daten + schemas/) gegen manifest.json
git status --porcelain out/                      # Stand von out/ in Git
git ls-files out/ | head -1                      # leer = out/ war noch nie committet
```
- `verify` rot (Exit-Code 1, `missing …`/`changed …`): **abbrechen** und den Nutzer informieren. Nicht "reparieren".
  Hinweise mit `(info)` sind kein Fehler (z. B. `schemas/ not checked (manifest before schemaHashes)` bei älteren Exporten).
- `git status` leer: in Ordnung.
- `git status` zeigt nur `?? out/` **und** `git ls-files out/` ist leer: `out/` wurde noch nie committet (z. B. erstes Update
  nach dem Aufsetzen). **Weitermachen**, nicht nachfragen. Der Export legt nur einen neuen Ordner an und ändert
  `out/index.json`/`out/latest.json`; `out/<alt>` bleibt, `verify` belegt das. In Schritt h vermerken: "Ausgangsstand war
  nicht committet; der Commit in Schritt i enthält alte und neue Version".
- Kein Git-Repository (`git status` schlägt fehl): weitermachen, in h vermerken.
- Alles andere (`M`, `D`, oder `??` innerhalb eines schon committeten `out/`): **abbrechen** und melden
  (unerklärte Änderung an committeten Daten).

Nach Schritt c `python3 extractor/export verify out/<alt>` noch einmal laufen lassen. Der Export darf nur den neuen Ordner
sowie `out/index.json` und `out/latest.json` anfassen.

### c. Export
```
python3 extractor/export out
```
Der Export rechnet und validiert alles im Speicher, schreibt nach `out/.tmp-<neu>/` und tauscht den Ordner erst dann ein.
Danach aktualisiert er `out/index.json`/`out/latest.json` und schreibt `out/<neu>/CHANGES.md` gegen die Vorversion (Schritt e).
Dauer ca. 6 s, davon ca. 3 s für den Abgleich Template-Dump ↔ Bundle.

| Exit-Code | Bedeutung | Was tun |
|---|---|---|
| 0  | ok (Warnungen möglich) | weiter mit d |
| 2  | Schemafehler (stderr beginnt mit `SCHEMA ERRORS`) oder falscher Aufruf (stderr `usage:` / `error:`). **Nichts geschrieben** | Schemafehler: Ursache im Extractor suchen (meist ein neuer Wertetyp in einem Template-Feld), beheben, erneut exportieren. |
| 3  | Spiel nicht gefunden oder Spielordner unvollständig (stderr nennt durchsuchte Orte bzw. `incomplete game folder - missing …`) | wie Schritt a; bei `incomplete game folder`: Steam-Installation unvollständig, dem Nutzer melden (Steam: Dateien überprüfen) |
| 4  | Daten geschrieben, CHANGES.md fehlgeschlagen | `python3 extractor/export diff out/<alt> out/<neu>` von Hand (Schritt e), Fehler im Diff-Code beheben. |
| 5  | Template-Typ nicht lesbar (stderr `TEMPLATE LOAD ERROR: …`: Ordner fehlt, YAML nicht reparierbar, Typ nicht im Bundle). **Nichts geschrieben** | Meldung lesen. Betrifft sie den Dump (`Templates/…`): `python3 extractor/export out --source bundle` versuchen und es in h melden. Betrifft sie das Bundle: Extractor-Fehler, beheben. |
| 6  | Plausibilitätssperre: eine exportierte Datendatei ist leer oder hat weniger als 50 % der Einträge der Vorversion. **Nichts geschrieben** | Fast immer ein Ladefehler (Quelle, Warnungen ansehen). Nur wenn die Ursache belegt ist (Inhalt wirklich entfernt) und der Nutzer zustimmt: `--force`. |
| 7  | Überschreiben verweigert: Der Ordner existiert und ist nicht der neueste Export oder hat einen anderen bzw. keinen Steam-Build. **Nichts geschrieben** | Abbrechen und melden. `--overwrite` nur mit Zustimmung des Nutzers (ersetzt einen vorhandenen, evtl. committeten Ordner). |
| 12 | Steam-Update unvollständig | Abbrechen wie in Schritt a. `--force` nur auf ausdrücklichen Wunsch. |
| 1  | mit `--strict`: es gab Warnungen. Ohne `--strict`: unerwarteter Fehler (Traceback) | `--strict` im Runbook nicht benutzen (die bekannten Warnungen gibt es immer). Traceback: Extractor-Fehler, Ursache nennen und beheben. |

Optionen: `--source auto|yaml|bundle` (Template-Quelle, Standard `auto`, siehe Schritt d "Template-Quelle"), `--force`
(Steam-Update unvollständig oder Plausibilitätssperre übergehen, Warnung `sanity: … (exported with --force)`),
`--overwrite` (vorhandenen Ordner trotz Exit-Code 7 ersetzen). `--force` und `--overwrite` nie ohne Zustimmung.

- Die Konsole zeigt die Anzahlen und alle Warnungen. Sie stehen auch in `out/<neu>/manifest.json → warnings`.
- Neu pro Version: `out/<neu>/template_fields.json` (alle Feldpfade aller Template-Typen inkl. `AssemblyLineStages`).
  Damit bleibt festgehalten, welche Felder es in dieser Version gab, auch nachdem die Baseline (Schritt d) angepasst wurde.

### d. Neu-Erkennung: nichts stillschweigend ignorieren
Die Warnungen im Manifest durchgehen. Bekannte Warnungen in 0.6.0.26518: siehe [Stolpersteine](#stolpersteine).
Präfixe und was zu tun ist:

| Warnung | Bedeutung | Vorgehen |
|---|---|---|
| `new-template-type: X (n templates[, not exported])` | neuer Template-Typ | YAML ansehen (`ls "$(python3 extractor/export locate --field templatesDir)/X"`, 2 bis 3 Dateien lesen). Bei Spielinhalt (Items, Maschinen, Rezepte, Roboter, Forschung): Extractor erweitern. Sonst bewusst ignorieren und in `findings/schema.md` unter "Bewusst nicht exportiert" eintragen. |
| `unknown-field: Typ.feld (n templates), not read by the extractor` | neues Feld in einem **exportierten** Typ (oder in `AssemblyLineStages`) | Werte und Bedeutung klären (siehe "Unbekanntes Feld untersuchen"). Für Wiki/Calculator relevant (Zeit, Menge, Geschwindigkeit, Energie, Freischaltung)? Dann exportieren, sonst in `findings/schema.md` "Bewusst nicht exportiert" eintragen. |
| `unknown-field: Typ: a, b` | neue Felder in einem **nicht exportierten** Typ (gruppiert) | kurz ansehen; nur bei Spielinhalt handeln. |
| `unknown-field: AssemblyLineStages.…` | neuer Schlüssel in den dekodierten Odin-Stufen (Roboter-"Rezept") | **Wichtig:** könnte z. B. eine Zeit pro Aktion sein. Bedeutung in `decompiled/Main/AssemblyLineObjectTemplate.cs` (`AssemblyStage`, `AssemblyStageAction`) nachlesen; `findings/open_questions.md` Nr. 4 prüfen. |
| `removed-field: …` / `removed-template-type: …` | Feld oder Typ verschwunden | Liest der Extractor es? Dann gibt es meist einen Folgefehler. Ersatzfeld suchen. |
| `new-enum-value: Typ.feld = X (n templates)` | neuer Wert in einem Feld, nach dem `build.py` verzweigt (z. B. `BuildableObjectTemplate.type`, Item-/Forschungs-Flags) | Bedeutung im Enum nachlesen (dekompilieren, `grep -rn "enum <Name>" decompiled/Main`). Prüfen, ob `build.py` den Wert behandeln muss (z. B. neuer produzierender Maschinentyp ohne `crafting`). |
| `removed-enum-value: Typ.feld = X` | Wert kommt nicht mehr vor | Prüfen, ob `build.py` davon abhing. Meist harmlos. |
| `count-change: … ±x % vs <alt>` | Anzahl ändert sich um mehr als 20 % gegenüber der Vorversion | Plausibel (großes Content-Update) oder Ladefehler? In CHANGES.md (Schritt e) nachsehen. |
| `sanity: … (exported with --force)` | Plausibilitätssperre wurde mit `--force` übergangen | Nur nach Zustimmung (Schritt c). In h nennen. |
| `dll-types: …` | neue/entfernte Klassen in `Main.dll`/`Channel3.dll`/`Assembly-CSharp.dll` | Bei neuen `FoundryTemplate`-Unterklassen oder Klassen rund um Crafting/AssemblyLine/Research: dekompilieren (Anhang) und lesen. |
| `code-changed: <DLL> differs from <alt>` (Managed-DLL) | `Main.dll`, `Channel3.dll` oder `Assembly-CSharp.dll` hat sich geändert (Hash) | Dekompilieren (Anhang) und `python3 extractor/tools/check_code_constants.py decompiled/Main` (siehe g). |
| `code-changed: FoundryNative.dll differs from <alt>` | native Simulation geändert | Schritt g: `python3 extractor/tools/check_native_constants.py`. |
| `code-changed: X missing (present in <alt>)` / `code-changed: X is new` | Datei verschwunden bzw. neu gehasht | Verschwunden: Die Prüfungen, die sich darauf stützen, sind unbelegt (bei `FoundryNative.dll` alle nativen Formeln). Datei suchen (umbenannt/verschoben?), dem Nutzer melden, betroffene Punkte in g auf `neu messen`. |
| `source-mismatch: …` | Template-Dump und Bundle unterscheiden sich | siehe "Template-Quelle" unten |
| `source: Templates dump differs from foundry_main_bundle … - data taken from foundry_main_bundle` | Folge davon: Daten kommen aus dem Bundle | siehe "Template-Quelle" unten |
| `source: Templates dump differs …, but the bundle reader reported problems - data taken from the Templates dump` | Bundle-Leser hatte Probleme (`bundle:`-Warnungen), Dump wurde behalten | siehe "Template-Quelle" unten; Bundle-Leser reparieren. |
| `source: StreamingAssets/Templates missing\|incomplete (…) - … (fallback)` | Dump fehlt oder hat für einen exportierten Typ keine Dateien | Ergebnis gegen Vorversion besonders genau prüfen (Schritt e). In h melden. |
| `source: templates read from <Quelle> but baseline was taken from <Quelle>` | erscheint nur, wenn es Feldwarnungen gibt und die Baseline aus der anderen Quelle stammt | Feldwarnungen von Hand prüfen (in 0.6.0.26518 waren die Feldnamen beider Quellen gleich). |
| `source: Templates/<Typ>: n unquoted value(s) contain " #" …` | Wert enthält ` #` ohne Anführungszeichen; YAML schneidet den Rest ab | Bei exportiertem Typ: betroffene Zeilen ansehen (`grep -n ' #' "$(python3 extractor/export locate --field templatesDir)"/<Typ>/*.yaml`) und prüfen, ob ein exportierter Text abgeschnitten ist. Bekannt: `SkyPlatformUpgradeTemplate` (nicht exportiert). |
| `source: Templates/<Typ>/<Datei> line n is not valid YAML …` | Dump-Fehler, repariert gelesen | Bekannt: 2× `PlanetTemplate`. Neue Fälle melden. |
| `source: cannot scan <Typ>: …` | Typ nicht lesbar (nicht exportierter Typ; exportierte Typen brechen mit Exit-Code 5 ab) | Ursache nennen; für Felder dieses Typs gibt es keine Prüfung. |
| `source: Steam update pending …` | nur mit `--force` | Export wiederholen, wenn Steam fertig ist. |
| `bundle: …` | nur Bundle-Weg: unbekannter Enum-Wert, Feld ohne Typinfo, DLLs fehlen | Dekompilieren; `export baseline` erneuert `data/managed_types.json`. |
| `baseline: …` | Baseline fehlt oder ohne `enumValues` | Prüfungen wurden übersprungen. Baseline erzeugen (unten). |
| ohne Präfix (z. B. `recipe X: no machine accepts tags`, `machine X / recipe Y: no rate …`, `recipe X: output Y has no percentage_str - chance taken as 1`, `assembly line: expected exactly one producer speed / start power / start speed …`) | Konsistenzhinweis | Neu gegenüber der Vorversion? Dann Ursache klären (Template-Werte ansehen). Bekannte siehe Stolpersteine. |

Nur wenn eine der Warnungen oben es verlangt oder die Bedeutung eines Felds/Werts unklar bleibt: **dekompilieren** und/oder
**AssetRipper-Export erneuern** (Anhang). Der Extractor braucht beides nicht. Beides dient nur der Analyse.

#### Template-Quelle (`--source auto`, Standard)
Das Spiel lädt nur `foundry_main_bundle`. Der Dump `StreamingAssets/Templates` ist ein Entwickler-Artefakt (siehe Stolpersteine).
Jeder Export vergleicht beide für die 9 exportierten Typen:
- Dump vollständig und gleich: Daten aus dem Dump (`templateSource: StreamingAssets/Templates`).
- Dump fehlt oder hat für einen exportierten Typ keine Dateien: Daten aus dem Bundle, Warnung `source: … (fallback)`.
- Dump ≠ Bundle: Zeilen `source-mismatch: <Typ>: …` (mit Beispiel `dump X vs bundle Y`), Daten aus dem **Bundle**, weil das
  Spiel es lädt. CHANGES.md beginnt dann mit einem "Hinweis zur Template-Quelle". Ausnahme: Meldet der Bundle-Leser
  Probleme (`bundle:`-Warnungen) oder scheitert der Vergleich, bleibt der Dump die Quelle (Warnung sagt das).

Bei `source-mismatch:` prüfen und in h melden:
1. Richtung: `only in Templates dump` (der Dump hat Inhalte, die das Spiel nicht lädt, z. B. unveröffentlichte) oder
   `only in foundry_main_bundle` / abweichende Werte (Dump veraltet). In beiden Fällen gilt das Bundle.
2. Gibt es `bundle:`-Warnungen? Dann sind die Bundle-Werte selbst fraglich (Bundle-Leser prüfen), und die Daten kamen aus dem Dump.
3. Einzelwerte ansehen (Typ und Identifier aus der Warnung; ca. 4 s; zeigt nur abweichende Felder):
   ```
   PYTHONPATH=extractor python3 -c "import sys,json;from foundry_export.cli import _find;from foundry_export.sources import YamlTemplateSource,BundleTemplateSource,_norm;T,I=sys.argv[1:3];gp=_find(None)[1];a,b=(_norm(s.load(T).get(I,{})) for s in (YamlTemplateSource(gp.templates,[]),BundleTemplateSource(gp,[])));[print(k,'| dump:',json.dumps(a.get(k,'<missing>'),default=str)[:150],'| bundle:',json.dumps(b.get(k,'<missing>'),default=str)[:150]) for k in sorted(set(a)|set(b)) if a.get(k,'<missing>')!=b.get(k,'<missing>')];print('dump',len(a),'fields, bundle',len(b),'fields')" <Typ> <identifier>
   ```
   Beispiel-Ausgabe: `powerCost_kj_str | dump: 600 | bundle: 500`. `dump 0 fields` = Template fehlt im Dump.
4. Folgen: CHANGES.md und Referenzwerte (Schritt f) richten sich nach dem Bundle. Die Tests, die Dump und Bundle vergleichen,
   schlagen fehl, solange beide verschieden sind (Schritt f). Das ist erwartet und wird gemeldet, nicht "repariert".

Quelle erzwingen: `python3 extractor/export out --source bundle` bzw. `--source yaml` (bricht mit Exit-Code 5 ab, wenn der Dump
fehlt oder unvollständig ist). Ein erneuter Export mit anderer Quelle ersetzt nur den neuen Ordner. `export baseline` nutzt
dieselbe Quellenwahl (`--source` gibt es dort auch).

#### Unbekanntes Feld untersuchen
```
grep -h "^    <feld>:" "$(python3 extractor/export locate --field templatesDir)"/<Typ>/*.yaml | sort | uniq -c | sort -rn | head
```
(Felder der obersten Ebene sind im Dump mit 4 Leerzeichen eingerückt; bei verschachtelten Pfaden wie `a.b` oder `a[].b` den
letzten Namen `b` ohne `^    ` greppen.) Bleibt die Bedeutung unklar (z. B. ein Faktor, der überall gleich ist): dekompilieren
(Anhang) und die Verwendung im Code suchen. Der YAML-Schlüssel ist der C#-Feldname:
```
grep -rn "<feld>" decompiled/Main --include=*.cs | head -20
```
Ergebnis mit Beleg (Datei + Klasse/Methode) in `findings/schema.md` eintragen: exportiert (Feldtabelle) oder
"Bewusst nicht exportiert" (mit Grund). Ist die Wirkung nur nativ, in `findings/open_questions.md` aufnehmen.

#### Erweitern statt ignorieren
Neues Feld in `extractor/foundry_export/build.py` übernehmen, das Schema in `schemas.py` anpassen
(`python3 extractor/export schemas` schreibt die JSON-Schemas neu), die Beschreibung in `findings/schema.md` ergänzen (mit Beleg),
bei Bedarf einen Referenzwert in `extractor/tests/reference_values.json` hinzufügen. Danach erneut exportieren (Schritt c).
Das ersetzt nur den neuen Versionsordner (er ist der neueste Export mit gleichem Build).

#### Baseline (bei **jeder** neuen Version, nach der Prüfung)
Die Baseline dokumentiert "diese Template-Felder, Enum-Werte und DLL-Klassen wurden angesehen". Sie wird bei **jeder** neuen
Version gesetzt, auch ohne Warnungen, sobald alle Warnungen oben angesehen und entschieden sind. Sonst schlagen in Schritt f
die Baseline-Tests fehl (`test_current_game_matches_committed_baseline`, `test_baseline_matches_installed_game`).
Vorher die Warnungsliste sichern, denn nach Baseline und erneutem Export fehlen die erledigten Warnungen im Manifest:
```
python3 -c "import json,sys;print(chr(10).join(json.load(open(sys.argv[1]))['warnings']))" out/<neu>/manifest.json > /tmp/fx_warnings_before_baseline.txt
python3 extractor/export baseline      # schreibt baseline/known_templates.json (Typen, Felder, enumValues, AssemblyLineStages),
                                       # baseline/dll_types.txt und data/managed_types.json; listet alles als "accepted:"
python3 extractor/export out           # erneut exportieren, damit das Manifest die erledigten Warnungen nicht mehr enthält
```
Die Baseline nie blind aktualisieren. Was nach der Baseline von der Neuheit übrig bleibt: `out/<neu>/template_fields.json`
(Feldliste dieser Version) und in `out/<neu>/CHANGES.md` der Abschnitt "Template-Felder" (neue/entfernte Feldpfade je Typ
gegenüber der Vorversion). Hat die Vorversion noch keine `template_fields.json`, steht dort "nicht bestimmbar"; dann die
`unknown-field:`-Zeilen aus der gesicherten Liste in `findings/schema.md` festhalten (exportiert oder "Bewusst nicht exportiert",
mit Version). Die gesicherte Warnungsliste geht in die Zusammenfassung (Schritt h).

### e. Änderungen gegenüber der Vorversion
`out/<neu>/CHANGES.md` hat der Export geschrieben (nach jedem erneuten Export in d wieder). Von Hand:
```
python3 extractor/export diff out/<alt> out/<neu>        # schreibt out/<neu>/CHANGES.md
```
CHANGES.md enthält: Kopf mit Version/Build/Template-Quelle, ggf. "Hinweis zur Template-Quelle" (Rückfall oder Dump ≠ Bundle),
Übersicht, neue/entfernte/geänderte Items, Rezepte, Maschinen und Gebäude, Forschungen, Erkundungs-Freischaltungen,
Assembly-Line-Roboter, -Stufen, -Aktionen und -Maschinen (Werte alt → neu), neue Template-Typen, "Template-Felder",
"Lokalisierung", Warnungen (neu/entfallen; zählen nicht als Datenänderung) und das Ergebnis.
Durchlesen und auf Unplausibles achten, z. B. massenhaft entfernte Einträge (deutet auf einen Ladefehler hin, nicht auf ein Spiel-Update).

- **Assembly-Line-Aktionen** heißen in CHANGES.md `<Roboter> / <Aktion im Stufenbaum>` (z. B. `_base_droid01 / _weld_head`),
  dahinter in Klammern der Identifier der Producer-Aktion (ALPA, z. B. `_d01_weldHead`). Warnungen, Templates
  (`AssemblyLineProducerActionTemplate`) und `localization → assemblyLineActions` benutzen nur den ALPA-Identifier.
  Zuordnung: `assembly_line.json → objects[].stages[].actions[].producerAction.identifier`, als Liste:
  ```
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));[print(o['identifier'],'/',a['identifier'],'->',(a.get('producerAction') or {}).get('identifier')) for o in d['objects'] for s in o['stages'] for a in s['actions']]" out/<neu>/assembly_line.json
  ```
- **Lokalisierung:** Neue Einträge ohne deutschen bzw. englischen Namen listet CHANGES.md unter "Lokalisierung". Direkt nach
  einem Patch fehlen Übersetzungen oft noch. Kein Fehler des Exports, aber in h erwähnen (Wiki zeigt sonst englischen Text).
- **Hinweis zur Template-Quelle:** Steht er oben in CHANGES.md, in h ausdrücklich sagen, aus welcher Quelle die Daten stammen.

### f. Tests
```
FOUNDRY_REQUIRE_GAME=1 python3 -m unittest discover -s extractor/tests -v
```
Dauer ca. 35 bis 60 s. Die Tests finden das Spiel wie der Extractor. Mit `FOUNDRY_REQUIRE_GAME=1` schlagen Tests, die das
Spiel brauchen, fehl statt still übersprungen zu werden, wenn das Spiel nicht gefunden wird (ein gesetztes, aber ungültiges
`FOUNDRY_GAME_DIR` lässt sie immer fehlschlagen). Die Tests umfassen: Doppel-Export byte-gleich (außer Zeitstempel), Schema-Validierung
jeder Datei samt sha256 im Manifest, festgenagelte Referenzwerte (`extractor/tests/reference_values.json`), Bundle-Rückfall,
Abgleich Dump ↔ Bundle, Steam-Ordnersuche, Diff, Feld/Typ/Enum-Prüfung, DLL-Klassenliste, native Konstanten.
`FOUNDRY_SKIP_SLOW=1` überspringt die langsamen Tests. Beim Update nicht setzen.
Ergebnis wörtlich berichten (Anzahl, `OK`/`FAILED (failures=…, errors=…)`). Bei Fehlschlag die Ursache nennen:
- **Baseline-Tests** (`test_current_game_matches_committed_baseline`, `test_baseline_matches_installed_game`,
  `test_committed_table_is_current`): `export baseline` aus Schritt d fehlt oder wurde vor einem Extractor-Umbau gesetzt.
- **Dump ↔ Bundle** (`test_type_names`, `test_nine_types_equal`, `test_all_types_identifiers_and_fields`,
  `FakeGameExportTests.test_c_*`): erwartet bei `source-mismatch:` bzw. fehlendem Dump. Melden, nicht anpassen.
- **Bekannte Warnungen** (`test_known_warnings_only`): auf die 5 Warnungen von 0.6.0.26518 festgenagelt, läuft nur bei dieser
  Version (sonst übersprungen). Schlägt er fehl, ist bei gleicher Version eine neue Warnung entstanden: Ursache nennen.
- **Baselines uneinheitlich** (`test_committed_baselines_agree`): `export baseline` lief nicht vollständig durch.
- **Neuer Template-Typ** (`test_templates_cover_template_folders`): Typ im Dump, aber keine `FoundryTemplate`-Unterklasse
  in den DLLs (oder umgekehrt). Ursache klären.
- **Referenzwert weicht ab** (`test_reference_values`): CHANGES.md prüfen. Maßgeblich ist der Wert, den das Spiel lädt (bei
  `source-mismatch:` der Bundle-Wert, siehe d). Hat das Spiel den Wert geändert: Referenzwert anpassen (Notiz, `pinnedAt` setzen)
  und in h erwähnen. Ist es ein Extractor-Fehler: beheben.
- **Native Konstanten** (`test_native_constants.GameTests`): wie `check_native_constants.py` in Schritt g.
- **Doppel-Export ungleich:** Nichtdeterminismus (Sortierung, Set-Reihenfolge, Zeit) im Extractor. Beheben.
- **`test_committed_latest_is_reproducible`:** Der Extractor wurde geändert, aber `out/<latest>` ist noch alt. Neu exportieren.
- **`test_finds_installed_game` / `test_steam_libraries_find_the_game`:** Spielordner-Suche (Steam-Bibliotheken,
  `libraryfolders.vdf`). Liegt das Spiel außerhalb einer registrierten Bibliothek (nur über `FOUNDRY_GAME_DIR`/`game_path.txt`
  gefunden), wird der zweite Test übersprungen. Ein Fehlschlag ist ein Fehler in `steam.py` oder eine kaputte Steam-Konfiguration.

### g. Offene Punkte prüfen
`findings/open_questions.md` lesen. Die Simulation läuft in `foundry_Data/Plugins/x86_64/FoundryNative.dll`, die UI-Formeln in `Main.dll`.

**Native Prüfung** (immer laufen lassen, ca. 0,1 s, nur lesend; Pflicht bei `code-changed: FoundryNative.dll`):
```
python3 extractor/tools/check_native_constants.py                      # 16 Prüfungen über die mitgelieferte FoundryNative.pdb
python3 extractor/tools/check_native_constants.py --find AL_StartEntity::   # Funktionen suchen (Name enthält Text; nach Umbenennung)
python3 extractor/tools/check_native_constants.py --disasm             # objdump-Kontext zu jedem Treffer
```
Exit-Code 0 = alles `OK`, 1 = `MISMATCH`/`NOT FOUND`, 2 = DLL/PDB fehlt, 3 = Spiel nicht gefunden.
- `MISMATCH`/`NOT FOUND`: Funktion mit `--find <Name>` suchen (umbenannt?), mit `--disasm` bzw. von Hand disassemblieren
  (Vorgehen in `findings/verification.md`), `build.py` anpassen, betroffene Punkte auf `neu messen`.
- Die Zeilen `function present` zeigen die **Funktionsgröße in Bytes**. Mit der Tabelle "Native Funktionsgrößen" in
  `findings/verification.md` vergleichen. Weicht eine Größe ab, hat sich der Code der Funktion geändert, auch wenn die
  Prüfung `OK` sagt: Funktion mit `--disasm` ansehen und die zugehörigen Punkte (Tabelle unten) auf `neu messen` setzen.
  Die Größen der übrigen Funktionen aus der Tabelle (Spalte "Ausgabe: `--find`"):
  ```
  for n in CraftingAction::reinitialize ProducerEntity::tryStartProduction AutoProducerEntity::tryStartProduction ModularProducerEntity::tryStartProduction BaseStationEntity::BaseStationFurnace::tickUpdate; do python3 extractor/tools/check_native_constants.py --find "$n" | grep "^$n @" | cut -d'(' -f1; done
  ```
  (`CraftingAction::reinitialize` erscheint zweimal; maßgeblich ist die Überladung mit `recipe`, in 0.6.0.26518 1006 Bytes.)
  Neue Größen nach der Prüfung in die Tabelle in `findings/verification.md` eintragen (mit Version).
- `PDB … not found`: Das Spiel liefert keine Symbole mehr. Dann lassen sich die nativen Aussagen nur von Hand prüfen. Melden.

**Managed-Code** (bei `code-changed: Main.dll`): dekompilieren (Anhang) und `python3 extractor/tools/check_code_constants.py decompiled/Main`.

**Zuordnung Änderung → Punkt in `open_questions.md`:**

| Auslöser (Warnung aus c, Abschnitt in CHANGES.md) | Punkte |
|---|---|
| `code-changed: FoundryNative.dll`, Größenänderung von `CraftingAction::reinitialize` / `CraftingQueue::tickUpdate` | 1, 2 |
| Größenänderung `ProducerEntity`/`AutoProducerEntity`/`ModularProducerEntity::tryStartProduction` | 3, 10, 11 |
| Größenänderung `AL_ProducerEntity::tickUpdate`, `AL_StartEntity::tickUpdate` | 4, 7 |
| Größenänderung `AL_ProducerEntity::recalculatePainterCosts`, `AL_EndConsumerEntity::alcm_validateItemForConsumption`, `AL_Item::processPainting` | 5 |
| Größenänderung `AL_Item::_isReadyForActionIterativeCheck` | 6 |
| `code-changed: Main.dll` | 1 (Tooltip), 2, 12, 13 |
| Rezepte `_base_science_pack_i`, `_base_conveyor_i` (`timeMs`, Zutaten) | 1, 2, 10, 11 |
| Erkundungs-Freischaltungen `_base_character_crafting_speed_*` (`characterCraftingSpeedBonusPercent`) | 2 |
| Maschine `_base_casting_building_base` (`crafting.speedMultiplier`, `itemSlots`), Rezept `_base_xf_plates_t3`, neue `modularProducer_*`-Felder | 3 |
| Assembly-Line-Maschinen (`speedSlotsPerTick`, `powerPerActionKJ`), Konstanten, Roboter `derived.singleStartObjectsPerMinute`/`maxObjectsPerMinute`, `unknown-field:` bei `AssemblyLineStages`, `AssemblyLineProducerActionTemplate` oder `al_*` | 4 |
| Roboter `parts[].paintingPowerKJ`, `derived.painterPowerKJ`, Painter `_base_al_painter_i` | 5 |
| Assembly-Line-Aktionen (`parentAction`, Reihenfolge), Stufen | 6 |
| Assembly-Line-Aktionen `producerAction.powerKJ`, Start `powerPerActionKJ` | 7 |
| Endverbraucher `_base_al_end_consumer_i` (`endConsumerSlotCount`) | 8 |
| Forschung `_base_data_cable` (`secondsPerScienceItem`, `cost`) | 9 |
| Item `_base_robot_01`, `unknown-field:`/Template-Felder `workstationItem_*` | 10 |
| Maschinen `item`, `name`, `itemAlternatives` | 12 |
| Items `fuel`, Flag `BURNABLE` | 13 |
| Base Station `_base_baseStation01`, Rezepte `_base_*_t1_primitive` (`timeMs`), Größenänderung `BaseStationEntity::BaseStationFurnace::tickUpdate` | 14 |

Ändert sich etwas davon: **ausdrücklich darauf hinweisen**, in `open_questions.md` den Status auf `neu messen` setzen.
Bereits gemessene Werte gelten nur für die Version in der Spalte "gemessen am".

### h. Zusammenfassung an den Nutzer (höchstens 15 Zeilen)
Inhalt: Version alt → neu (Build), Template-Quelle (bei `source-mismatch:`/Rückfall ausdrücklich), was ist neu, was hat sich
geändert (die wichtigsten Zahlen aus CHANGES.md), welche Warnungen (aus `/tmp/fx_warnings_before_baseline.txt`, und was damit
gemacht wurde), fehlende Übersetzungen neuer Einträge, Teststatus (wörtlich), was im Spiel nachzumessen ist (aus g), welche
Dateien geändert wurden, ggf. "Ausgangsstand war nicht committet" (Schritt b) und die Entscheidung (A)/(B) bei einem `-b`-Ordner (Schritt a).
**Nichts committen, pushen oder veröffentlichen.** Auf Zustimmung warten.

### i. Nach Zustimmung: Commit
```
git status --porcelain --untracked-files=all          # prüfen: keine DLLs, PDBs, Texturen, raw/, decompiled/
git add out/ findings/ extractor/ UPDATE.md .gitignore setup.py inventory_assets.py
git diff --cached --name-only | grep -vE '\.(json|md|py|txt)$|^\.gitignore$|^extractor/export$'   # muss leer sein
git commit -m "Export FOUNDRY <Version> (Steam-Build <Build>): <Kurzfassung>"
```
`git add -A` ist ebenso in Ordnung, wenn `git status` vorher nur Dateien aus der Liste oben zeigt (`.gitignore` schließt
Spieldateien, `raw/` und `decompiled/` aus). **Push nur, wenn der Nutzer ihn ausdrücklich verlangt.**

---

## Anhang: Befehle

### Spielordner finden
```
python3 extractor/export locate                       # JSON: gameDir, gameVersion, steamBuildId, steamBranch, source, manifest,
                                                      # library, stateFlags, updatePending, templatesDump, templatesDir, alternatives
python3 extractor/export locate --field templatesDir  # ein Feld
python3 extractor/export locate --game <Pfad>         # Pfad erzwingen (auch für alle anderen Befehle: --game)
FOUNDRY_GAME_DIR=<Pfad> python3 extractor/export check --out out
```
Suchreihenfolge: `--game` bzw. Positionsargument, dann `FOUNDRY_GAME_DIR`, dann alle Steam-Bibliotheken, zuletzt `game_path.txt`.
Ein ungültiger expliziter Pfad bricht ab (Exit-Code 3), es gibt keinen stillen Rückfall.
Steam-Bibliotheken: `~/.local/share/Steam`, `~/.steam/steam`, Flatpak `~/.var/app/com.valvesoftware.Steam/.local/share/Steam`,
Snap, macOS, Windows (Registry). Jeweils alle Einträge aus `steamapps/libraryfolders.vdf`.
Gesucht wird `steamapps/appmanifest_983870.acf`, der Ordner ist dann `steamapps/common/<installdir>`.
Von Hand: `grep -A2 '"path"' ~/.local/share/Steam/steamapps/libraryfolders.vdf` und in jeder Bibliothek `ls <lib>/steamapps/appmanifest_983870.acf`.

### Extractor
```
python3 extractor/export check  [--game <Pfad>] [--out out]                 # Schritt a, Exit-Codes siehe dort
python3 extractor/export [<Spielordner>] out [--source auto|yaml|bundle] [--force] [--overwrite] [--strict]
                                                                            # Export (Schritt c); ohne Spielordner: automatisch suchen
python3 extractor/export verify out/<Version>                               # sha256 (Daten + schemas/) gegen manifest.json
python3 extractor/export diff out/<alt> out/<neu> [--out FILE]              # CHANGES.md; erste Version: diff none out/<neu>
python3 extractor/export baseline [--game <Pfad>] [--source auto|yaml|bundle]   # geprüften Stand übernehmen (Schritt d)
python3 extractor/export schemas                                            # JSON-Schemas aus schemas.py neu schreiben
```
Voraussetzungen: Python ≥ 3.10, PyYAML (`pip install pyyaml`). Sonst nichts. `decompiled/` und `raw/` braucht der Export nicht.

### Tests
```
FOUNDRY_REQUIRE_GAME=1 python3 -m unittest discover -s extractor/tests -v   # alles, ca. 35-60 s (Schritt f)
FOUNDRY_SKIP_SLOW=1 python3 -m unittest discover -s extractor/tests -v      # ohne die langsamen Tests (nicht beim Update)
python3 -m pytest extractor/tests -q                                        # alternativ, falls pytest installiert ist
```

### Dekompilieren (nur bei Bedarf, Schritt d/g)
ilspycmd 8.2 liegt in `~/.dotnet/tools/ilspycmd` (nicht im PATH). Ohne `DOTNET_ROLL_FORWARD=Major` startet es nicht
(.NET-6-Tool, installiert ist nur .NET 8), ohne `DOTNET_ROOT="$HOME/.dotnet"` findet es die Runtime nicht (die System-.NET-Installation
ist unvollständig; `DOTNET_ROOT` kommt sonst nur aus der systemd-Benutzerumgebung, die SSH/cron nicht haben).
```
GAME="$(python3 extractor/export locate --field gameDir)"
rm -rf decompiled.prev && { [ ! -d decompiled ] || mv decompiled decompiled.prev; }   # Vorversion zum Vergleichen (gitignored, lokal)
for dll in Main Channel3 Assembly-CSharp ThirdParty; do
  DOTNET_ROOT="$HOME/.dotnet" DOTNET_ROLL_FORWARD=Major ~/.dotnet/tools/ilspycmd -p -o "decompiled/$dll" "$GAME/foundry_Data/Managed/$dll.dll" || echo "FEHLER: $dll"
done
diff -rq decompiled.prev/Main decompiled/Main | head -50     # welche Klassen haben sich geändert?
python3 extractor/tools/check_code_constants.py decompiled/Main
```
Die Meldung "You are not using the latest version of the tool" von ilspycmd ist harmlos.
Alternativ `rm -rf decompiled.prev && mv decompiled decompiled.prev && python3 setup.py "$GAME"` (setup.py überspringt vorhandene
Ordner und endet mit Exit-Code 1, wenn eine DLL nicht dekompiliert werden konnte).
Die wichtige Assembly ist **`Main.dll`**, nicht `Assembly-CSharp.dll`. Ist `foundry_Data/Managed/` leer und liegt `GameAssembly.dll`
im Spielordner, ist das Spiel auf IL2CPP umgestellt. Dann hilft ilspycmd nicht mehr (Il2CppDumper nötig), und dem Nutzer Bescheid geben.

### AssetRipper-Export erneuern (nur bei Bedarf)
AssetRipper 2.0 (Free) liegt in `~/Tools/AssetRipper/`. Der Export dauert ca. 4 Minuten, braucht ca. 8 GB RAM und 8 GB Platz.
Er ist nur nötig für Assets, die nicht im Template-Dump stehen (z. B. Odin-Assets, Prefabs).
Den Block **in einem einzigen Shell-Aufruf** ausführen (Variablen und Hintergrundprozess gelten nur darin):
```
REPO="$PWD"
GAME="$(python3 extractor/export locate --field gameDir)"
rm -rf raw.prev && { [ ! -d raw ] || mv raw raw.prev; }          # Vorversion behalten (gitignored); später löschen
(cd ~/Tools/AssetRipper && exec ./AssetRipper.GUI.Free --headless --port 8765) > /tmp/assetripper_stdout.log 2>&1 &
AR_PID=$!
for i in $(seq 60); do curl -fs -o /dev/null http://127.0.0.1:8765/ && break; sleep 1; done
LOG="$(ls -t ~/Tools/AssetRipper/AssetRipper_*.log | head -1)"
curl -fsS -o /dev/null -X POST --data-urlencode "Path=$GAME" http://127.0.0.1:8765/LoadFolder
curl -fsS -o /dev/null -X POST --data-urlencode "Path=$REPO/raw" http://127.0.0.1:8765/Export/UnityProject
for i in $(seq 120); do tail -n 1 "$LOG" | grep -q "Finished post-export" && break; sleep 5; done
tail -n 1 "$LOG"                                                 # erwartet: "Export : Finished post-export"
kill "$AR_PID"; wait "$AR_PID" 2>/dev/null
kill -0 "$AR_PID" 2>/dev/null && echo "AssetRipper läuft noch: kill $AR_PID" || echo "AssetRipper beendet"
```
Klappt das Formular nicht: `http://127.0.0.1:8765/` im Browser öffnen (File → Open Folder, Export → Export All Files),
oder `http://127.0.0.1:8765/openapi.json` ansehen. Danach mit `pgrep -af AssetRipper.GUI` prüfen, dass keine Instanz übrig ist.
Inventar der ScriptableObject-Typen: `python3 inventory_assets.py raw --out inventory.txt`.

---

## Stolpersteine

- **Template-Dump ist ein Entwickler-Artefakt** (`StreamingAssets/Templates`): geschrieben vom Editor-Werkzeug `TemplateExporter`,
  das Spiel liest ihn nie (`TweakManager` liest nur Mod-Tweaks). Er enthält nur Templates mit `includeInBuild && includeIngame`
  und kann in einem Patch veralten. Deshalb vergleicht jeder Export ihn mit dem Bundle und nimmt bei Abweichung das Bundle (Schritt d).
  Fehlt er, liest der Extractor die Templates aus dem Bundle (TypeTrees, eigene LZ4-Implementierung, ca. 4 s statt 6 s).
  Enum-Namen kommen dann aus den DLLs bzw. `extractor/foundry_export/data/managed_types.json`.
- **Odin-Binärformat bei den Assembly-Line-Stufen:** `AssemblyLineStages` ist ein `SerializedScriptableObject`. Die Stufen stehen
  als Odin-Binärdaten (`serializationData.SerializedBytes`, `SerializedFormat: 0`) im Asset. Sie sind **nicht** im YAML-Dump enthalten.
  Der Extractor liest sie direkt aus `foundry_main_bundle` und dekodiert sie mit `foundry_export/odin_binary.py`. Ihre Feldpfade
  prüft er wie einen Template-Typ (Pseudo-Typ `AssemblyLineStages`).
  Wechselt das Format (1 = JSON, 2 = Nodes) oder kommt ein unbekannter Eintragstyp vor, bricht der Export mit einer Meldung ab. Dann den Decoder erweitern.
- **Stage-Titel sind nicht lokalisiert** (`PoMgr` überspringt `AssemblyLineStages`). Sie stehen nur englisch im Export. Das ist kein Fehler.
- **Bundle-Kompression:** Unterstützt wird nur LZ4/LZ4HC und unkomprimiert. Stellt das Spiel auf LZMA um, bricht der Export ab
  (`NotImplementedError: bundle compression type`).
- **Simulation ist nativ** (`FoundryNative`): Zeit pro Assembly-Line-Aktion, PCM-Ladegeschwindigkeit, Handwerks-Simulation und Modul-Effekte
  stehen nicht in C# und nicht in den Assets. Darum gibt es `findings/open_questions.md` mit Mess-Anleitungen und `check_native_constants.py`.
- **Festkomma:** numerische `*_str`-Felder sind Dezimal-Strings mit Faktor 10000 im Spiel. Mengen in `requiredElements` der ALPA sind ganzzahlig ×10000 gespeichert (`/10000`).
- **Infobox-Texte** (`_infoBox` in Rezepten) sind vom Editor erzeugter Text, keine Quelle. Werte immer aus den Feldern.
- **Steam-Build ohne neue `version.txt`:** eigener Ordner `v<Version>-b<Build>`. Keinen alten Ordner überschreiben (Schritt a).
- **Bekannte Warnungen in 0.6.0.26518** (5, erklärt, kein Handlungsbedarf, solange sie unverändert bleiben):
  - `recipes use undefined crafting tag base_station` (die Base Station wählt ihre Rezepte über `baseStation_craftingRecipeIdentifier`),
  - `recipe _base_pipe_adapter: no machine accepts tags ['character']` (Rezept im Handwerk versteckt, sonst nirgends herstellbar),
  - 2× `source: Templates/PlanetTemplate/… is not valid YAML` (Dump-Fehler `planetInfo: -`, wird repariert gelesen),
  - `source: Templates/SkyPlatformUpgradeTemplate: 11 unquoted value(s) contain " #" …` (Namen wie `Install Fuel Tank #3`;
    Typ wird nicht exportiert).

  Mit `--source bundle` (oder wenn das Bundle wegen `source-mismatch:` gewählt wurde) entfallen die drei `source: Templates/…`-Warnungen.
- Tests und Export brauchen das installierte Spiel. Auf anderen Rechnern `FOUNDRY_GAME_DIR` setzen.
