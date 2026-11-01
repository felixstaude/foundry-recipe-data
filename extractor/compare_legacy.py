#!/usr/bin/env python3
"""Compare a foundry-data v1 export with the legacy foundry-recipe-data set.

    python3 extractor/compare_legacy.py <legacy-version-dir> <new-version-dir> [--out report.md]

legacy-version-dir: e.g. a checkout of github.com/felixstaude/foundry-recipe-data/v0.6.0.24200
new-version-dir:    e.g. out/v0.6.0.26518
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foundry_export.build import CHARACTER_SPEED  # noqa: E402  (hand crafting: simulation timeMs / 3)


def load(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def fmt_io(lst, key='identifier'):
    return ', '.join(f'{e["amount"]}× {e[key]}' for e in lst) or '–'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('legacy'); ap.add_argument('new'); ap.add_argument('--out')
    a = ap.parse_args()
    L, N = Path(a.legacy), Path(a.new)
    old = {r['identifier']: r for r in load(L / 'recipes_clean.json')['recipes']}
    new = {r['identifier']: r for r in load(N / 'recipes.json')['recipes']}
    old_tags = {t['identifier']: t for t in load(L / 'tags.json')['tags']}
    new_tags = {t['identifier']: t for t in load(N / 'crafting_tags.json')['tags']}
    old_machines = load(L / 'machines.json')['machines']
    new_machines = {m['identifier']: m for m in load(N / 'machines.json')['machines']}
    al = load(N / 'assembly_line.json')
    new_ver = load(N / 'manifest.json')['gameVersion']
    old_ver = L.name

    out = []
    w = out.append
    w(f'# Vergleich mit dem alten Datensatz ({old_ver} → v{new_ver})\n')
    w('Erzeugt von `extractor/compare_legacy.py`. Achtung: Die Sätze stammen aus **verschiedenen Spielversionen**. '
      'Unterschiede bei Rezeptinhalten (Zeit, Zutaten, neue/entfernte Rezepte) können Spiel-Patches sein. '
      'Unterschiede bei Geschwindigkeiten, Raten, Fluiden und Maschinen kommen von der **Methode** '
      '(alt: aus `_infoBox`-Tooltiptexten geraten; neu: aus den Maschinen-Assets).\n')

    # ---- recipe sets
    only_new, only_old = sorted(set(new) - set(old)), sorted(set(old) - set(new))
    w('## 1. Rezeptmenge\n')
    w(f'- alt: {len(old)} Rezepte, neu: {len(new)} Rezepte, gemeinsam: {len(set(old) & set(new))}')
    w(f'- nur neu: {len(only_new)}, nur alt: {len(only_old)}\n')
    if only_new:
        by_tag = defaultdict(list)
        for i in only_new:
            by_tag[', '.join(new[i]['tags'])].append(i)
        w('### Nur im neuen Export\n')
        w('| Tags | Anzahl | Rezepte |\n|---|---|---|')
        for t, ids in sorted(by_tag.items()):
            w(f'| {t} | {len(ids)} | {", ".join(f"`{x}`" for x in ids)} |')
        w('')
        with_fluid = [i for i in only_new if new[i]['fluidInputs'] or new[i]['fluidOutputs']]
        w(f'{len(with_fluid)} davon haben Fluid-Ein- oder -Ausgaben. Der alte Datensatz kennt keine Fluide; '
          'ob er solche Rezepte bewusst verworfen hat oder ob sie in 0.6.0.24200 fehlten, lässt sich ohne die alten '
          'Spieldateien nicht unterscheiden.\n')
    if only_old:
        w('### Nur im alten Datensatz\n')
        for i in only_old:
            w(f'- `{i}` ({old[i]["name"]}, Tags {old[i]["tags"]})')
        w('')

    # ---- per recipe content
    diffs = defaultdict(list)
    for i in sorted(set(old) & set(new)):
        o, n = old[i], new[i]
        if o['name'] != n['name']:
            diffs['name'].append((i, o['name'], n['name']))
        if o['timeMs'] != n['timeMs']:
            diffs['timeMs'].append((i, o['timeMs'], n['timeMs']))
        oi = sorted((e['identifier'], e['amount']) for e in o['inputs'])
        ni = sorted((e['item'], e['amount']) for e in n['inputs'])
        if oi != ni:
            diffs['inputs'].append((i, fmt_io(o['inputs']), fmt_io(n['inputs'], 'item')))
        oo = sorted((e['identifier'], e['amount']) for e in o['outputs'])
        no = sorted((e['item'], e['amount']) for e in n['outputs'])
        if oo != no:
            diffs['outputs'].append((i, fmt_io(o['outputs']), fmt_io(n['outputs'], 'item')))
        if sorted(o['tags']) != sorted(n['tags']):
            diffs['tags'].append((i, o['tags'], n['tags']))
        if n['fluidInputs'] or n['fluidOutputs']:
            diffs['fluids'].append((i, '–', '; '.join([f'in {e["liters"]} L {e["element"]}' for e in n['fluidInputs']] +
                                                    [f'out {e["liters"]} L {e["element"]}' for e in n['fluidOutputs']])))
        chances = [e for e in n['outputs'] if e['chance'] != 1]
        if chances:
            oldrate = {e['identifier']: e['perMin'] for e in o['rates_per_min_speed1']['outputs']}
            base = 60000.0 / n['timeMs']
            for e in chances:
                diffs['chance'].append((i, f'{oldrate.get(e["item"])} /min (ohne Chance)',
                                        f'{round(e["amount"] * e["chance"] * base, 4)} /min (Chance {e["chance"]})'))
    w('## 2. Inhalt gemeinsamer Rezepte\n')
    labels = {'name': 'Name', 'timeMs': 'timeMs', 'inputs': 'Item-Eingaben', 'outputs': 'Item-Ausgaben',
              'tags': 'Tags', 'fluids': 'Fluide (fehlen im alten Satz komplett)',
              'chance': 'Ausgabe mit Wahrscheinlichkeit (alte Rate ignoriert `percentage_str`)'}
    w('| Feld | Abweichungen |\n|---|---|')
    for k in labels:
        w(f'| {labels[k]} | {len(diffs[k])} |')
    w('')
    for k in labels:
        if not diffs[k]:
            continue
        w(f'### {labels[k]}\n')
        w('| Rezept | alt | neu |\n|---|---|---|')
        for i, x, y in diffs[k]:
            w(f'| `{i}` | {x} | {y} |')
        w('')

    # ---- tags
    w('## 3. Crafting-Tags\n')
    w(f'- alt: {len(old_tags)}, neu: {len(new_tags)} (CraftingTag-Templates)')
    w(f'- nur neu: {", ".join(f"`{t}`" for t in sorted(set(new_tags) - set(old_tags))) or "–"}')
    w(f'- nur alt: {", ".join(f"`{t}`" for t in sorted(set(old_tags) - set(new_tags))) or "–"}')
    used = sorted({t for r in new.values() for t in r['tags']} - set(new_tags))
    w(f'- in Rezepten benutzt, aber ohne CraftingTag-Template: {", ".join(f"`{t}`" for t in used) or "–"}\n')

    # ---- machine speeds
    w('## 4. Maschinen und Geschwindigkeiten\n')
    w('Alt: pro Tag immer die Stufen 1 / 1,5 / 2, geraten aus den `===[SPEED x]===`-Markern im `_infoBox`. '
      'Diese Marker stehen in **jedem** Rezept-Tooltip, egal welche Maschinen es gibt. '
      'Neu: Maschinen aus `BuildableObjectTemplate`, Multiplikator aus `*_recipeTimeModifier_str`, '
      'Zuordnung wie `CraftingRecipe.onLoadPostprocess`.\n')
    real = defaultdict(list)
    for m in new_machines.values():
        c = m.get('crafting')
        if not c:
            continue
        for t in c['tags']:
            real[t].append((c['speedMultiplier'], m['identifier'], c['kind']))
        if c['recipeSelection'] != 'tags':
            for rid in c['derived']['recipes']:
                for t in new[rid]['tags']:
                    real[t].append((c['speedMultiplier'], m['identifier'], c['kind'] + ' (fix/Liste)'))
    real['character'].append((CHARACTER_SPEED, 'character',
                              f'Character (Simulation timeMs/{CHARACTER_SPEED}, Tooltip /5)'))
    old_by_tag = defaultdict(list)
    for v in old_machines.values():
        for t in v['craftingTags']:
            old_by_tag[t].append(v['craftingSpeedMultiplier'])
    w('| Tag | alt: Stufen | neu: echte Maschinen (Multiplikator) | erfundene Stufen (nur alt) | fehlende Stufen (nur neu) |')
    w('|---|---|---|---|---|')
    for t in sorted(set(old_by_tag) | set(real)):
        os_ = sorted(set(old_by_tag.get(t, [])))
        ns = sorted({s for s, _, _ in real.get(t, [])})
        mlist = ', '.join(f'`{mid}` ×{s} ({k})' for s, mid, k in sorted(set(real.get(t, []))))
        w(f'| `{t}` | {", ".join(map(str, os_)) or "–"} | {mlist or "–"} | '
          f'{", ".join(map(str, sorted(set(os_) - set(ns)))) or "–"} | {", ".join(map(str, sorted(set(ns) - set(os_)))) or "–"} |')
    w('')
    w('Zusätzlich neu pro Maschine: Strom (`energyConsumptionKW_str`), Größe, Fluid-Boxen, Item-Slots, Name und Item.\n')

    # ---- what's entirely new
    w('## 5. Was der alte Datensatz gar nicht hat\n')
    w(f'- Assembly Line: {al["count"]} Roboter mit Stufen/Aktionen, Starter-/Verkaufs-Items, Lackverbrauch, Durchsatz '
      f'({len(al["machines"])} AL-Maschinen).')
    w('- Fluid-Ein-/Ausgaben von Rezepten, Wahrscheinlichkeiten von Ausgaben.')
    w('- Items, Elemente, Forschung (inkl. Erkundungs-Freischaltungen) und Freischaltung pro Rezept.')
    w('- Lokalisierung in allen Spielsprachen.')
    w(f'- Handwerk: Charakter-Zeit = `timeMs / {CHARACTER_SPEED}` in ganzen 60-Hz-Ticks (nativ `FoundryNative.dll` '
      '`CraftingAction::reinitialize`, `findings/verification.md`; der Tooltip `Character.getCraftingTimeForRecipeInMs` '
      'zeigt `/5`, nur UI). Alt: Faktor 1.')

    text = '\n'.join(out) + '\n'
    if a.out:
        Path(a.out).write_text(text, encoding='utf-8')
        print(f'written {a.out}')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
