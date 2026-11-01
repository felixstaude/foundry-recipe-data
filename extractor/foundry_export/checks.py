"""'Nothing may silently drop' checks: template types / fields vs. a committed baseline, and count changes
vs. the previous export.

Works on plain data so that any template source fits (YAML dump or main bundle):
    res = scan(source.type_names(), source.load)        # or scan_yaml_dir(gp.templates, errors)
    warnings += template_warnings(res, load_baseline(), template_source=...)
    warnings += count_warnings(prev_manifest, files, template_counts(res), prev_name=...)

The baseline (baseline/known_templates.json) lists every template type with its count and all field paths
(no values). It is rewritten only after a reviewed game update (write_baseline).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

import yaml

try:
    _Loader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - libyaml missing
    _Loader = yaml.SafeLoader

# the template types build.py reads (keep in sync with build.Data)
EXPORTED_TYPES = ('ItemTemplate', 'ElementTemplate', 'CraftingTag', 'CraftingRecipe', 'BuildableObjectTemplate',
                  'ResearchTemplate', 'ExplorationUnlockTemplate', 'AssemblyLineObjectTemplate',
                  'AssemblyLineProducerActionTemplate', 'ItemCategoryTemplate', 'CreativeModeCategoryTemplate')
# decoded Odin AssemblyLineStages (the robot "recipes"), scanned like a template type and treated as exported
STAGES_TYPE = 'AssemblyLineStages'
# fields build.py branches on: a value never seen before must be reported, not silently fall through
# ('|' = flag combination, split into single names)
ENUM_FIELDS = {
    'ItemTemplate': ('flags|', 'toggleableModeType'),
    'BuildableObjectTemplate': ('type', 'producerRecipeType', 'powerComponentType', 'powerSubType', 'poleGridType',
                                'al_producer_machineType'),
    'ResearchTemplate': ('flags|', 'researchContext'),
    'ExplorationUnlockTemplate': ('unlockFlags|',),
    'ElementTemplate': ('flags|', 'fuel_flags|'),
}
BASELINE_PATH = Path(__file__).parent / 'baseline' / 'known_templates.json'
BASELINE_FORMAT = 'foundry-export/known-templates@1'
MAX_DEPTH = 8                  # nested dict levels recorded by field_paths (current game: max 6)
_TRAILING_LIST = re.compile(r'(\[\])+$')
# the game's TemplateExporter writes a bare '-' scalar unquoted ('planetInfo: -'), which is invalid YAML
_BARE_DASH = re.compile(r'^([ \t]*(?:-[ \t]+)?[\w$.]+):[ \t]+-[ \t]*$', re.M)


# ---------------------------------------------------------------- scanning

def field_paths(body, max_depth: int = MAX_DEPTH) -> set[str]:
    """Key paths of one template body: 'a', 'a.b' for nested dicts, 'a[].b' for dicts inside lists ('a[][].b' for
    lists of lists). Values are ignored; dicts nested deeper than max_depth are not descended into."""
    out: set[str] = set()

    def walk(v, prefix: str, depth: int) -> None:
        if isinstance(v, dict):
            if depth >= max_depth:
                return
            for k, x in v.items():
                p = f'{prefix}.{k}' if prefix else str(k)
                out.add(p)
                walk(x, p, depth + 1)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, (dict, list)):
                    walk(x, prefix + '[]', depth)

    walk(body, '', 0)
    return out


def _parent(path: str) -> str | None:
    head = path.rpartition('.')[0]
    return _TRAILING_LIST.sub('', head) if head else None


def scan(type_names: Iterable[str], load: Callable[[str], dict]) -> dict:
    """{type: {'count': n, 'fields': {path: n_templates_having_it}}}; a type whose load() raises gets
    {'count': 0, 'fields': {}, 'error': msg} (reported by template_warnings, skipped for field checks)."""
    out = {}
    for t in sorted(set(type_names)):
        try:
            templates = load(t)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one broken type must not kill the export
            out[t] = {'count': 0, 'fields': {}, 'error': (str(e).strip().splitlines() or [type(e).__name__])[0]}
            continue
        fields: dict[str, int] = {}
        for body in templates.values():
            for p in field_paths(body):
                fields[p] = fields.get(p, 0) + 1
        out[t] = {'count': len(templates), 'fields': dict(sorted(fields.items()))}
    return out


def scan_stages(stages: dict[str, list]) -> dict:
    """Scan entry for the decoded AssemblyLineStages ({ALOT identifier: [stage, ...]}), same shape as scan()."""
    return scan([STAGES_TYPE], lambda _t: {k: {'stages': v} for k, v in stages.items()})


def enum_values(load: Callable[[str], dict]) -> dict[str, dict[str, int]]:
    """{'Type.field': {value: n_templates}} for ENUM_FIELDS (types that fail to load are skipped)."""
    out: dict[str, dict[str, int]] = {}
    for t, fields in ENUM_FIELDS.items():
        try:
            templates = load(t)
        except (Exception, SystemExit):  # noqa: BLE001 - reported by scan()
            continue
        for spec in fields:
            name, split = spec.rstrip('|'), spec.endswith('|')
            counts: dict[str, int] = {}
            for body in templates.values():
                v = body.get(name)
                if v is None:
                    continue
                vals = [x.strip() for x in str(v).split('|') if x.strip()] if split else [str(v)]
                for x in vals:
                    counts[x] = counts.get(x, 0) + 1
            out[f'{t}.{name}'] = dict(sorted(counts.items()))
    return out


def enum_warnings(values: dict[str, dict[str, int]], baseline: dict | None) -> list[str]:
    """'new-enum-value:' / 'removed-enum-value:' against baseline['enumValues']."""
    known = (baseline or {}).get('enumValues')
    if known is None:
        return [] if baseline is None else ['baseline: known_templates.json has no enumValues - enum checks skipped']
    out = []
    for key, vals in sorted(values.items()):
        old = set(known.get(key, []))
        out += [f'new-enum-value: {key} = {v} ({n} templates)' for v, n in vals.items() if v not in old]
        out += [f'removed-enum-value: {key} = {v}' for v in sorted(old - set(vals))]
    return out


def template_counts(scan_result: dict) -> dict[str, int]:
    """{type: count} for the manifest ('templateCounts'); types that failed to load are left out."""
    return {t: v['count'] for t, v in sorted(scan_result.items()) if 'error' not in v}


def _load_yaml_file(f: Path) -> dict:
    txt = f.read_text(encoding='utf-8')
    try:
        return yaml.load(txt, Loader=_Loader) or {}
    except yaml.YAMLError:
        fixed = _BARE_DASH.sub(r'\1: "-"', txt)
        if fixed == txt:
            raise
        return yaml.load(fixed, Loader=_Loader) or {}


def yaml_dir_source(templates_dir: Path, errors: list[str] | None = None) -> tuple[list[str], Callable[[str], dict]]:
    """(type_names, load) over StreamingAssets/Templates/<Type>/*.yaml. Unparseable files are skipped and
    reported to `errors` as 'source: ...' warnings."""
    root = Path(templates_dir)
    names = sorted(d.name for d in root.iterdir() if d.is_dir())

    def load(type_name: str) -> dict:
        out = {}
        for f in sorted((root / type_name).glob('*.yaml')):
            try:
                doc = _load_yaml_file(f)
            except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
                if errors is not None:
                    errors.append(f'source: cannot parse {type_name}/{f.name}: {str(e).splitlines()[0]}')
                continue
            for ident, body in (doc.get(type_name) or {}).items():
                body = dict(body or {})
                body.setdefault('identifier', ident)
                out[body['identifier']] = body
        return out

    return names, load


def scan_yaml_dir(templates_dir: Path, errors: list[str] | None = None) -> dict:
    """scan() over the game's YAML template dump (interim until sources.TemplateSource is wired in)."""
    return scan(*yaml_dir_source(templates_dir, errors))


# ---------------------------------------------------------------- baseline

def load_baseline(path: Path | None = None) -> dict | None:
    """The committed baseline, or None if the file does not exist."""
    p = Path(path) if path else BASELINE_PATH
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def write_baseline(scan_result: dict, path: Path | None = None, game_version: str | None = None,
                   template_source: str | None = None, enums: dict[str, dict[str, int]] | None = None) -> Path:
    """Writes a stable, sorted baseline (types, counts, field paths; no values). Types that failed to load
    are refused, so a broken scan cannot silently become the new truth."""
    broken = sorted(t for t, v in scan_result.items() if 'error' in v)
    if broken:
        raise ValueError(f'cannot write baseline, template types failed to load: {", ".join(broken)}')
    types = {t: {'count': v['count'], 'fields': sorted(v['fields'])} for t, v in sorted(scan_result.items())}
    doc = {'format': BASELINE_FORMAT, 'gameVersion': game_version, 'templateSource': template_source,
           'typeCount': len(types), 'fieldCount': sum(len(v['fields']) for v in types.values()),
           'enumValues': {k: sorted(v) for k, v in sorted((enums or {}).items())}, 'types': types}
    p = Path(path) if path else BASELINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return p


# ---------------------------------------------------------------- warnings

def _topmost(paths: set[str]) -> list[str]:
    """Drops paths whose parent is in the set too (a new list 'a' also brings 'a[].b' - report 'a' once)."""
    def covered(p: str) -> bool:
        q = _parent(p)
        while q:
            if q in paths:
                return True
            q = _parent(q)
        return False
    return sorted(p for p in paths if not covered(p))


def template_warnings(scan_result: dict, baseline: dict | None, template_source: str | None = None) -> list[str]:
    """new/removed template types and unknown/removed fields vs. the baseline. Exported types get one warning
    per field; other types one grouped line per type."""
    if baseline is None:
        return ['baseline: known_templates.json missing, template type/field checks skipped']
    known = baseline.get('types', {})
    out = []
    for t, v in sorted(scan_result.items()):
        if 'error' in v:
            out.append(f'source: cannot scan {t}: {v["error"]}')
            continue
        exported = t in EXPORTED_TYPES or t == STAGES_TYPE
        if t not in known:
            out.append(f'new-template-type: {t} ({v["count"]} templates{"" if exported else ", not exported"})')
            continue
        cur, old = set(v['fields']), set(known[t].get('fields', []))
        new, gone = _topmost(cur - old), _topmost(old - cur)
        if exported:
            out += [f'unknown-field: {t}.{p} ({v["fields"][p]} templates), not read by the extractor' for p in new]
            out += [f'removed-field: {t}.{p}' for p in gone]
        else:
            if new:
                out.append(f'unknown-field: {t}: {", ".join(new)}')
            if gone:
                out.append(f'removed-field: {t}: {", ".join(gone)}')
    out += [f'removed-template-type: {t}' for t in sorted(set(known) - set(scan_result))]
    bsrc = baseline.get('templateSource')
    if template_source and bsrc and template_source != bsrc and any(w.split(':')[0].endswith('-field') for w in out):
        out.append(f'source: templates read from {template_source} but baseline was taken from {bsrc} '
                   '(field names were identical in 0.6.0.26518; check the field warnings by hand)')
    return out


def _change(name: str, old: int, new: int | None, threshold: float, label: str) -> str | None:
    if new is None:
        return f'count-change: {name} {old} -> 0 (missing) vs {label}'
    if old == new:
        return None
    if old == 0:
        return f'count-change: {name} 0 -> {new} (new) vs {label}'
    rel = (new - old) / old
    if abs(rel) <= threshold:
        return None
    return f'count-change: {name} {old} -> {new} ({rel * 100:+.1f} %) vs {label}'


def count_warnings(prev_manifest: dict | None, files: dict[str, dict], template_counts: dict[str, int] | None,
                   threshold: float = 0.2, prev_name: str | None = None) -> list[str]:
    """Count changes > threshold (relative) vs. the previous export's manifest: output files (count) and, if the
    previous manifest has 'templateCounts', template types. Vanished entries always warn; entries that are new
    in this export are not compared (new types are reported by template_warnings)."""
    if not prev_manifest:
        return []
    label = prev_name or prev_manifest.get('version') or f'v{prev_manifest.get("gameVersion", "?")}'
    out = []
    for name, info in sorted((prev_manifest.get('files') or {}).items()):
        new = files.get(name)
        w = _change(name, int(info.get('count', 0)), None if new is None else int(new['count']), threshold, label)
        if w:
            out.append(w)
    prev_tc = prev_manifest.get('templateCounts')
    if isinstance(prev_tc, dict):
        cur_tc = template_counts or {}
        for t, old in sorted(prev_tc.items()):
            w = _change(t, int(old), None if t not in cur_tc else int(cur_tc[t]), threshold, label)
            if w:
                out.append(w)
    return out


# ---------------------------------------------------------------- previous export

def version_key(name: str) -> tuple:
    """Sort key for 'v0.6.0.26518'-style names (numeric parts numerically, robust against non-numeric parts).
    'v0.6.0.26518-b123' (same version.txt, other Steam build) sorts right after 'v0.6.0.26518'."""
    return tuple((0, int(x), '') if x.isdigit() else (1, 0, x) for x in name.lstrip('v').replace('-b', '.').split('.'))


def previous_version(out_dir: Path, current_version_dir_name: str) -> tuple[str, dict] | None:
    """(name, manifest) of the newest version in out_dir/index.json that sorts before the current one and has a
    readable manifest.json; None if there is none."""
    root = Path(out_dir)
    try:
        index = json.loads((root / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    cur = version_key(current_version_dir_name)
    names = {v['version'] for v in index.get('versions', [])
             if isinstance(v, dict) and isinstance(v.get('version'), str)}
    for name in sorted((n for n in names if n != current_version_dir_name and version_key(n) < cur),
                       key=version_key, reverse=True):
        try:
            manifest = json.loads((root / name / 'manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict):
            return name, manifest
    return None
