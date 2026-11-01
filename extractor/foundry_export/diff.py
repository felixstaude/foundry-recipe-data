"""Version diff of two export folders (out/v<old>, out/v<new>) -> structured dict and CHANGES.md (German).

    diff <old_dir|none> <new_dir> [--out FILE] [--json FILE]

Entries are matched by identifier (AL stages/actions by '<object> / <id>'). Keys that exist in only one export for
*every* entry of a section (the extractor gained/lost a field) are listed once under 'Neue Felder im Export' instead of
per entry. manifest.generatedAt is never compared. Output is deterministic (sorted, JSON key order of the export).

hasChanges refers to the data only (sections, producers, AL constants, export format, template types/fields,
localization); new/removed warnings are listed but do not count. 'Template-Felder' compares template_fields.json of
both versions (game template field paths, incl. the pseudo-type AssemblyLineStages), so new fields stay on record
after the baseline was accepted. New entries without a name/title in de.json / en.json are listed under
'Lokalisierung'. A notice at the top flags a template source switch / dump-vs-bundle fallback.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

COLLAPSE = 50          # lists with more entries are wrapped in <details>
MAX_VALUE = 400        # max rendered length of a dict/list value
MAP_FIELDS = {'itemSlots', 'slotWidths', 'templateCounts', 'files'}   # dicts keyed by data, not by field names
KEY_FIELDS = ('identifier', 'machine', 'item', 'element', 'recipe', 'craftingTag')
TEMPLATE_FIELDS_FILE = 'template_fields.json'
COVERAGE_LANGS = (('de', 'deutsche Übersetzung'), ('en', 'englischen Text'))   # name/title checked for new entries
# section key -> localization category (strings[<category>][<id>]); alActions are localized by producer action id
LOC_CATEGORY = {'items': 'items', 'recipes': 'recipes', 'machines': 'machines', 'research': 'research',
                'explorationUnlocks': 'explorationUnlocks', 'alObjects': 'assemblyLineObjects',
                'alActions': 'assemblyLineActions', 'elements': 'elements', 'craftingTags': 'craftingTags',
                'itemCategories': 'itemCategories', 'creativeModeCategories': 'creativeModeCategories'}


# ---------------------------------------------------------------- loading / views

def _read(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def _load(vdir: Path) -> dict:
    return {p.name: _read(p) for p in sorted(vdir.glob('*.json')) if not p.name.startswith('CHANGES')}


def _plain(fname: str, key: str):
    def view(docs: dict) -> dict | None:
        d = docs.get(fname)
        if not isinstance(d, dict) or not isinstance(d.get(key), list):
            return None
        return {e['identifier']: e for e in d[key] if isinstance(e, dict) and 'identifier' in e}
    return view


def _al_objects(docs: dict) -> list | None:
    d = docs.get('assembly_line.json')
    return d['objects'] if isinstance(d, dict) and isinstance(d.get('objects'), list) else None


def _view_al_objects(docs: dict) -> dict | None:
    objs = _al_objects(docs)
    return None if objs is None else {o['identifier']: {k: v for k, v in o.items() if k != 'stages'} for o in objs}


def _view_al_stages(docs: dict) -> dict | None:
    objs = _al_objects(docs)
    if objs is None:
        return None
    out = {}
    for o in objs:
        for i, s in enumerate(o.get('stages') or [], 1):
            out[f"{o['identifier']} / {s['identifier']}"] = {
                'object': o['identifier'], **{k: v for k, v in s.items() if k != 'actions'}, 'position': i,
                'actions': [a.get('identifier') for a in s.get('actions') or []]}
    return out


def _view_al_actions(docs: dict) -> dict | None:
    objs = _al_objects(docs)
    if objs is None:
        return None
    out = {}
    for o in objs:
        for s in o.get('stages') or []:
            for i, a in enumerate(s.get('actions') or [], 1):
                k = f"{o['identifier']} / {a['identifier']}"
                if k in out:  # action ids are unique per object in 0.6; fall back to the stage path otherwise
                    k = f"{o['identifier']} / {s['identifier']} / {a['identifier']}"
                out[k] = {'object': o['identifier'], 'stage': s['identifier'], 'position': i, **a}
    return out


# ignore: derived data that is summarised elsewhere (entries with only such changes are counted, not listed)
# hidden: helper keys of the synthetic views (never reported); group: position changes are reported within a group
SECTIONS = (
    {'key': 'items', 'title': 'Items', 'file': 'items.json', 'view': _plain('items.json', 'items'),
     'ignore': ('derived',), 'reason': 'folgt aus Rezepten und Assembly Line'},
    {'key': 'recipes', 'title': 'Rezepte', 'file': 'recipes.json', 'view': _plain('recipes.json', 'recipes'),
     'ignore': ('derived.producers',), 'reason': 'zusammengefasst unter Hersteller-Änderungen'},
    {'key': 'machines', 'title': 'Maschinen und Gebäude', 'file': 'machines.json', 'view': _plain('machines.json', 'machines'),
     'ignore': ('crafting.derived',), 'reason': 'folgt aus den Rezept-Tags, siehe Rezepte → Hersteller-Änderungen'},
    {'key': 'research', 'title': 'Forschungen', 'file': 'research.json', 'view': _plain('research.json', 'research')},
    {'key': 'explorationUnlocks', 'title': 'Erkundungs-Freischaltungen', 'file': 'research.json',
     'view': _plain('research.json', 'explorationUnlocks')},
    {'key': 'alObjects', 'title': 'Assembly-Line-Roboter', 'file': 'assembly_line.json', 'view': _view_al_objects},
    {'key': 'alStages', 'title': 'Assembly-Line-Stufen', 'file': 'assembly_line.json', 'view': _view_al_stages,
     'hidden': ('position', 'actions'), 'group': ('object',), 'pair': True},
    {'key': 'alActions', 'title': 'Assembly-Line-Aktionen', 'file': 'assembly_line.json', 'view': _view_al_actions,
     'hidden': ('position',), 'group': ('object', 'stage')},
    {'key': 'alMachines', 'title': 'Assembly-Line-Maschinen', 'file': 'assembly_line.json',
     'view': _plain('assembly_line.json', 'machines')},
    {'key': 'elements', 'title': 'Elemente', 'file': 'elements.json', 'view': _plain('elements.json', 'elements')},
    {'key': 'craftingTags', 'title': 'Crafting-Tags', 'file': 'crafting_tags.json', 'view': _plain('crafting_tags.json', 'tags')},
    {'key': 'itemCategories', 'title': 'Item-Kategorien', 'file': 'items.json', 'view': _plain('items.json', 'categories')},
    {'key': 'creativeModeCategories', 'title': 'Creative-Mode-Kategorien', 'file': 'items.json',
     'view': _plain('items.json', 'creativeModeCategories')},
)


# ---------------------------------------------------------------- generic deep diff

class _Ctx:
    def __init__(self, new_fields=(), removed_fields=(), skip=()):
        self.new, self.removed, self.skip = set(new_fields), set(removed_fields), set(skip)


def _join(a: str, b: str) -> str:
    return f'{a}.{b}' if a else b


def _parent(p: str) -> str:
    return p.rsplit('.', 1)[0] if '.' in p else ''


def _child_norm(np: str, k: str) -> str:
    return _join(np, '{}' if np.rsplit('.', 1)[-1] in MAP_FIELDS else k)


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    return type(a) is type(b) and a == b


def _shape(entries) -> tuple[Counter, Counter]:
    """Count dict containers and keys per normalized path (list elements -> '[]', map keys -> '{}')."""
    containers, keys = Counter(), Counter()

    def walk(v, np):
        if isinstance(v, dict):
            containers[np] += 1
            for k, x in v.items():
                p = _child_norm(np, k)
                keys[p] += 1
                walk(x, p)
        elif isinstance(v, list):
            for x in v:
                walk(x, np + '[]')
    for e in entries:
        walk(e, '')
    return containers, keys


def _field_changes(old_entries, new_entries) -> tuple[set, set]:
    """Fields the extractor gained/lost: present in every instance of the parent object on one side, never on the other."""
    oc, ok = _shape(old_entries)
    nc, nk = _shape(new_entries)
    added = {p for p in nk.keys() - ok.keys() if not p.endswith('{}') and _parent(p) in oc and nk[p] == nc[_parent(p)]}
    removed = {p for p in ok.keys() - nk.keys() if not p.endswith('{}') and _parent(p) in nc and ok[p] == oc[_parent(p)]}
    return added, removed


def _topmost(paths) -> list:
    """Drops paths covered by another path of the set ('a' covers 'a.b' and 'a[].b'): report a new list/object once."""
    paths = set(paths)
    return sorted(p for p in paths if not any(ch in '.[' and p[:i] in paths for i, ch in enumerate(p)))


def _list_key(a: list, b: list) -> str | None:
    items = a + b
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    for k in KEY_FIELDS:
        if all(isinstance(x.get(k), str) for x in items) and len({x[k] for x in a}) == len(a) \
                and len({x[k] for x in b}) == len(b):
            return k
    return None


def _pair_field(ea: dict, eb: dict, key: str, ln: str, ctx: _Ctx) -> str | None:
    """{key, value} elements like {item, amount}: return the value field name."""
    fa = [k for k in ea if k != key and _join(ln, k) not in ctx.removed]
    fb = [k for k in eb if k != key and _join(ln, k) not in ctx.new]
    if len(fa) == 1 and fa == fb and not isinstance(ea[fa[0]], (dict, list)) and not isinstance(eb[fa[0]], (dict, list)):
        return fa[0]
    return None


def _diff(a, b, rp: str, np: str, out: list, ctx: _Ctx) -> None:
    if _same(a, b):
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(b) + [k for k in a if k not in b]:
            cn, cr = _child_norm(np, k), _join(rp, k)
            if cn in ctx.skip:
                continue
            if k not in a:
                if cn not in ctx.new:
                    out.append({'op': 'added', 'path': cr, 'new': b[k]})
            elif k not in b:
                if cn not in ctx.removed:
                    out.append({'op': 'removed', 'path': cr, 'old': a[k]})
            else:
                _diff(a[k], b[k], cr, cn, out, ctx)
    elif isinstance(a, list) and isinstance(b, list):
        _diff_list(a, b, rp, np, out, ctx)
    else:
        out.append({'op': 'changed', 'path': rp, 'old': a, 'new': b})


def _diff_list(a: list, b: list, rp: str, np: str, out: list, ctx: _Ctx) -> None:
    ln = np + '[]'
    if not any(isinstance(x, (dict, list)) for x in a + b):
        ka, kb = [json.dumps(x) for x in a], [json.dumps(x) for x in b]
        plus, minus = sorted((Counter(kb) - Counter(ka)).elements()), sorted((Counter(ka) - Counter(kb)).elements())
        if plus or minus:
            out.append({'op': 'set', 'path': rp, 'added': [json.loads(x) for x in plus],
                        'removed': [json.loads(x) for x in minus]})
        elif ka != kb:
            out.append({'op': 'order', 'path': rp, 'old': a, 'new': b})
        return
    key = _list_key(a, b)
    if key is None:
        for i in range(max(len(a), len(b))):
            cr = f'{rp}[{i}]'
            if i >= len(a):
                out.append({'op': 'added', 'path': cr, 'new': b[i]})
            elif i >= len(b):
                out.append({'op': 'removed', 'path': cr, 'old': a[i]})
            else:
                _diff(a[i], b[i], cr, ln, out, ctx)
        return
    ma, mb = {x[key]: x for x in a}, {x[key]: x for x in b}
    for k in [x[key] for x in b] + [x[key] for x in a if x[key] not in mb]:
        ea, eb = ma.get(k), mb.get(k)
        if ea is None:
            out.append({'op': 'added', 'path': rp, 'key': k, 'keyField': key, 'new': eb})
        elif eb is None:
            out.append({'op': 'removed', 'path': rp, 'key': k, 'keyField': key, 'old': ea})
        else:
            pf = _pair_field(ea, eb, key, ln, ctx)
            if pf is None:
                _diff(ea, eb, f'{rp}[{k}]', ln, out, ctx)
            elif not _same(ea[pf], eb[pf]):
                out.append({'op': 'changed', 'path': rp, 'key': k, 'old': ea[pf], 'new': eb[pf]})
    ca, cb = [x[key] for x in a if x[key] in mb], [x[key] for x in b if x[key] in ma]
    if ca != cb:
        out.append({'op': 'order', 'path': rp, 'old': ca, 'new': cb})


def _diff_entry(a, b, ctx: _Ctx) -> list:
    out: list = []
    _diff(a, b, '', '', out, ctx)
    return out


def _lcs(a: list, b: list) -> set:
    n, m = len(a), len(b)
    t = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            t[i][j] = t[i + 1][j + 1] + 1 if a[i] == b[j] else max(t[i + 1][j], t[i][j + 1])
    i = j = 0
    keep = set()
    while i < n and j < m:
        if a[i] == b[j]:
            keep.add(a[i]); i += 1; j += 1
        elif t[i + 1][j] >= t[i][j + 1]:
            i += 1
        else:
            j += 1
    return keep


def _moves(old: dict, new: dict, group: tuple) -> dict:
    """Position changes of entries that kept their group, ignoring pure shifts (LCS of the common order)."""
    seqs: dict = defaultdict(list)
    for k in new:
        if k in old and all(old[k].get(g) == new[k].get(g) for g in group):
            seqs[tuple(new[k].get(g) for g in group)].append(k)
    out = {}
    for ks in seqs.values():
        sa, sb = sorted(ks, key=lambda k: old[k]['position']), sorted(ks, key=lambda k: new[k]['position'])
        keep = _lcs(sa, sb)
        for k in sa:
            if k not in keep:
                out[k] = [{'op': 'changed', 'path': 'position', 'old': old[k]['position'], 'new': new[k]['position']}]
    return out


def _pair_stages(old: dict, new: dict, removed: list, added: list) -> dict:
    """Stage identifier renames within one object: same title, else same set of actions. Returns {new_key: old_key}."""
    pairs: dict = {}
    for attr in ('title', 'actions'):
        val = (lambda e: e.get('title')) if attr == 'title' else (lambda e: sorted(map(str, e.get('actions') or [])))
        for k in sorted(added):
            if k in pairs or not val(new[k]):
                continue
            obj, v = new[k]['object'], val(new[k])
            cand = [r for r in sorted(removed) if r not in pairs.values() and old[r]['object'] == obj and val(old[r]) == v]
            twins = [x for x in added if x not in pairs and new[x]['object'] == obj and val(new[x]) == v]
            if len(cand) == 1 and len(twins) == 1:
                pairs[k] = cand[0]
    return pairs


def _name(e: dict):
    pa = e.get('producerAction')
    return e.get('name') or e.get('title') or (pa.get('name') if isinstance(pa, dict) else None)


def _ref(key: str, e: dict) -> str | None:
    """Second identifier shown next to the entry id: the producer action template (ALPA) of an AL action."""
    if key != 'alActions':
        return None
    pa = e.get('producerAction')
    return pa.get('identifier') if isinstance(pa, dict) and isinstance(pa.get('identifier'), str) else None


def _entry(key: str, eid: str, e: dict, **kw) -> dict:
    out = {'id': eid, 'name': _name(e)}
    ref = _ref(key, e)
    if ref is not None:
        out['ref'] = ref
    return {**out, **kw}


def _section(spec: dict, old_docs: dict | None, new_docs: dict) -> dict:
    new = spec['view'](new_docs)
    old = spec['view'](old_docs) if old_docs is not None else None
    sec = {'key': spec['key'], 'title': spec['title'], 'file': spec['file'],
           'oldCount': None if old is None else len(old), 'newCount': None if new is None else len(new),
           'comparable': old is not None and new is not None, 'added': [], 'removed': [], 'changed': [],
           'newFields': [], 'removedFields': [], 'ignored': list(spec.get('ignore', ())),
           'ignoredReason': spec.get('reason'), 'ignoredOnly': 0}
    if not sec['comparable']:
        return sec
    nf, rf = _field_changes(list(old.values()), list(new.values()))
    sec['newFields'], sec['removedFields'] = _topmost(nf), _topmost(rf)
    hidden = set(spec.get('hidden', ()))
    full, ctx = _Ctx(nf, rf, hidden), _Ctx(nf, rf, hidden | set(spec.get('ignore', ())))
    added, removed = [k for k in new if k not in old], [k for k in old if k not in new]
    pairs = _pair_stages(old, new, removed, added) if spec.get('pair') else {}
    extra = _moves(old, new, spec['group']) if spec.get('group') else {}
    paired_old = set(pairs.values())
    key = spec['key']
    sec['added'] = [_entry(key, k, new[k], value=new[k]) for k in sorted(added) if k not in pairs]
    sec['removed'] = [_entry(key, k, old[k], value=old[k]) for k in sorted(removed) if k not in paired_old]
    for k in sorted([k for k in new if k in old] + list(pairs)):
        a, b = old[pairs.get(k, k)], new[k]
        ch = list(extra.get(k, []))
        if not _same(a, b):
            ch = _diff_entry(a, b, ctx) + ch
            if not ch and _diff_entry(a, b, full):
                sec['ignoredOnly'] += 1
        if ch:
            sec['changed'].append(_entry(key, k, b, changes=ch))
    return sec


# ---------------------------------------------------------------- special parts

def _producer_changes(old_docs: dict, new_docs: dict) -> dict:
    """Summary of recipes.derived.producers: machines that gained/lost recipes, changed speed/kind."""
    view = _plain('recipes.json', 'recipes')
    old, new = view(old_docs), view(new_docs)
    added, removed, changed = defaultdict(list), defaultdict(list), defaultdict(list)
    for rid in sorted((old or {}).keys() & (new or {}).keys()):
        pa = {p.get('machine'): p for p in (old[rid].get('derived') or {}).get('producers') or []}
        pb = {p.get('machine'): p for p in (new[rid].get('derived') or {}).get('producers') or []}
        for m in pb.keys() - pa.keys():
            added[str(m)].append(rid)
        for m in pa.keys() - pb.keys():
            removed[str(m)].append(rid)
        for m in pa.keys() & pb.keys():
            for f in ('kind', 'speedMultiplier'):
                if not _same(pa[m].get(f), pb[m].get(f)):
                    changed[(str(m), f, json.dumps(pa[m].get(f)), json.dumps(pb[m].get(f)))].append(rid)
    return {'added': {m: v for m, v in sorted(added.items())}, 'removed': {m: v for m, v in sorted(removed.items())},
            'changed': [{'machine': m, 'field': f, 'old': json.loads(o), 'new': json.loads(n), 'recipes': v}
                        for (m, f, o, n), v in sorted(changed.items())]}


def _constants(old_docs: dict, new_docs: dict) -> tuple[list, list, list]:
    a = (old_docs.get('assembly_line.json') or {}).get('constants')
    b = (new_docs.get('assembly_line.json') or {}).get('constants')
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return [], [], []
    nf, rf = _field_changes([a], [b])
    return _diff_entry(a, b, _Ctx(nf, rf)), _topmost(nf), _topmost(rf)


def _templates(om: dict | None, nm: dict) -> dict:
    nc = nm.get('templateCounts') if isinstance(nm.get('templateCounts'), dict) else None
    if om is None:
        return {'status': 'first', 'counts': nc}
    oc = om.get('templateCounts') if isinstance(om.get('templateCounts'), dict) else None
    if oc is not None and nc is not None:
        return {'status': 'compared', 'added': {k: nc[k] for k in sorted(nc.keys() - oc.keys())},
                'removed': {k: oc[k] for k in sorted(oc.keys() - nc.keys())},
                'changed': [{'type': k, 'old': oc[k], 'new': nc[k]} for k in sorted(oc.keys() & nc.keys()) if oc[k] != nc[k]],
                'counts': nc}
    return {'status': 'oldMissing' if nc is not None else ('newMissing' if oc is not None else 'missing'), 'counts': nc}


def _template_fields(od: dict | None, nd: dict) -> dict:
    """New/removed template field paths per type (topmost only) from template_fields.json of both versions."""
    def types(doc):
        return doc['types'] if isinstance(doc, dict) and isinstance(doc.get('types'), dict) else None
    nf, of = nd.get(TEMPLATE_FIELDS_FILE), (od or {}).get(TEMPLATE_FIELDS_FILE)
    nt, ot = types(nf), types(of)
    if od is None:
        return {'status': 'first', 'types': [], 'typesAdded': [], 'typesRemoved': []}
    res = {'status': 'compared', 'oldSource': (of or {}).get('templateSource') if ot is not None else None,
           'newSource': (nf or {}).get('templateSource') if nt is not None else None,
           'types': [], 'typesAdded': [], 'typesRemoved': [], 'typeCount': 0}
    if nt is None or ot is None:
        res['status'] = 'missing' if nt is None and ot is None else ('newMissing' if nt is None else 'oldMissing')
        return res

    def fields(side: dict, t: str) -> set:
        v = side.get(t)
        return set(v.get('fields') or []) if isinstance(v, dict) else set()
    for t in sorted(nt.keys() & ot.keys()):
        a, b = fields(ot, t), fields(nt, t)
        added, removed = _topmost(b - a), _topmost(a - b)
        if added or removed:
            res['types'].append({'type': t, 'added': added, 'removed': removed})
    res['typesAdded'] = [{'type': t, 'fields': len(fields(nt, t))} for t in sorted(nt.keys() - ot.keys())]
    res['typesRemoved'] = [{'type': t, 'fields': len(fields(ot, t))} for t in sorted(ot.keys() - nt.keys())]
    res['typeCount'] = len(nt.keys() & ot.keys())
    return res


SOURCE_REASONS = (   # (warning prefix, extra condition, reason key)
    ('source: Templates dump differs from foundry_main_bundle, but', None, 'mismatchKeptDump'),
    ('source: Templates dump differs from foundry_main_bundle', None, 'mismatch'),
    ('source-mismatch: bundle comparison failed', None, 'comparisonFailed'),
    ('source:', '(fallback)', 'fallback'),
    ('source:', '(--source bundle)', 'forced'),
)


def _source_notice(om: dict | None, nm: dict) -> dict | None:
    """Template source facts worth a prominent notice: dump/bundle mismatch, fallback, forced source, source switch."""
    reasons: list = []
    for w in nm.get('warnings') or []:
        for prefix, extra, key in SOURCE_REASONS:
            if w.startswith(prefix) and (extra is None or extra in w):
                if key not in reasons:
                    reasons.append(key)
                break
    if 'mismatchKeptDump' in reasons and 'mismatch' in reasons:
        reasons.remove('mismatch')
    old_src, new_src = (om or {}).get('templateSource'), nm.get('templateSource')
    switched = om is not None and old_src is not None and old_src != new_src
    if not reasons and not switched:
        return None
    return {'source': new_src, 'oldSource': old_src, 'switched': switched,
            'oldUnknown': om is not None and old_src is None, 'reasons': sorted(reasons)}


def _warnings(om: dict | None, nm: dict) -> dict:
    nw, ow = set(nm.get('warnings') or []), set((om or {}).get('warnings') or [])
    return {'added': sorted(nw - ow), 'removed': sorted(ow - nw), 'unchanged': sorted(nw & ow)}


def _loc_strings(d: dict) -> dict:
    out = {}

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, path + (k,))
        else:
            out[path] = v
    walk(d.get('strings') or {}, ())
    return out


def _localization(old_dir: Path | None, new_dir: Path) -> dict:
    def langs(d):
        return {p.stem: p for p in sorted((d / 'localization').glob('*.json'))} if d is not None else {}
    ol, nl = langs(old_dir), langs(new_dir)
    res = {'added': sorted(nl.keys() - ol.keys()) if old_dir is not None else [],
           'removed': sorted(ol.keys() - nl.keys()), 'languages': {}}
    for lang in sorted(nl):
        sn = _loc_strings(_read(nl[lang]))
        e = {'newCount': len(sn)}
        if lang in ol:
            so = _loc_strings(_read(ol[lang]))
            e.update(oldCount=len(so), added=len(sn.keys() - so.keys()), removed=len(so.keys() - sn.keys()),
                     changed=sum(1 for k in so.keys() & sn.keys() if so[k] != sn[k]))
        res['languages'][lang] = e
    return res


def _new_entry_ids(spec: dict, sec: dict, od: dict | None, nd: dict) -> list[tuple[str, dict]]:
    """(id, entry) of the entries new in this version (all entries for a first export)."""
    if od is None:
        view = spec['view'](nd) or {}
        return [(k, view[k]) for k in sorted(view)]
    return [(e['id'], e['value']) for e in sec['added']]


def _loc_coverage(specs_secs: list, od: dict | None, nd: dict, new_dir: Path) -> dict:
    """New entries without a non-empty name/title in localization/<lang>.json (COVERAGE_LANGS)."""
    strings = {}
    for lang, _ in COVERAGE_LANGS:
        p = new_dir / 'localization' / f'{lang}.json'
        try:
            doc = _read(p) if p.is_file() else None
        except (OSError, ValueError):
            doc = None
        strings[lang] = doc.get('strings') if isinstance(doc, dict) and isinstance(doc.get('strings'), dict) else None
    res = {'checked': 0, 'missing': {lang: [] for lang, _ in COVERAGE_LANGS},
           'unavailable': [lang for lang, _ in COVERAGE_LANGS if strings[lang] is None]}
    for spec, sec in specs_secs:
        cat = LOC_CATEGORY.get(spec['key'])
        if cat is None:
            continue
        for eid, e in _new_entry_ids(spec, sec, od, nd):
            loc_id = _ref(spec['key'], e) if spec['key'] == 'alActions' else eid
            if not isinstance(loc_id, str):
                continue
            res['checked'] += 1
            for lang, _ in COVERAGE_LANGS:
                if strings[lang] is None:
                    continue
                cats = strings[lang].get(cat)
                s = cats.get(loc_id) if isinstance(cats, dict) else None
                if not (isinstance(s, dict) and any(isinstance(s.get(f), str) and s[f].strip() for f in ('name', 'title'))):
                    res['missing'][lang].append({'section': spec['title'], 'id': eid, 'locId': loc_id})
    return res


def _header(vdir: Path, m: dict) -> dict:
    name = vdir.resolve().name
    return {'version': name if name.startswith('v') else f"v{m.get('gameVersion', '?')}",
            **{k: m.get(k) for k in ('gameVersion', 'steamBuildId', 'unityVersion', 'generatedAt', 'generator',
                                     'schemaVersion', 'templateSource', 'previousVersion')}}


def _has_changes(d: dict) -> bool:
    """Data changes only - warnings are reported separately (d['warningsChanged']) and do not count."""
    if any(s['added'] or s['removed'] or s['changed'] or s['ignoredOnly']
           or (not s['comparable'] and s['oldCount'] != s['newCount']) for s in d['sections']):
        return True
    p, t, tf, loc = d['producers'], d['templates'], d['templateFields'], d['localization']
    return bool(p['added'] or p['removed'] or p['changed'] or d['alConstants']
                or d['fields']['added'] or d['fields']['removed'] or d['files']['added'] or d['files']['removed']
                or t.get('added') or t.get('removed') or t.get('changed')
                or tf['types'] or tf['typesAdded'] or tf['typesRemoved']
                or loc['added'] or loc['removed']
                or any(e.get('added') or e.get('removed') or e.get('changed') for e in loc['languages'].values()))


def diff_versions(old_dir: Path | str | None, new_dir: Path | str) -> dict:
    """Structured, deterministic diff of two export version folders; old_dir=None means 'first export'."""
    new_dir = Path(new_dir)
    old_dir = Path(old_dir) if old_dir is not None else None
    nd = _load(new_dir)
    od = _load(old_dir) if old_dir is not None else None
    nm = nd.get('manifest.json') or {}
    om = (od.get('manifest.json') or {}) if od is not None else None
    res: dict = {'diffFormat': 2, 'first': od is None, 'old': _header(old_dir, om) if od is not None else None,
                 'new': _header(new_dir, nm), 'sourceNotice': _source_notice(om, nm),
                 'sections': [_section(s, od, nd) for s in SECTIONS]}
    if od is not None:
        res['producers'] = _producer_changes(od, nd)
        res['alConstants'], cnf, crf = _constants(od, nd)
        fields: dict = {'added': [], 'removed': []}
        for s in res['sections']:
            fields['added'] += [{'section': s['title'], 'path': p} for p in s['newFields']]
            fields['removed'] += [{'section': s['title'], 'path': p} for p in s['removedFields']]
        fields['added'] += [{'section': 'Assembly-Line-Konstanten', 'path': p} for p in cnf]
        fields['removed'] += [{'section': 'Assembly-Line-Konstanten', 'path': p} for p in crf]
        for fname in sorted(od.keys() & nd.keys()):
            a, b = od[fname], nd[fname]
            if isinstance(a, dict) and isinstance(b, dict):
                fields['added'] += [{'section': fname, 'path': k} for k in b if k not in a]
                fields['removed'] += [{'section': fname, 'path': k} for k in a if k not in b]
        res['fields'] = fields
        res['files'] = {'added': sorted(nd.keys() - od.keys()), 'removed': sorted(od.keys() - nd.keys())}
    res['templates'] = _templates(om, nm)
    res['templateFields'] = _template_fields(od, nd)
    res['warnings'] = _warnings(om, nm)
    res['localization'] = _localization(old_dir if od is not None else None, new_dir)
    res['localization']['newEntries'] = _loc_coverage(list(zip(SECTIONS, res['sections'])), od, nd, new_dir)
    res['hasChanges'] = (not res['first']) and _has_changes(res)
    res['warningsChanged'] = (not res['first']) and bool(res['warnings']['added'] or res['warnings']['removed'])
    return res


# ---------------------------------------------------------------- rendering

def _num(x) -> str:
    if isinstance(x, float):
        return str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)
    return str(x)


def _code(s) -> str:
    s = str(s).replace('`', "'").replace('\r', '').replace('\n', ' ⏎ ')
    return f'`{s}`' if s.strip() else '""'


def _text(s) -> str:
    return str(s).replace('\r', '').replace('\n', ' ').replace('<', '&lt;')


def _fmt(v) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return _num(v)
    if isinstance(v, str):
        return _code(v)
    if isinstance(v, list):
        s = '[' + ', '.join(_fmt(x) for x in v) + ']'
    elif isinstance(v, dict):
        s = '{' + ', '.join(f'{k}: {_fmt(x)}' for k, x in v.items()) + '}'
    else:
        s = _code(v)
    return s if len(s) <= MAX_VALUE else s[:MAX_VALUE] + ' …'


def _elem_rest(v, key_field: str | None) -> str:
    if not isinstance(v, dict):
        return ' ' + _fmt(v)
    rest = [(k, x) for k, x in v.items() if k != key_field]
    if len(rest) == 1 and not isinstance(rest[0][1], (dict, list)):
        return ' ' + _fmt(rest[0][1])
    parts = [f'{k} {len(x)} Einträge' if isinstance(x, list) else f'{k} {_fmt(x)}' for k, x in rest]
    return f" ({', '.join(parts)})" if parts else ''


def render_change(c: dict) -> str:
    op, p = c['op'], c['path']
    if op == 'set':
        parts = (['+ ' + ', '.join(map(_fmt, c['added']))] if c['added'] else []) + \
                (['− ' + ', '.join(map(_fmt, c['removed']))] if c['removed'] else [])
        return f"{p}: {'; '.join(parts)}"
    if op == 'order':
        return f"{p}: Reihenfolge {', '.join(map(_fmt, c['old']))} → {', '.join(map(_fmt, c['new']))}"
    if 'key' in c:
        if op == 'changed':
            return f"{p}: {_code(c['key'])} {_fmt(c['old'])} → {_fmt(c['new'])}"
        sign, v = ('+', c['new']) if op == 'added' else ('−', c['old'])
        return f"{p}: {sign} {_code(c['key'])}{_elem_rest(v, c.get('keyField'))}"
    if op == 'added':
        return f"{p}: (fehlt) → {_fmt(c['new'])}"
    if op == 'removed':
        return f"{p}: {_fmt(c['old'])} → (entfernt)"
    return f"{p}: {_fmt(c['old'])} → {_fmt(c['new'])}"


def _codes(xs) -> str:
    return ', '.join(_code(x) for x in xs)


def _amounts(items, fluids) -> str:
    return ' + '.join([f"{i.get('amount')}× {_code(i.get('item'))}" for i in items or []]
                      + [f"{_num(f.get('liters'))} l {_code(f.get('element'))}" for f in fluids or []])


def _s_item(e: dict) -> str:
    parts = [f"Stack {e['stackSize']}"] if e.get('stackSize') is not None else []
    return '; '.join(parts + (['Flags ' + _codes(e['flags'])] if e.get('flags') else []))


def _s_recipe(r: dict) -> str:
    outs = ' + '.join([f"{o.get('amount')}× {_code(o.get('item'))}" + (f" ({_num(round(o['chance'] * 100, 4))} %)"
                                                                       if o.get('chance', 1) != 1 else '')
                       for o in r.get('outputs') or []]
                      + [f"{_num(f.get('liters'))} l {_code(f.get('element'))}" for f in r.get('fluidOutputs') or []])
    s = f"{_num(r['timeMs'] / 1000)} s, {_amounts(r.get('inputs'), r.get('fluidInputs')) or '–'} → {outs or '–'}"
    if r.get('tags'):
        s += '; Tags ' + _codes(r['tags'])
    u = (r.get('derived') or {}).get('unlockedBy') or {}
    us = (u.get('research') or []) + (u.get('explorationUnlocks') or [])
    return s + ('; freigeschaltet durch ' + _codes(us) if us else '')


def _s_machine(m: dict) -> str:
    parts = [f"Typ {_code(m.get('type'))}"]
    sz = m.get('size') or {}
    if sz:
        parts.append('×'.join(_num(sz.get(k)) for k in ('x', 'y', 'z')))
    kw = (m.get('power') or {}).get('consumptionKW')
    if kw:
        parts.append(f'{_num(kw)} kW')
    c = m.get('crafting')
    if c:
        parts.append(f"Tempo ×{_num(c.get('speedMultiplier'))}" + (f", Tags {_codes(c['tags'])}" if c.get('tags') else ''))
    if m.get('assemblyLine'):
        parts.append(f"AL-Rolle {_code(m['assemblyLine'].get('role'))}")
    return ', '.join(parts)


def _s_research(r: dict) -> str:
    s = f"Kosten {_amounts(r.get('cost'), None) or '–'}"
    if r.get('dependencies'):
        s += '; benötigt ' + _codes(r['dependencies'])
    un = [f'{k} ' + (_codes(v) if len(v) <= 10 else f'({len(v)})') for k, v in (r.get('unlocks') or {}).items() if v]
    return s + ('; schaltet frei: ' + '; '.join(un) if un else '')


def _s_exploration(e: dict) -> str:
    s = f"Bedarf {_amounts(e.get('requirements'), None) or '–'}"
    return s + (f"; Rezepte {_codes(e['recipeUnlocks'])}" if e.get('recipeUnlocks') else '')


def _s_al_object(o: dict) -> str:
    dv = o.get('derived') or {}
    return (f"Start {_fmt(o.get('starterItem'))}, Verkauf {_fmt(o.get('sellItem'))}, Forschung {_fmt(o.get('researchedBy'))}, "
            f"{len(o.get('parts') or [])} Teile, Gesamtenergie {_num(dv.get('totalPowerKJ'))} kJ")


def _s_al_action(a: dict) -> str:
    pa = a.get('producerAction') or {}
    s = f"Stufe {_code(a.get('stage'))}, Position {a.get('position')}, {_code(a.get('type'))}, {_num(pa.get('powerKJ'))} kJ"
    am = _amounts(pa.get('items'), pa.get('fluids'))
    return s + (f', {am}' if am else '') + (f", montiert {_code(pa['attachesPart'])}" if pa.get('attachesPart') else '')


def _s_al_machine(m: dict) -> str:
    sp = (m.get('derived') or {}).get('speedMetersPerSec')
    return f"Rolle {_code(m.get('role'))}" + (f', {_num(sp)} m/s' if sp is not None else '')


_SUMMARY = {
    'items': _s_item, 'recipes': _s_recipe, 'machines': _s_machine, 'research': _s_research,
    'explorationUnlocks': _s_exploration, 'alObjects': _s_al_object, 'alActions': _s_al_action,
    'alStages': lambda s: f"Position {s.get('position')}, {len(s.get('actions') or [])} Aktionen",
    'alMachines': _s_al_machine,
    'craftingTags': lambda t: ('Maschinen ' + _codes(t['derived']['machines'])
                               if (t.get('derived') or {}).get('machines') else ''),
}


def _summary(key: str, e: dict) -> str:
    try:
        s = _SUMMARY[key](e) if key in _SUMMARY else ''
    except (AttributeError, KeyError, TypeError, ValueError):
        s = ''
    return f': {s}' if s else ''


def _label(e: dict) -> str:
    """`id` (`ref`) – name; ref = producer action template of an AL action."""
    return _code(e['id']) + (f" ({_code(e['ref'])})" if e.get('ref') else '') + (f" – {_text(e['name'])}" if e.get('name') else '')


def _block(L: list, heading: str | None, blocks: list[list[str]], what: str = 'Einträge') -> None:
    if heading:
        L += [heading, '']
    lines = [x for b in blocks for x in b]
    if len(blocks) > COLLAPSE:
        L += ['<details>', f'<summary>{len(blocks)} {what} anzeigen</summary>', '', *lines, '', '</details>', '']
    else:
        L += lines + ['']


def _inline_list(xs: list) -> str:
    if len(xs) > COLLAPSE:
        return f'<details><summary>{len(xs)} anzeigen</summary>{_codes(xs)}</details>'
    return _codes(xs)


def _cnt(x) -> str:
    return '–' if x is None else str(x)


def _render_section(s: dict, d: dict, L: list) -> None:
    L += [f"## {s['title']}", '']
    if not s['comparable']:
        side = 'alten' if s['oldCount'] is None else 'neuen'
        L += [f"_Daten (`{s['file']}`) fehlen in der {side} Version – kein Vergleich möglich._", '']
        return
    extra: list = []
    if s['key'] == 'recipes':
        p = d['producers']
        blocks = [[f"- {_code(m)} stellt jetzt zusätzlich {len(rs)} Rezept(e) her: {_inline_list(rs)}"]
                  for m, rs in p['added'].items()]
        blocks += [[f"- {_code(m)} stellt {len(rs)} Rezept(e) nicht mehr her: {_inline_list(rs)}"]
                   for m, rs in p['removed'].items()]
        blocks += [[f"- {_code(c['machine'])} {c['field']}: {_fmt(c['old'])} → {_fmt(c['new'])} "
                    f"({len(c['recipes'])} Rezept(e): {_inline_list(c['recipes'])})"] for c in p['changed']]
        if blocks:
            _block(extra, '### Hersteller-Änderungen (derived.producers, zusammengefasst)', blocks)
    if s['key'] == 'alMachines' and d['alConstants']:
        _block(extra, '### Konstanten', [[f'- {render_change(c)}'] for c in d['alConstants']])
    if not (s['added'] or s['removed'] or s['changed'] or extra or s['ignoredOnly']):
        L += [f"keine Änderungen ({_cnt(s['newCount'])} Einträge)", '']
        return
    L += [f"alt {_cnt(s['oldCount'])} → neu {_cnt(s['newCount'])} · neu {len(s['added'])} · entfernt {len(s['removed'])} "
          f"· geändert {len(s['changed'])}", '']
    if s['added']:
        _block(L, f"### Neu ({len(s['added'])})",
               [[f"- {_label(e)}{_summary(s['key'], e['value'])}"] for e in s['added']])
    if s['removed']:
        _block(L, f"### Entfernt ({len(s['removed'])})", [[f"- {_label(e)}"] for e in s['removed']])
    if s['changed']:
        _block(L, f"### Geändert ({len(s['changed'])})",
               [[f"- {_label(e)}"] + [f'  - {render_change(c)}' for c in e['changes']]
                for e in s['changed']])
    L += extra
    if s['ignoredOnly']:
        L += [f"_{s['ignoredOnly']} weitere Einträge haben nur Änderungen in abgeleiteten Feldern "
              f"({_codes(s['ignored'])}; {s['ignoredReason']}); sie werden hier nicht einzeln aufgeführt._", '']


HEADER_ROWS = (('Export-Version', 'version'), ('Spielversion', 'gameVersion'), ('Steam-Build', 'steamBuildId'),
               ('Unity', 'unityVersion'), ('Datum (generatedAt)', 'generatedAt'), ('Generator', 'generator'),
               ('Schema-Version', 'schemaVersion'), ('Template-Quelle', 'templateSource'))


def _render_templates(d: dict, L: list) -> None:
    t = d['templates']
    L += ['## Neue Template-Typen', '']
    counts = t.get('counts') or {}
    if t['status'] == 'compared':
        if t['added']:
            _block(L, None, [[f'- {_code(k)}: {v} Templates'] for k, v in t['added'].items()], 'Typen')
        else:
            L += ['keine neuen Template-Typen', '']
        if t['removed']:
            _block(L, f"### Entfernte Template-Typen ({len(t['removed'])})",
                   [[f'- {_code(k)} (zuvor {v})'] for k, v in t['removed'].items()], 'Typen')
        if t['changed']:
            _block(L, f"### Geänderte Template-Anzahlen ({len(t['changed'])})",
                   [[f"- {_code(c['type'])}: {c['old']} → {c['new']}"] for c in t['changed']], 'Typen')
        else:
            L += ['Template-Anzahlen unverändert.', '']
        return
    if t['status'] == 'oldMissing':
        L += [f"Für die alte Version {d['old']['version']} nicht bestimmbar (`manifest.templateCounts` fehlt dort). "
              f"Die neue Version enthält {len(counts)} Template-Typen mit zusammen {sum(counts.values())} Templates.", '']
        _block(L, None, [[f'- {_code(k)}: {v}'] for k, v in sorted(counts.items())], 'Typen')
    elif t['status'] == 'newMissing':
        L += ['Nicht bestimmbar: `manifest.templateCounts` fehlt in der neuen Version.', '']
    else:
        L += ['Nicht bestimmbar: `manifest.templateCounts` fehlt in beiden Versionen.', '']


def _render_template_fields(d: dict, L: list) -> None:
    tf = d['templateFields']
    L += ['## Template-Felder', '']
    if tf['status'] == 'oldMissing':
        L += [f'nicht bestimmbar (Vorversion ohne {TEMPLATE_FIELDS_FILE})', '']
        return
    if tf['status'] in ('newMissing', 'missing'):
        which = 'neue Version' if tf['status'] == 'newMissing' else 'beide Versionen'
        L += [f'nicht bestimmbar ({which} ohne {TEMPLATE_FIELDS_FILE})', '']
        return
    L += [f'Feldpfade der Spiel-Templates laut `{TEMPLATE_FIELDS_FILE}` (alle Felder, nicht nur exportierte; '
          'inkl. `AssemblyLineStages` = dekodierte Assembly-Line-Stufen). Bei einer neuen Liste bzw. einem neuen Objekt '
          'steht nur der oberste Pfad.', '']
    if tf['oldSource'] != tf['newSource']:
        L += [f"_Achtung: Feldlisten aus unterschiedlichen Template-Quellen ({_fmt(tf['oldSource'])} → "
              f"{_fmt(tf['newSource'])}); Unterschiede können vom Quellenwechsel stammen._", '']
    if tf['types']:
        blocks = []
        for e in tf['types']:
            b = [f"- {_code(e['type'])}"]
            if e['added']:
                b.append(f"  - neu ({len(e['added'])}): {_inline_list(e['added'])}")
            if e['removed']:
                b.append(f"  - entfernt ({len(e['removed'])}): {_inline_list(e['removed'])}")
            blocks.append(b)
        _block(L, None, blocks, 'Typen')
    else:
        L += [f"keine neuen oder entfernten Template-Felder ({tf['typeCount']} Template-Typen verglichen)", '']
    if tf['typesAdded']:
        L += ['Nur in der neuen Version erfasst (Felder nicht einzeln aufgeführt): '
              + ', '.join(f"{_code(x['type'])} ({x['fields']} Felder)" for x in tf['typesAdded']), '']
    if tf['typesRemoved']:
        L += ['Nur in der Vorversion erfasst: '
              + ', '.join(f"{_code(x['type'])} ({x['fields']} Felder)" for x in tf['typesRemoved']), '']


SOURCE_REASON_TEXT = {
    'mismatch': 'Der Templates-Dump (`StreamingAssets/Templates`) weicht von `foundry_main_bundle` ab; verwendet wurde '
                '`foundry_main_bundle`, das das Spiel lädt (siehe `source-mismatch:` unter „Warnungen“).',
    'mismatchKeptDump': 'Der Templates-Dump weicht von `foundry_main_bundle` ab, der Bundle-Leser meldete aber Probleme; '
                        'verwendet wurde der Dump – von Hand prüfen (UPDATE.md Schritt d).',
    'comparisonFailed': 'Der Vergleich Templates-Dump ↔ `foundry_main_bundle` ist fehlgeschlagen; die Daten stammen '
                        'ungeprüft aus dem Dump.',
    'fallback': '`StreamingAssets/Templates` fehlt oder ist unvollständig; die Templates wurden aus `foundry_main_bundle` '
                'gelesen (Fallback).',
    'forced': 'Die Template-Quelle wurde mit `--source bundle` erzwungen.',
}


def _src(x) -> str:
    return _code(x) if x else 'unbekannt'


def _render_notice(d: dict, L: list) -> None:
    sn = d.get('sourceNotice')
    if not sn:
        return
    lines = [f"> **Hinweis zur Template-Quelle:** Die Daten dieser Version stammen aus {_src(sn['source'])}."]
    lines += [f'> - {SOURCE_REASON_TEXT[r]}' for r in sn['reasons'] if r in SOURCE_REASON_TEXT]
    if not d['first']:
        if sn['switched']:
            lines.append(f"> - Die Vorversion wurde aus {_src(sn['oldSource'])} gelesen. **Änderungen gegenüber der "
                         f"Vorversion können ganz oder teilweise auf diesen Quellenwechsel zurückgehen** statt auf ein "
                         f"Spielupdate.")
        elif sn.get('oldUnknown'):
            lines.append('> - Die Template-Quelle der Vorversion ist unbekannt (`manifest.templateSource` fehlt); '
                         'Änderungen können auf einen Quellenwechsel zurückgehen.')
        else:
            lines.append('> - Die Vorversion wurde aus derselben Quelle gelesen (kein Quellenwechsel).')
    if {'mismatchKeptDump', 'comparisonFailed'} & set(sn['reasons']):
        lines.append('> - Daten und Änderungen spiegeln den Templates-Dump wider, nicht unbedingt das, was das Spiel lädt.')
    L += lines + ['']


def _render_warnings(d: dict, L: list) -> None:
    w = d['warnings']
    L += ['## Warnungen', '']
    if not (w['added'] or w['removed'] or w['unchanged']):
        L += ['keine Warnungen', '']
        return
    if w['added']:
        _block(L, f"### Neu in dieser Version ({len(w['added'])})", [[f'- {_text(x)}'] for x in w['added']], 'Warnungen')
    if w['removed']:
        _block(L, f"### Nicht mehr vorhanden ({len(w['removed'])})", [[f'- {_text(x)}'] for x in w['removed']], 'Warnungen')
    L += [f"Unverändert: {len(w['unchanged'])} Warnung(en).", '']


def _render_localization(d: dict, L: list) -> None:
    loc = d['localization']
    L += ['## Lokalisierung', '']
    rows = [(k, e) for k, e in loc['languages'].items() if e.get('added') or e.get('removed') or e.get('changed')]
    if rows:
        L += ['| Sprache | alt | neu | + | − | ~ |', '|---|---:|---:|---:|---:|---:|']
        L += [f"| {k} | {e['oldCount']} | {e['newCount']} | {e['added']} | {e['removed']} | {e['changed']} |" for k, e in rows]
        L += ['']
    if loc['added']:
        L += ['Neue Sprachen: ' + ', '.join(f"{k} ({loc['languages'][k]['newCount']} Strings)" for k in loc['added']), '']
    if loc['removed']:
        L += ['Entfernte Sprachen: ' + ', '.join(loc['removed']), '']
    if not (rows or loc['added'] or loc['removed']):
        L += [f"keine Änderungen ({len(loc['languages'])} Sprachen verglichen)", '']
    _render_coverage(d, L)


def _render_coverage(d: dict, L: list) -> None:
    cov = d['localization'].get('newEntries') or {}
    what, what_all = ('Einträge', 'Einträge') if d['first'] else ('neue Einträge', 'neuen Einträge')
    if not cov.get('checked'):
        return
    for lang, label in COVERAGE_LANGS:
        if lang in cov['unavailable']:
            L += [f'{what[0].upper() + what[1:]}: `localization/{lang}.json` fehlt – Übersetzungen nicht prüfbar.', '']
            continue
        miss = cov['missing'][lang]
        if miss:
            _block(L, f"{what} ohne {label} ({lang}.json, kein `name`/`title`): {len(miss)}",
                   [[f"- {x['section']}: {_code(x['id'])}" + (f" ({_code(x['locId'])})" if x['locId'] != x['id'] else '')]
                    for x in miss])
    if not any(cov['missing'][lang] for lang, _ in COVERAGE_LANGS):
        langs = ' und '.join(f'{lang}.json' for lang, _ in COVERAGE_LANGS if lang not in cov['unavailable'])
        if langs:
            L += [f"Alle {cov['checked']} {what_all} haben `name`/`title` in {langs}.", '']


def _render_fields(d: dict, L: list) -> None:
    f, files = d['fields'], d['files']
    L += ['## Neue Felder im Export (Extractor erweitert)', '']
    if f['added']:
        L += ['Diese Felder gibt es erst in der neuen Export-Version; sie werden nicht pro Eintrag als Änderung aufgeführt.', '']
        L += [f"- {x['section']}: {_code(x['path'])}" for x in f['added']] + ['']
    else:
        L += ['keine', '']
    if f['removed']:
        L += ['### Entfernte Felder im Export', '',
              'Diese Felder fehlen in der neuen Export-Version (nicht pro Eintrag aufgeführt).', '']
        L += [f"- {x['section']}: {_code(x['path'])}" for x in f['removed']] + ['']
    if files['added']:
        L += ['### Neue Dateien im Export', ''] + [f'- {_code(x)}' for x in files['added']] + ['']
    if files['removed']:
        L += ['### Entfernte Dateien im Export', ''] + [f'- {_code(x)}' for x in files['removed']] + ['']


def _render_first(d: dict, L: list) -> None:
    n = d['new']
    L += [f"# Erster Export {n['version']}", '', '| | |', '|---|---|']
    L += [f'| {label} | {_cnt(n.get(k))} |' for label, k in HEADER_ROWS if n.get(k) is not None] + ['']
    _render_notice(d, L)
    L += ['Dies ist der erste Export – es gibt keine Vorgängerversion zum Vergleich. Aufgeführt sind nur die Umfänge.', '']
    L += ['## Übersicht', '', '| Bereich | Anzahl |', '|---|---:|']
    L += [f"| {s['title']} | {_cnt(s['newCount'])} |" for s in d['sections']] + ['']
    L += ['## Template-Typen', '']
    counts = d['templates'].get('counts')
    if counts:
        L += [f'{len(counts)} Template-Typen mit zusammen {sum(counts.values())} Templates.', '']
        _block(L, None, [[f'- {_code(k)}: {v}'] for k, v in sorted(counts.items())], 'Typen')
    else:
        L += ['nicht verfügbar (`manifest.templateCounts` fehlt)', '']
    w = d['warnings']['added']
    L += [f'## Warnungen ({len(w)})', '']
    if w:
        _block(L, None, [[f'- {_text(x)}'] for x in w], 'Warnungen')
    else:
        L += ['keine Warnungen', '']
    langs = d['localization']['languages']
    L += ['## Lokalisierung', '', f'{len(langs)} Sprachen: ' + ', '.join(f"{k} ({e['newCount']})" for k, e in langs.items()), '']
    _render_coverage(d, L)


def render_changes_md(diff: dict) -> str:
    """CHANGES.md (German) for a diff_versions() result."""
    L: list[str] = []
    if diff['first']:
        _render_first(diff, L)
        return '\n'.join(L).rstrip() + '\n'
    o, n = diff['old'], diff['new']
    L += [f"# Änderungen {o['version']} → {n['version']}", '', '| | alt | neu |', '|---|---|---|']
    L += [f'| {label} | {_cnt(o.get(k))} | {_cnt(n.get(k))} |' for label, k in HEADER_ROWS
          if o.get(k) is not None or n.get(k) is not None] + ['']
    _render_notice(diff, L)
    L += ['## Übersicht', '', '| Bereich | alt | neu | + | − | ~ |', '|---|---:|---:|---:|---:|---:|']
    for s in diff['sections']:
        cmp_ = s['comparable']
        L.append(f"| {s['title']} | {_cnt(s['oldCount'])} | {_cnt(s['newCount'])} | "
                 + ' | '.join(str(len(s[k])) if cmp_ else '–' for k in ('added', 'removed', 'changed')) + ' |')
    L.append('')
    w = diff['warnings']
    wtxt = f"{len(w['added'])} neu, {len(w['removed'])} entfallen"
    if not diff['hasChanges']:
        if diff['warningsChanged']:
            L += [f'**Ergebnis: keine Datenänderungen** (nur Warnungen geändert: {wtxt} – siehe „Warnungen“).', '']
        else:
            L += ['**Ergebnis: keine Datenänderungen** (auch die Warnungen sind unverändert; abgesehen von `generatedAt`).', '']
    else:
        loc, f, tf = diff['localization'], diff['fields'], diff['templateFields']
        nloc = sum(1 for e in loc['languages'].values() if e.get('added') or e.get('removed') or e.get('changed'))
        notes = [f"Warnungen: {wtxt}",
                 f"Lokalisierung: {nloc} Sprache(n) mit geänderten Strings"
                 + (f", {len(loc['added'])} neue Sprache(n)" if loc['added'] else '')]
        if tf['types']:
            notes.append(f"Template-Felder: {sum(len(e['added']) for e in tf['types'])} neu / "
                         f"{sum(len(e['removed']) for e in tf['types'])} entfernt in {len(tf['types'])} Typ(en) (siehe unten)")
        if f['added'] or f['removed']:
            notes.append(f"Export-Format: {len(f['added'])} neue / {len(f['removed'])} entfernte Felder (siehe unten)")
        miss = (loc.get('newEntries') or {}).get('missing') or {}
        for lang, label in COVERAGE_LANGS:
            if miss.get(lang):
                notes.append(f"{len(miss[lang])} neue Einträge ohne {label} ({lang}.json, siehe „Lokalisierung“)")
        L += [f'- {x}' for x in notes] + ['']
    for s in diff['sections']:
        _render_section(s, diff, L)
    _render_templates(diff, L)
    _render_template_fields(diff, L)
    _render_warnings(diff, L)
    _render_localization(diff, L)
    _render_fields(diff, L)
    return '\n'.join(L).rstrip() + '\n'


# ---------------------------------------------------------------- helpers for the export command / CLI

def write_changes(old_dir: Path | str | None, new_dir: Path | str, out: Path | str | None = None,
                  json_out: Path | str | None = None) -> Path:
    d = diff_versions(old_dir, new_dir)
    target = Path(out) if out else Path(new_dir) / 'CHANGES.md'
    target.write_text(render_changes_md(d), encoding='utf-8')
    if json_out:
        Path(json_out).write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='diff', description='compare two export version folders and write CHANGES.md (German)')
    ap.add_argument('old_dir', help="older version folder (e.g. out/v0.6.0.26518) or 'none' for the first export")
    ap.add_argument('new_dir', help='newer version folder')
    ap.add_argument('--out', help='output file (default: <new_dir>/CHANGES.md)')
    ap.add_argument('--json', dest='json_out', help='also write the structured diff as JSON to this file')
    args = ap.parse_args(argv)
    old = None if args.old_dir.lower() == 'none' else Path(args.old_dir)
    for p in (old, Path(args.new_dir)):
        if p is not None and not (p / 'manifest.json').is_file():
            print(f'not an export version folder (manifest.json missing): {p}', file=sys.stderr)
            return 2
    target = write_changes(old, args.new_dir, args.out, args.json_out)
    print(f'written to {target}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
