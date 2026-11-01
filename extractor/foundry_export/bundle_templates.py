"""Fallback template source: FoundryTemplate ScriptableObjects read directly from foundry_main_bundle.

Reproduces what yaml.load(CSafeLoader) yields for the game's own TemplateExporter dump
(StreamingAssets/Templates/<Type>/<identifier>.yaml), see decompiled TemplateExporter.runExportAll,
TweakManager.createYamlFromTemplate and C3.ModKit.Yaml.YamlConverter / YamlValue / Enum(Flags)YamlConverter:
  * types: MonoBehaviour m_Script -> MonoScript m_ClassName (== Templates folder name); templates are the
    subclasses of C3.FoundryTemplate minus TrainTrackTemplate/TrainTrackSetTemplate/(TrainTrack)SplineDataContainer,
    filtered by includeInBuild && includeIngame
  * fields: public instance fields without [NonSerialized]/[HideInInspector], derived class first; public fields
    Unity does not serialize (not in the type tree) are null; null references to native engine objects are
    omitted at top level (the editor holds "fake null" objects there)
  * only assets listed in the bundle's m_Container count (AssetManager registers AssetBundle.LoadAllAssets());
    templates that are merely bundled as dependencies are not part of the game (nor of the dump)
  * values: enum names, [Flags] combos ('A|B', '' for 0), True/False, .NET 'G7' float formatting, nested
    classes, lists, references -> 'identifier|' (templates) or '<asset path>|' (m_Container path in original case
    from <bundle>.abdb / .manifest; the dump's '|<guid>' suffix is not available in the bundle)
  * every scalar is resolved like PyYAML would resolve the exporter's (plain or double-quoted) output

Managed type metadata (field visibility, attributes, enums) comes from the game's Managed/*.dll when present,
else from the committed table data/managed_types.json (regenerate with extractor/tools/gen_enums.py).
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import yaml

from .typetree import (FIELD_NOT_SERIALIZED, FIELD_PUBLIC, ClrAssembly, Field, PPtr, build_tree, compile_field)
from .unity_bundle import SerializedFile, UnityFSBundle

try:
    _Loader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - libyaml missing
    _Loader = yaml.SafeLoader

FOUNDRY_TEMPLATE = 'C3.FoundryTemplate'
EXCLUDED_TYPES = frozenset({'TrainTrackTemplate', 'TrainTrackSetTemplate', 'SplineDataContainer',
                            'TrainTrackSplineDataContainer'})
TEMPLATE_BASE_FIELDS = ['includeIngame', 'includeInBuild', 'includeInDemo', 'buildTags', 'identifier']
# MonoBehaviour header + non-exported FoundryTemplate fields (private / [HideInInspector])
_TEMPLATE_INTERNALS = frozenset({'m_GameObject', 'm_Enabled', 'm_Script', 'm_Name', 'includeIngame', 'includeInBuild',
                                 'includeInDemo', 'modIdentifier', 'serializedOriginal'})
UNITY_OBJECT = 'UnityEngine.Object'
SCRIPT_BASES = frozenset({'UnityEngine.MonoBehaviour', 'UnityEngine.ScriptableObject'})
LIST_TYPE = 'System.Collections.Generic.List`1'
INT_VECTORS = {'UnityEngine.Vector2Int': ('x', 'y'), 'UnityEngine.Vector3Int': ('x', 'y', 'z')}
TABLE_FILE = Path(__file__).parent / 'data' / 'managed_types.json'
_GAME_ASSEMBLIES = ('Main', 'Channel3', 'Assembly-CSharp', 'UnityEngine.CoreModule')


# ---------------------------------------------------------------- managed type table

class TypeTable:
    """Managed type metadata needed to emulate the exporter: {full name: entry | None (unknown)}.

    entry = {'base': name|None, 'valuetype': bool,
             'enum': {'flags': bool, 'values': [[name, value], ...]}            (enums only)
             'fields': [[name, sig], ...]   public, serializable, not hidden    (declaration order)
             'skip': [name, ...]}           other instance fields (private / [NonSerialized] / [HideInInspector])
    """

    def __init__(self, types: dict[str, dict | None], origin: str, game_version: str | None = None,
                 snapshot: bool = False):
        self.types, self.origin = types, origin
        self.game_version, self.snapshot = game_version, snapshot  # snapshot: committed table, not live DLLs
        self._yaml_fields: dict[str, list] = {}
        self._field_names: dict[str, frozenset] = {}

    # -- construction
    @classmethod
    def from_managed(cls, managed_dir: Path, roots: list[str] | None = None) -> 'TypeTable':
        loader = _AssemblyLoader(Path(managed_dir))
        if roots is None:
            roots = loader.subclasses(FOUNDRY_TEMPLATE)
        return cls(_collect(loader.lookup, roots), f'{managed_dir.name}/*.dll')

    @classmethod
    def from_json(cls, path: Path = TABLE_FILE) -> 'TypeTable':
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls(doc['types'], f'{Path(path).name} (game {doc.get("gameVersion")})', doc.get('gameVersion'), True)

    def to_json(self, game_version: str | None) -> str:
        head = {'comment': 'Derived managed type metadata (names, enum values, field visibility) for the '
                           'foundry_main_bundle template fallback; generated by extractor/tools/gen_enums.py',
                'gameVersion': game_version}
        lines = [f'{json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(",", ":"))}'
                 for k, v in sorted(self.types.items())]  # one type per line: readable diffs
        return json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',\n "types": {\n' + ',\n'.join(lines) + '\n}}\n'

    # -- queries
    def chain(self, name: str | None) -> list[str]:
        out = []
        while name and name not in out:
            out.append(name)
            e = self.types.get(name)
            name = e.get('base') if e else None
        return out

    def is_template(self, name: str) -> bool | None:
        if self.types.get(name) is None:
            return None
        return FOUNDRY_TEMPLATE in self.chain(name)

    def object_kind(self, name: str) -> str | None:
        """'script' (MonoBehaviour/ScriptableObject subclass), 'native' (engine object) or None."""
        ch = self.chain(name)
        if UNITY_OBJECT not in ch:
            return None
        return 'script' if SCRIPT_BASES & set(ch) else 'native'

    def yaml_fields(self, name: str) -> list | None:
        """[(field name, sig)] in reflection order (declaring class first, then base classes)."""
        if name in self._yaml_fields:
            return self._yaml_fields[name]
        if self.types.get(name) is None:
            return None
        out = []
        for n in self.chain(name):
            e = self.types.get(n)
            if e:
                out += [tuple(f) for f in e.get('fields', ())]
        self._yaml_fields[name] = out
        return out

    def field_names(self, name: str) -> frozenset:
        """All instance field names (exported or not) of a type and its bases."""
        if name not in self._field_names:
            names = set()
            for n in self.chain(name):
                e = self.types.get(n)
                if e:
                    names.update(f[0] for f in e.get('fields', ()))
                    names.update(e.get('skip', ()))
            self._field_names[name] = frozenset(names)
        return self._field_names[name]


class _AssemblyLoader:
    def __init__(self, managed: Path):
        self.dir, self.loaded, self.where = managed, {}, {}
        self.files = {p.stem: p for p in managed.glob('*.dll')}
        for a in _GAME_ASSEMBLIES:
            self._load(a)

    def _load(self, name: str) -> ClrAssembly | None:
        if name in self.loaded:
            return self.loaded[name]
        p = self.files.get(name)
        asm = None
        if p is not None:
            try:
                asm = ClrAssembly(p)
            except (ValueError, struct.error, IndexError, KeyError):
                asm = None
        self.loaded[name] = asm
        if asm:
            for tn, scope in zip(asm.typeref_names, asm.typeref_scopes):
                if scope:
                    self.where.setdefault(tn, scope)
        return asm

    def lookup(self, name: str) -> dict | None:
        for asm in list(self.loaded.values()):
            if asm and name in asm.types:
                return asm.types[name]
        scope = self.where.get(name)
        if scope and scope not in self.loaded:
            asm = self._load(scope)
            if asm and name in asm.types:
                return asm.types[name]
        return None

    def subclasses(self, base: str) -> list[str]:
        """Direct and indirect subclasses of `base` defined in the game assemblies."""
        out = []
        for name in _GAME_ASSEMBLIES:
            asm = self.loaded.get(name)
            for n in (asm.types if asm and not name.startswith('UnityEngine.') else ()):
                seen, cur = set(), n
                while cur and cur not in seen and not cur.startswith('System.'):
                    seen.add(cur)
                    info = self.lookup(cur)
                    cur = info['base'] if info else None
                    if cur == base:
                        out.append(n)
                        break
        return sorted(set(out))


def _sig_types(sig) -> list[str]:
    k = sig[0]
    if k in ('class', 'valuetype'):
        return [sig[1]] if sig[1] else []
    if k == 'array':
        return _sig_types(sig[1])
    if k == 'generic':
        out = [] if sig[1] == LIST_TYPE else [sig[1]]
        for a in sig[2]:
            out += _sig_types(a)
        return out
    return []


def _is_yaml_field(f: dict) -> bool:
    return (f['flags'] & 7) == FIELD_PUBLIC and not f['flags'] & FIELD_NOT_SERIALIZED and not f['hide']


def _collect(lookup, roots: list[str]) -> dict[str, dict | None]:
    """Closure of the types reachable from the template classes through exporter-visible fields."""
    out: dict[str, dict | None] = {}
    raw: dict[str, dict | None] = {}

    def get(n):
        if n not in raw:
            raw[n] = None if n.startswith('System.') else lookup(n)  # BCL types: opaque
        return raw[n]

    def chain(n):
        res = []
        while n and n not in res:
            res.append(n)
            info = get(n)
            n = info['base'] if info else None
        return res

    todo = list(roots)
    while todo:
        n = todo.pop()
        if n in out:
            continue
        info = get(n)
        if info is None:
            if not n.startswith('System.'):
                out[n] = None
            continue
        e = {'base': info['base'], 'valuetype': info['valuetype']}
        ch = chain(n)
        if info['enum']:
            e['enum'] = {'flags': info['enum']['flags'], 'values': [list(v) for v in info['enum']['values']]}
        elif UNITY_OBJECT not in ch or FOUNDRY_TEMPLATE in ch:  # engine objects: base chain only
            e['fields'] = [[f['name'], f['sig']] for f in info['fields'] if _is_yaml_field(f)]
            e['skip'] = [f['name'] for f in info['fields'] if not _is_yaml_field(f)]
            for f in e['fields']:
                todo += _sig_types(f[1])
        out[n] = e
        if info['base'] and not info['base'].startswith('System.'):
            todo.append(info['base'])
    return out


def load_type_table(managed_dir: Path | None, warnings: list[str]) -> TypeTable:
    if managed_dir is not None and (Path(managed_dir) / 'Main.dll').exists():
        try:
            return TypeTable.from_managed(Path(managed_dir))
        except Exception as ex:  # noqa: BLE001 - fall back to the committed table
            warnings.append(f'bundle: cannot read managed assemblies ({ex}) - using {TABLE_FILE.name}')
    else:
        warnings.append(f'bundle: managed assemblies not found - using committed {TABLE_FILE.name}')
    return TypeTable.from_json(TABLE_FILE)


# ---------------------------------------------------------------- scalar formatting (exporter -> PyYAML)

_NET_WS = frozenset('\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008'
                    '\u2009\u200a\u2028\u2029\u202f\u205f\u3000')  # char.IsWhiteSpace
_INDICATORS = frozenset('-?:,[]{}#&*!|>\'"%@`')
_resolver = yaml.resolver.Resolver()
_constructor = yaml.constructor.SafeConstructor()
_scalar_cache: dict[str, object] = {}


def yaml_scalar(s: str):
    """The Python value PyYAML (CSafeLoader) yields for YamlValue(s) as written by the exporter."""
    v = _scalar_cache.get(s, _scalar_cache)
    if v is not _scalar_cache:
        return v
    if s == '' or any(c in s for c in '"\\\n\r:') or s[0] in _NET_WS or s[-1] in _NET_WS:
        v = s  # written double-quoted with \\ \r \n \" escapes -> exact round trip
    elif s[0] in _INDICATORS or ' #' in s or '\t#' in s or any(c in s for c in '\x85\u2028\u2029\ufeff'):
        try:  # plain scalar with YAML syntax meaning: let the parser decide, as for the real dump
            v = yaml.load('k: ' + s + '\n', Loader=_Loader)['k']
        except yaml.YAMLError:
            v = s  # the dump file would not be parseable at all; keep the text
    else:
        tag = _resolver.resolve(yaml.ScalarNode, s, (True, False))
        ctor = _constructor.yaml_constructors.get(tag) if tag != 'tag:yaml.org,2002:str' else None
        try:
            v = ctor(_constructor, yaml.ScalarNode(tag, s)) if ctor else s
        except (yaml.YAMLError, ValueError, TypeError):  # e.g. '<<' / '=' (merge / value tags)
            v = s
    if isinstance(v, (str, int, float, bool, type(None))):
        _scalar_cache[s] = v
    return v


def net_single(x: float) -> str:
    """System.Single.ToString(CultureInfo.InvariantCulture) of the Unity Mono runtime ('G', 7 digits)."""
    return _net_general(x, 7)


def net_double(x: float) -> str:
    return _net_general(x, 15)


def _net_general(x: float, prec: int) -> str:
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0'
    s = format(x, f'.{prec}g')
    if 'e' in s:
        mant, exp = s.split('e')
        s = f'{mant}E{exp[0]}{int(exp[1:]):02d}'
    return s


# ---------------------------------------------------------------- bundle source

class BundleTemplates:
    """All FoundryTemplate types of foundry_main_bundle; load(type) mimics the YAML dump."""

    def __init__(self, bundle: UnityFSBundle | str, managed_dir: Path | None = None,
                 warnings: list[str] | None = None, table: TypeTable | None = None, game_version: str | None = None):
        self.bundle = bundle if isinstance(bundle, UnityFSBundle) else UnityFSBundle(str(bundle))
        self.warnings = warnings if warnings is not None else []
        self.table = table or load_type_table(managed_dir, self.warnings)
        # enum values missing from a committed table of another game version may be new names -> warn
        self.table_is_snapshot = self.table.snapshot and self.table.game_version != game_version
        self.sf: SerializedFile = next(s for s in self.bundle.serialized_files() if s.objects)
        self._classes = self._script_classes()
        self._readers: dict[int, tuple] = {}
        self._values: dict[int, dict] = {}
        self._paths: dict[int, str] | None = None
        self._explicit: set[int] | None = None
        self._raw: dict[int, bytes] = {}
        self._ident_cache: dict[int, str | None] = {}
        self._prefetched = False
        self._cache: dict[str, dict[str, dict]] = {}
        self._warned: set[str] = set()
        self._types = self._template_types()

    # -- type discovery
    def _script_classes(self) -> dict[int, tuple[str, str]]:
        """SerializedType index -> (full class name, class name) via m_Script -> MonoScript."""
        sf = self.sf
        ms_idx = [i for i, t in enumerate(sf.types) if t.class_id == 115]
        scripts = {}
        if ms_idx:
            rd = compile_field(build_tree(sf.types[ms_idx[0]].nodes), sf.little)
            for o in sf.objects.values():
                if o.class_id == 115:
                    v, _ = rd(sf.object_bytes(o.path_id), 0)
                    full = f'{v["m_Namespace"]}.{v["m_ClassName"]}' if v['m_Namespace'] else v['m_ClassName']
                    scripts[o.path_id] = (full, v['m_ClassName'])
        out = {}
        for i, t in enumerate(sf.types):
            if t.class_id == 114 and 0 <= t.script_type_index < len(sf.script_types):
                fidx, pid = sf.script_types[t.script_type_index]
                if fidx == 0 and pid in scripts:
                    out[i] = scripts[pid]
        return out

    def _template_types(self) -> dict[str, tuple[str, list[int]]]:
        """class name -> (full name, [SerializedType indices])."""
        out: dict[str, tuple[str, list[int]]] = {}
        for i, (full, short) in self._classes.items():
            if short in EXCLUDED_TYPES:
                continue
            is_t = self.table.is_template(full)
            if is_t is None:  # unknown to the metadata: recognise the FoundryTemplate field layout
                names = [c.name for c in build_tree(self.sf.types[i].nodes).children]
                is_t = names[4:9] == TEMPLATE_BASE_FIELDS
                if is_t:
                    self._warn(f'bundle: template type {full} not in managed type metadata ({self.table.origin}) '
                               f'- enum fields stay numeric')
            if is_t:
                out.setdefault(short, (full, []))[1].append(i)
        return out

    def type_names(self) -> list[str]:
        """Template types with at least one registered asset (the dump has one folder per such type)."""
        explicit = self.explicit_assets()
        used = {o.type_index for o in self.sf.objects.values() if o.class_id == 114 and o.path_id in explicit}
        return sorted(t for t, (_full, idx) in self._types.items() if used.intersection(idx))

    # -- loading
    def load(self, type_name: str) -> dict[str, dict]:
        if type_name in self._cache:
            return self._cache[type_name]
        if type_name not in self._types:
            raise KeyError(f'template type {type_name} not found in {Path(self.bundle.path).name}')
        full, tidx = self._types[type_name]
        self._prefetch()
        explicit = self.explicit_assets()  # AssetManager registers AssetBundle.LoadAllAssets() = m_Container assets
        objs = sorted((o for o in self.sf.objects.values() if o.type_index in tidx and o.path_id in explicit),
                      key=lambda o: o.byte_start)
        found: dict[str, tuple[str, int, dict]] = {}
        for o in objs:
            raw = self._read(o.path_id)
            if not (raw.get('includeInBuild', True) and raw.get('includeIngame', True)):
                continue  # TemplateExporter: shouldIncludeInBuild() && shouldIncludeInGame()
            ident = str(raw.get('identifier'))
            fname = (ident + '.yaml').lower()  # one file per identifier (case-insensitive file system)
            if fname in found:
                self._warn(f'bundle: duplicate template file {type_name}/{ident}.yaml (path ids '
                           f'{found[fname][1]}, {o.path_id}) - keeping the first')
                continue
            body = self._convert_template(full, raw)
            body.setdefault('identifier', ident)
            found[fname] = (ident + '.yaml', o.path_id, body)
        out = {}
        for _name, _pid, body in sorted(found.values(), key=lambda x: x[0]):  # sorted(glob('*.yaml'))
            out[body['identifier']] = body
        self._cache[type_name] = out
        return out

    def _read(self, pid: int) -> dict:
        v = self._values.get(pid)
        if v is None:
            o = self.sf.objects[pid]
            rd = self._readers.get(o.type_index)
            if rd is None:
                root = build_tree(self.sf.types[o.type_index].nodes)
                rd = self._readers[o.type_index] = (root, compile_field(root, self.sf.little))
            raw = self._raw.pop(pid, None)
            v, _ = rd[1](raw if raw is not None else self.sf.object_bytes(pid), 0)
            self._values[pid] = v
        return v

    def _identifier(self, pid: int) -> str | None:
        """FoundryTemplate.identifier of a referenced object, reading only the start of large objects."""
        if pid in self._values or pid in self._raw:
            v = self._read(pid).get('identifier')
            return v if isinstance(v, str) else None
        if pid not in self._ident_cache:
            o = self.sf.objects[pid]
            root = build_tree(self.sf.types[o.type_index].nodes)
            names = [c.name for c in root.children]
            v = None
            if 'identifier' in names:
                head = Field(root.type, root.name, root.meta_flag, False, -1,
                             root.children[:names.index('identifier') + 1])
                rd = compile_field(head, self.sf.little)
                size = 4096
                start = self.sf.node.offset + self.sf.data_offset + o.byte_start
                while True:
                    buf = self.sf.bundle.read(start, min(size, o.byte_size))
                    try:
                        val, end = rd(buf, 0)
                        if end <= len(buf):
                            v = val['identifier']
                            break
                    except (struct.error, IndexError, ValueError):
                        pass
                    if size >= o.byte_size:
                        break
                    size *= 8
            self._ident_cache[pid] = v if isinstance(v, str) else None
        return self._ident_cache[pid]

    def _prefetch(self):
        """Raw bytes of all template objects in one pass in file order: every LZ4 block is decompressed once."""
        if self._prefetched:
            return
        self._prefetched = True
        tidx = {i for _full, idx in self._types.values() for i in idx}
        explicit = self.explicit_assets()
        objs = sorted((o for o in self.sf.objects.values() if o.type_index in tidx and o.path_id in explicit),
                      key=lambda o: o.byte_start)
        for o in objs:
            if o.path_id not in self._values:
                self._raw[o.path_id] = self.sf.object_bytes(o.path_id)

    def _warn(self, msg: str):
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(msg)

    # -- conversion
    def _convert_template(self, full: str, raw: dict) -> dict:
        return self._object(full, raw, full, top=True)

    def _object(self, name: str, v: dict, where: str, top: bool = False) -> dict:
        """Exporter view of a class/struct value: its public fields (reflection order) from the type tree."""
        fields = self.table.yaml_fields(name)
        engine = name.startswith('UnityEngine.')  # native layout: map public fields, ignore the rest
        out = {}
        for fname, fsig in fields or ():
            key = fname if fname in v else (_engine_field(fname, v) if engine else None)
            if key is None:
                out[fname] = None  # public but not serialized by Unity: runtime value, null in the dump
                continue
            x = v[key]
            if top and isinstance(x, PPtr) and not x and self._object_kind(fsig) == 'native':
                continue  # createYamlFromTemplate skips "fake null" engine object references
            out[fname] = self._conv(x, fsig, f'{where}.{fname}')
        if engine and fields is not None:
            return out
        known = self.table.field_names(name)
        for k, x in v.items():  # serialized but unknown to the metadata (newer game version / unknown type)
            if k in known or (top and k in _TEMPLATE_INTERNALS):
                continue
            if fields is not None or not top:
                self._warn(f'bundle: field {name}.{k} not in managed type metadata ({self.table.origin}) '
                           f'- added without type info')
            out[k] = self._plain(x)
        return out

    def _object_kind(self, sig) -> str | None:
        if sig[0] in ('class', 'valuetype') and sig[1]:
            return self.table.object_kind(sig[1])
        return None

    def _conv(self, v, sig, where: str):
        k = sig[0]
        if k == 'prim':
            t = sig[1]
            if t == 'bool':
                return bool(v)
            if t == 'r4':
                return yaml_scalar(net_single(v))
            if t == 'r8':
                return yaml_scalar(net_double(v))
            if t == 'char':
                return yaml_scalar(chr(v))
            return int(v)
        if k == 'string':
            return yaml_scalar(v) if isinstance(v, str) else None
        if k == 'array' or (k == 'generic' and sig[1] == LIST_TYPE):
            el = sig[1] if k == 'array' else sig[2][0]
            return [self._conv(x, el, where) for x in v] if isinstance(v, list) else None
        if k in ('class', 'valuetype') and sig[1]:
            name = sig[1]
            if isinstance(v, PPtr):
                return self._ref(v)
            e = self.table.types.get(name)
            if e is not None and 'enum' in e and isinstance(v, int):
                return self._enum(v, e['enum'], where)
            if isinstance(v, dict):
                if name == 'UnityEngine.Color32' and 'rgba' in v:  # serialized as one uint
                    c = v['rgba']
                    return {'r': c & 0xFF, 'g': c >> 8 & 0xFF, 'b': c >> 16 & 0xFF, 'a': c >> 24 & 0xFF}
                if name in INT_VECTORS:  # YamlConverter special case (x/y/z properties)
                    return {c: int(v.get('m_' + c.upper(), v.get(c, 0))) for c in INT_VECTORS[name]}
                return self._object(name, v, name)
            if isinstance(v, int) and e is None:
                self._warn(f'bundle: unknown type {name} for {where} ({self.table.origin}) - value kept numeric')
        return self._plain(v)

    def _enum(self, v: int, info: dict, where: str):
        vals = info['values']
        if info['flags']:
            n = v & 0xFFFFFFFFFFFFFFFF
            parts, rest = [], n
            for vn, vv in sorted(vals, key=lambda x: x[1] & 0xFFFFFFFFFFFFFFFF):
                vu = vv & 0xFFFFFFFFFFFFFFFF
                if n & vu:
                    parts.append(_enum_name(vals, vv))
                    rest &= ~vu
            if rest and self.table_is_snapshot:
                self._warn(f'bundle: unknown enum value {rest} for {where}')
            return yaml_scalar('|'.join(parts))
        for vn, vv in vals:
            if vv == v:
                return yaml_scalar(_enum_name(vals, vv))
        if self.table_is_snapshot:  # the committed table may predate this game version
            self._warn(f'bundle: unknown enum value {v} for {where}')
            return str(v)
        return yaml_scalar(str(v))  # Enum.ToString() of an undefined value: the number

    def _plain(self, v):
        """Type-tree value without managed metadata (unknown types)."""
        if isinstance(v, PPtr):
            return self._ref(v)
        if isinstance(v, dict):
            return {k: self._plain(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._plain(x) for x in v]
        if isinstance(v, float):
            return yaml_scalar(net_single(v))
        if isinstance(v, str):
            return yaml_scalar(v)
        return v

    def _ref(self, p: PPtr):
        if not p:
            return None
        if p.file_id != 0:
            ext = self.sf.externals[p.file_id - 1] if p.file_id - 1 < len(self.sf.externals) else '?'
            return yaml_scalar(f'{ext}|')
        o = self.sf.objects.get(p.path_id)
        if o is not None and o.type_index in self._classes:
            full = self._classes[o.type_index][0]
            ident = self._identifier(p.path_id) if self.table.is_template(full) is not False else None
            if ident is not None:
                return yaml_scalar(f'{ident}|')
        return yaml_scalar(f'{self._asset_path(p.path_id)}|')

    def _asset_path(self, pid: int) -> str:
        """Asset path of an object: own m_Container entry, else the prefab its GameObject belongs to."""
        paths = self.asset_paths()
        seen = set()
        while pid not in paths and pid not in seen and pid in self.sf.objects:
            seen.add(pid)
            v = self._read(pid)
            go = v.get('m_GameObject')
            if isinstance(go, PPtr) and go.file_id == 0 and go.path_id in paths:
                return paths[go.path_id]
            if isinstance(go, PPtr) and go.file_id == 0 and go:  # component: continue with its GameObject
                pid = go.path_id
                continue
            comps = v.get('m_Component')  # GameObject: first component is its Transform -> parent
            if not comps:
                break
            first = comps[0].get('component') if isinstance(comps[0], dict) else None
            father = self._read(first.path_id).get('m_Father') if isinstance(first, PPtr) and first else None
            if not (isinstance(father, PPtr) and father and father.file_id == 0):
                break
            pid = father.path_id
        return paths.get(pid, '')

    def explicit_assets(self) -> set[int]:
        if self._explicit is None:
            self._explicit = {pid for pid in self.sf.container().values()}
        return self._explicit

    def asset_paths(self) -> dict[int, str]:
        """path id -> asset path of the m_Container entry (original case from <bundle>.abdb / .manifest)."""
        if self._paths is None:
            case = _original_case_paths(Path(self.bundle.path))
            self._paths = {pid: case.get(key, key) for pid, key in self.sf.container_paths().items()}
        return self._paths


def _original_case_paths(bundle_path: Path) -> dict[str, str]:
    """lower-case -> original asset path from the AssetBundleDB (.abdb, read by AssetManager) and the .manifest."""
    out: dict[str, str] = {}
    mf = bundle_path.with_name(bundle_path.name + '.manifest')
    if mf.exists():
        in_assets = False
        for line in mf.read_text(encoding='utf-8', errors='replace').splitlines():
            if not line.startswith('- '):
                in_assets = line.startswith('Assets:')
                continue
            if in_assets:
                out[line[2:].strip().lower()] = line[2:].strip()
    db = bundle_path.with_name(bundle_path.name + '.abdb')
    if db.exists():
        try:
            for e in json.loads(db.read_text(encoding='utf-8-sig')).get('entries', []):
                if isinstance(e, dict) and isinstance(e.get('path'), str):
                    out[e['path'].lower()] = e['path']
        except ValueError:
            pass
    return out


def _enum_name(vals: list, value: int) -> str:
    return next(n for n, v in vals if v == value)


def _engine_field(name: str, v: dict) -> str | None:
    """Serialized name of a public field of a UnityEngine struct (x -> m_X, m01 -> e01)."""
    matrix = 'e' + name[1:] if name[:1] == 'm' and name[1:].isdigit() else None
    for cand in ('m_' + name[:1].upper() + name[1:], matrix):
        if cand in v:
            return cand
    return None
