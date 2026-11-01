"""Class inventory of the game's managed DLLs without decompiling.

Minimal pure-Python ECMA-335 metadata reader: PE headers -> CLI header -> metadata root -> streams
(#~ or #-, #Strings, #Blob) -> TypeDef / TypeRef / TypeSpec / NestedClass tables. Used to detect new or
removed classes (above all new FoundryTemplate subclasses) after a game update, so UPDATE.md can decide
whether a re-decompile is needed. Baseline: baseline/dll_types.txt ('<Assembly>\\t<Namespace.Type>\\t<Base>').

    python3 -m foundry_export.dll_types diff <game_dir> [--baseline FILE]    # (cwd: extractor/)
    python3 -m foundry_export.dll_types baseline <game_dir> [--out FILE]
    python3 -m foundry_export.dll_types list <dll>
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ASSEMBLIES = ('Main', 'Channel3', 'Assembly-CSharp')
BASELINE = Path(__file__).parent / 'baseline' / 'dll_types.txt'
TEMPLATE_ROOT = 'C3.FoundryTemplate'
_CAP = 5

# ---- ECMA-335 table schema (II.22) -----------------------------------------
# column kinds: 'u2'/'u4' fixed, 'S'/'G'/'B' heap index, int = simple index into that table, str = coded index
_CODED = {  # name: (tag bits, referenced tables)
    'TypeDefOrRef': (2, (0x02, 0x01, 0x1B)),
    'HasConstant': (2, (0x04, 0x08, 0x17)),
    'HasCustomAttribute': (5, (0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11, 0x1A,
                               0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B)),
    'HasFieldMarshal': (1, (0x04, 0x08)),
    'HasDeclSecurity': (2, (0x02, 0x06, 0x20)),
    'MemberRefParent': (3, (0x02, 0x01, 0x1A, 0x06, 0x1B)),
    'HasSemantics': (1, (0x14, 0x17)),
    'MethodDefOrRef': (1, (0x06, 0x0A)),
    'MemberForwarded': (1, (0x04, 0x06)),
    'Implementation': (2, (0x26, 0x23, 0x27)),
    'CustomAttributeType': (3, (0x06, 0x0A)),  # tags 2/3; 0/1/4 unused
    'ResolutionScope': (2, (0x00, 0x1A, 0x23, 0x01)),
    'TypeOrMethodDef': (1, (0x02, 0x06)),
}
_TABLES = (  # only tables up to NestedClass (0x29) are needed to locate the ones we read
    ('u2', 'S', 'G', 'G', 'G'),                           # 00 Module
    ('ResolutionScope', 'S', 'S'),                        # 01 TypeRef
    ('u4', 'S', 'S', 'TypeDefOrRef', 0x04, 0x06),         # 02 TypeDef
    (0x04,),                                              # 03 FieldPtr
    ('u2', 'S', 'B'),                                     # 04 Field
    (0x06,),                                              # 05 MethodPtr
    ('u4', 'u2', 'u2', 'S', 'B', 0x08),                   # 06 MethodDef
    (0x08,),                                              # 07 ParamPtr
    ('u2', 'u2', 'S'),                                    # 08 Param
    (0x02, 'TypeDefOrRef'),                               # 09 InterfaceImpl
    ('MemberRefParent', 'S', 'B'),                        # 0A MemberRef
    ('u2', 'HasConstant', 'B'),                           # 0B Constant (u1 type + u1 pad)
    ('HasCustomAttribute', 'CustomAttributeType', 'B'),   # 0C CustomAttribute
    ('HasFieldMarshal', 'B'),                             # 0D FieldMarshal
    ('u2', 'HasDeclSecurity', 'B'),                       # 0E DeclSecurity
    ('u2', 'u4', 0x02),                                   # 0F ClassLayout
    ('u4', 0x04),                                         # 10 FieldLayout
    ('B',),                                               # 11 StandAloneSig
    (0x02, 0x14),                                         # 12 EventMap
    (0x14,),                                              # 13 EventPtr
    ('u2', 'S', 'TypeDefOrRef'),                          # 14 Event
    (0x02, 0x17),                                         # 15 PropertyMap
    (0x17,),                                              # 16 PropertyPtr
    ('u2', 'S', 'B'),                                     # 17 Property
    ('u2', 0x06, 'HasSemantics'),                         # 18 MethodSemantics
    (0x02, 'MethodDefOrRef', 'MethodDefOrRef'),           # 19 MethodImpl
    ('S',),                                               # 1A ModuleRef
    ('B',),                                               # 1B TypeSpec
    ('u2', 'MemberForwarded', 'S', 0x1A),                 # 1C ImplMap
    ('u4', 0x04),                                         # 1D FieldRVA
    ('u4', 'u4'),                                         # 1E ENCLog
    ('u4',),                                              # 1F ENCMap
    ('u4', 'u2', 'u2', 'u2', 'u2', 'u4', 'B', 'S', 'S'),  # 20 Assembly
    ('u4',),                                              # 21 AssemblyProcessor
    ('u4', 'u4', 'u4'),                                   # 22 AssemblyOS
    ('u2', 'u2', 'u2', 'u2', 'u4', 'B', 'S', 'S', 'B'),   # 23 AssemblyRef
    ('u4', 0x23),                                         # 24 AssemblyRefProcessor
    ('u4', 'u4', 'u4', 0x23),                             # 25 AssemblyRefOS
    ('u4', 'S', 'B'),                                     # 26 File
    ('u4', 'u4', 'S', 'S', 'Implementation'),             # 27 ExportedType
    ('u4', 'u4', 'S', 'Implementation'),                  # 28 ManifestResource
    (0x02, 0x02),                                         # 29 NestedClass
)
_PRIM = {0x01: 'System.Void', 0x02: 'System.Boolean', 0x03: 'System.Char', 0x04: 'System.SByte', 0x05: 'System.Byte',
         0x06: 'System.Int16', 0x07: 'System.UInt16', 0x08: 'System.Int32', 0x09: 'System.UInt32',
         0x0A: 'System.Int64', 0x0B: 'System.UInt64', 0x0C: 'System.Single', 0x0D: 'System.Double',
         0x0E: 'System.String', 0x16: 'System.TypedReference', 0x18: 'System.IntPtr', 0x19: 'System.UIntPtr',
         0x1C: 'System.Object'}
_INTERFACE = 0x20  # TypeAttributes.Interface


def _cuint(b: bytes, p: int) -> tuple[int, int]:
    """ECMA-335 compressed unsigned integer (II.23.2)."""
    x = b[p]
    if x < 0x80:
        return x, p + 1
    if x < 0xC0:
        return ((x & 0x3F) << 8) | b[p + 1], p + 2
    return ((x & 0x1F) << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3], p + 4


class _Metadata:
    def __init__(self, data: bytes):
        u16 = lambda o: struct.unpack_from('<H', data, o)[0]  # noqa: E731
        u32 = lambda o: struct.unpack_from('<I', data, o)[0]  # noqa: E731
        if data[:2] != b'MZ':
            raise ValueError('not a PE file')
        pe = u32(0x3C)
        if data[pe:pe + 4] != b'PE\0\0':
            raise ValueError('PE signature missing')
        nsec, opt_size = u16(pe + 6), u16(pe + 20)
        opt = pe + 24
        plus = u16(opt) == 0x20B
        if u32(opt + (108 if plus else 92)) < 15:
            raise ValueError('no CLI header (native image?)')
        cli_rva = u32(opt + (112 if plus else 96) + 14 * 8)
        if not cli_rva:
            raise ValueError('no CLI header (native image?)')
        secs = [struct.unpack_from('<IIII', data, opt + opt_size + 40 * i + 8) for i in range(nsec)]

        def off(rva: int) -> int:
            for vsize, va, rsize, rptr in secs:
                if va <= rva < va + max(vsize, rsize):
                    return rva - va + rptr
            raise ValueError(f'RVA {rva:#x} outside all sections')

        md = off(u32(off(cli_rva) + 8))
        if u32(md) != 0x424A5342:
            raise ValueError('metadata signature BSJB missing')
        p = md + 16 + u32(md + 12)
        nstreams = u16(p + 2); p += 4
        streams = {}
        for _ in range(nstreams):
            so, size = struct.unpack_from('<II', data, p); p += 8
            e = data.index(b'\0', p)
            streams[data[p:e].decode('ascii', 'replace')] = data[md + so:md + so + size]
            p += (e - p + 4) & ~3
        tbl = streams.get('#~') or streams.get('#-')
        if tbl is None:
            raise ValueError('no #~ / #- metadata table stream')
        self.strings, self.blob = streams.get('#Strings', b''), streams.get('#Blob', b'')
        heap, valid = tbl[6], struct.unpack_from('<Q', tbl, 8)[0]
        p, self.nrows = 24, [0] * 64
        for i in range(64):
            if valid >> i & 1:
                self.nrows[i] = struct.unpack_from('<I', tbl, p)[0]; p += 4
        if heap & 0x40:  # extra data (uncompressed #- streams)
            p += 4
        sizes = {'u2': 2, 'u4': 4, 'S': 4 if heap & 1 else 2, 'G': 4 if heap & 2 else 2, 'B': 4 if heap & 4 else 2}
        for name, (bits, tabs) in _CODED.items():
            sizes[name] = 2 if max(self.nrows[t] for t in tabs) < (1 << (16 - bits)) else 4
        self._tables = {}
        for t, cols in enumerate(_TABLES):
            colsz = [sizes[c] if isinstance(c, str) else (2 if self.nrows[c] < 0x10000 else 4) for c in cols]
            fmt = struct.Struct('<' + ''.join('H' if s == 2 else 'I' for s in colsz))
            n = self.nrows[t]
            self._tables[t] = (tbl, p, n, fmt)
            p += n * fmt.size
        if p > len(tbl):
            raise ValueError('metadata tables exceed stream size')
        self._str_cache: dict[int, str] = {}

    def rows(self, t: int) -> list[tuple]:
        buf, p, n, fmt = self._tables[t]
        return list(fmt.iter_unpack(buf[p:p + n * fmt.size])) if n else []

    def string(self, o: int) -> str:
        s = self._str_cache.get(o)
        if s is None:
            s = self._str_cache[o] = self.strings[o:self.strings.index(b'\0', o)].decode('utf-8', 'replace')
        return s

    def blob_at(self, o: int) -> bytes:
        n, p = _cuint(self.blob, o)
        return self.blob[p:p + n]


@dataclass(frozen=True)
class TypeInfo:
    namespace: str
    name: str            # nested types as 'Outer/Inner' (namespace = outermost type's namespace)
    base: str | None     # full name; generic instantiations as 'Ns.Base`1<System.Int32>'
    is_enum: bool
    is_interface: bool

    @property
    def full_name(self) -> str:
        return f'{self.namespace}.{self.name}' if self.namespace else self.name


def _join(ns: str, name: str) -> str:
    return f'{ns}.{name}' if ns else name


def list_types(dll_path) -> list[TypeInfo]:
    """All TypeDefs of one managed assembly (incl. <Module> and compiler-generated types), table order."""
    md = _Metadata(Path(dll_path).read_bytes())
    tdefs, trefs, tspecs = md.rows(0x02), md.rows(0x01), md.rows(0x1B)
    enclosing = {n: e for n, e in md.rows(0x29)}
    td_memo: dict[int, tuple[str, str]] = {}

    def td_parts(i: int, depth: int = 0) -> tuple[str, str]:
        if i not in td_memo:
            _, name, ns = tdefs[i - 1][:3]
            outer = enclosing.get(i)
            if outer and depth < 64:
                ons, oname = td_parts(outer, depth + 1)
                td_memo[i] = (ons, f'{oname}/{md.string(name)}')
            else:
                td_memo[i] = (md.string(ns), md.string(name))
        return td_memo[i]

    def tr_full(i: int, depth: int = 0) -> str:
        scope, name, ns = trefs[i - 1]
        if scope & 3 == 3 and scope >> 2 and depth < 64:  # nested TypeRef: scope is the enclosing TypeRef
            return f'{tr_full(scope >> 2, depth + 1)}/{md.string(name)}'
        return _join(md.string(ns), md.string(name))

    def tdor(v: int, depth: int = 0) -> str | None:  # TypeDefOrRef(OrSpec) coded value -> full name
        tag, idx = v & 3, v >> 2
        if not idx:
            return None
        if tag == 0:
            return _join(*td_parts(idx))
        if tag == 1:
            return tr_full(idx)
        if tag == 2 and depth < 16:
            try:
                return sig_type(md.blob_at(tspecs[idx - 1][0]), 0, depth + 1)[0]
            except (IndexError, ValueError):
                pass
        return f'TypeSpec#{idx}'

    def sig_type(b: bytes, p: int, depth: int) -> tuple[str, int]:
        et = b[p]; p += 1
        if et in _PRIM:
            return _PRIM[et], p
        if et in (0x11, 0x12):  # VALUETYPE / CLASS
            v, p = _cuint(b, p)
            return tdor(v, depth) or '?', p
        if et == 0x15:  # GENERICINST
            name, p = sig_type(b, p, depth)
            n, p = _cuint(b, p)
            args = []
            for _ in range(n):
                a, p = sig_type(b, p, depth); args.append(a)
            return f'{name}<{",".join(args)}>', p
        if et in (0x13, 0x1E):  # VAR / MVAR
            n, p = _cuint(b, p)
            return ('!' if et == 0x13 else '!!') + str(n), p
        if et in (0x0F, 0x10, 0x1D):  # PTR / BYREF / SZARRAY
            t, p = sig_type(b, p, depth)
            return t + {0x0F: '*', 0x10: '&', 0x1D: '[]'}[et], p
        if et == 0x14:  # ARRAY: type rank numSizes sizes* numLoBounds loBounds*
            t, p = sig_type(b, p, depth)
            rank, p = _cuint(b, p)
            for _ in range(2):
                k, p = _cuint(b, p)
                for _ in range(k):
                    _, p = _cuint(b, p)
            return f'{t}[{"," * max(rank - 1, 0)}]', p
        if et in (0x1F, 0x20):  # CMOD_REQD / CMOD_OPT
            _, p = _cuint(b, p)
            return sig_type(b, p, depth)
        if et == 0x45:  # PINNED
            return sig_type(b, p, depth)
        raise ValueError(f'unsupported element type {et:#x}')

    out = []
    for i, (flags, _, _, extends, _, _) in enumerate(tdefs, 1):
        ns, name = td_parts(i)
        base = tdor(extends)
        out.append(TypeInfo(ns, name, base, base == 'System.Enum', bool(flags & _INTERFACE)))
    return out


# ---- snapshots / diff ------------------------------------------------------

def snapshot(managed_dir, assemblies=ASSEMBLIES) -> list[str]:
    """Sorted lines '<Assembly>\\t<Namespace.Type>\\t<Base>' (base '' if none); compiler-generated types skipped."""
    lines = []
    for asm in assemblies:
        for t in list_types(Path(managed_dir) / f'{asm}.dll'):
            if '<' not in t.full_name:
                lines.append(f'{asm}\t{t.full_name}\t{t.base or ""}')
    return sorted(lines)


def _parse(lines) -> dict[tuple[str, str], str]:
    out = {}
    for line in lines:
        line = line.rstrip('\r\n')
        if line and not line.startswith('#'):
            asm, name, base = (line.split('\t') + ['', ''])[:3]
            out[(asm, name)] = base
    return out


def _template_set(bases: dict[str, str]) -> set[str]:
    def derives(n: str) -> bool:
        seen, cur = set(), bases.get(n)
        while cur and cur not in seen:
            cur = cur.split('<', 1)[0]  # generic instantiation -> generic definition
            if cur == TEMPLATE_ROOT:
                return True
            seen.add(cur); cur = bases.get(cur)
        return False
    return {n for n in bases if derives(n)}


def template_subclasses(types) -> set[str]:
    """Full names of all types deriving (transitively, within the given set) from C3.FoundryTemplate.
    `types`: TypeInfo objects and/or snapshot lines (may span several assemblies)."""
    bases = {}
    for t in types:
        if isinstance(t, str):
            for (_, name), base in _parse([t]).items():
                bases[name] = base
        else:
            bases[t.full_name] = t.base or ''
    return _template_set(bases)


def diff_snapshot(old_lines, new_lines) -> dict[str, list[str]]:
    """added/removed: snapshot lines; changed_base: '<Asm>\\t<Type>\\t<old> -> <new>';
    new_templates / removed_templates: full type names (FoundryTemplate subclasses)."""
    old, new = _parse(old_lines), _parse(new_lines)
    t_old = _template_set({n: b for (_, n), b in old.items()})
    t_new = _template_set({n: b for (_, n), b in new.items()})
    return {
        'added': sorted(f'{a}\t{n}\t{new[a, n]}' for a, n in new.keys() - old.keys()),
        'removed': sorted(f'{a}\t{n}\t{old[a, n]}' for a, n in old.keys() - new.keys()),
        'changed_base': sorted(f'{a}\t{n}\t{old[a, n]} -> {new[a, n]}' for a, n in old.keys() & new.keys()
                               if old[a, n] != new[a, n]),
        'new_templates': sorted(t_new - t_old),
        'removed_templates': sorted(t_old - t_new),
    }


# ---- baseline / warnings ---------------------------------------------------

def _short(n: str) -> str:
    return n.rsplit('.', 1)[-1]


def _cap(names: list[str], n: int = _CAP) -> str:
    return ', '.join(names[:n]) + (f', +{len(names) - n} more' if len(names) > n else '')


def _disp(p: Path) -> str:
    """Path from the '*_Data' folder on (keeps user paths out of the manifest)."""
    parts = Path(p).parts
    for i, s in enumerate(parts):
        if s.endswith('_Data'):
            return '/'.join(parts[i:])
    return str(p)


def _game_version(managed: Path) -> str | None:
    f = Path(managed).absolute().parent.parent / 'version.txt'
    return f.read_text(encoding='utf-8').strip() if f.exists() else None


def read_baseline(path=None) -> tuple[list[str], str | None]:
    """Baseline lines (comments stripped) and the game version from its '# ... game <v>' header."""
    lines, ver = [], None
    for line in Path(path or BASELINE).read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            if ver is None and ' game ' in line:
                ver = line.split(' game ', 1)[1].split()[0]
        elif line:
            lines.append(line)
    return lines, ver


def write_baseline(managed_dir, path=None, assemblies=ASSEMBLIES, game_version: str | None = None) -> Path:
    path = Path(path or BASELINE)
    lines = snapshot(managed_dir, assemblies)
    version = game_version or _game_version(managed_dir) or '?'
    head = [f'# FOUNDRY managed type baseline - game {version} - {len(lines)} types',
            '# <Assembly>\\t<Namespace.Type>\\t<BaseType>; regenerate: python3 -m foundry_export.dll_types baseline <game_dir>']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(('\n'.join(head + lines) + '\n').encode('utf-8'))
    return path


def warnings_for(managed_dir, baseline_path=None) -> list[str]:
    """Manifest warnings ('dll-types: ...') for type changes vs the baseline; [] if nothing changed."""
    managed, bpath = Path(managed_dir), Path(baseline_path or BASELINE)
    if not bpath.exists():
        return [f'dll-types: baseline {bpath.name} not found - class check skipped']
    old_lines, bver = read_baseline(bpath)
    asms = list(dict.fromkeys(line.split('\t', 1)[0] for line in old_lines))
    if not managed.is_dir():
        return [f'dll-types: {_disp(managed)} not found (IL2CPP build?) - class check skipped']
    out, present = [], []
    for a in asms:
        dll = managed / f'{a}.dll'
        if dll.exists():
            present.append(a)
        else:
            out.append(f'dll-types: {_disp(dll)} not found (IL2CPP build?) - class check skipped')
    try:
        new_lines = snapshot(managed, present)
    except (OSError, ValueError, IndexError, struct.error) as e:
        return out + [f'dll-types: cannot read DLL metadata ({e}) - class check skipped']
    d = diff_snapshot([x for x in old_lines if x.split('\t', 1)[0] in present], new_lines)
    asm_of = {n: a for a, n in _parse(new_lines)} | {n: a for a, n in _parse(old_lines) if n in d['removed_templates']}
    ref = f'baseline {bver}' if bver else 'baseline'
    for a in present:
        add, rem, chg = (sum(x.startswith(a + '\t') for x in d[k]) for k in ('added', 'removed', 'changed_base'))
        if not (add or rem or chg):
            continue
        msg = f'dll-types: {a} +{add} / -{rem} types' + (f', {chg} base changes' if chg else '') + f' vs {ref}'
        extra = []
        for key, label in (('new_templates', 'new'), ('removed_templates', 'removed')):
            names = [_short(n) for n in d[key] if asm_of.get(n) == a]
            if names:
                extra.append(f'{label} FoundryTemplate subclasses: {_cap(names)}')
        out.append(msg + (f' ({"; ".join(extra)})' if extra else ''))
    return out


def managed_dir_of(path) -> Path:
    """Game folder, '*_Data' folder or Managed folder -> Managed folder (may not exist)."""
    p = Path(path).expanduser()
    if p.name == 'Managed' or (p / 'Main.dll').exists():
        return p
    if (p / 'Managed').is_dir():
        return p / 'Managed'
    data = sorted(d for d in p.glob('*_Data') if d.is_dir())
    return (data[0] if data else p) / 'Managed'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python3 -m foundry_export.dll_types',
                                 description='managed type inventory of the FOUNDRY DLLs vs baseline')
    sub = ap.add_subparsers(dest='cmd')
    d = sub.add_parser('diff', help='show type changes vs baseline (exit 1 if any)')
    d.add_argument('game_dir'); d.add_argument('--baseline', default=None)
    d.add_argument('--all', action='store_true', help='list every added/removed/changed type')
    b = sub.add_parser('baseline', help='(re)write the baseline from the installed game')
    b.add_argument('game_dir'); b.add_argument('--out', default=None)
    b.add_argument('--assemblies', default=','.join(ASSEMBLIES), help='comma-separated, default %(default)s')
    li = sub.add_parser('list', help='print all types of one DLL')
    li.add_argument('dll')
    args = ap.parse_args(argv)
    if args.cmd == 'list':
        for t in list_types(args.dll):
            kind = 'interface' if t.is_interface else 'enum' if t.is_enum else 'class'
            print(f'{t.full_name}\t{t.base or ""}\t{kind}')
        return 0
    if args.cmd == 'baseline':
        managed = managed_dir_of(args.game_dir)
        p = write_baseline(managed, args.out, tuple(a for a in args.assemblies.split(',') if a))
        print(f'wrote {p} ({p.stat().st_size} bytes, {len(read_baseline(p)[0])} types)')
        return 0
    if args.cmd == 'diff':
        managed = managed_dir_of(args.game_dir)
        warns = warnings_for(managed, args.baseline)
        for w in warns:
            print(w)
        old, _ = read_baseline(args.baseline) if Path(args.baseline or BASELINE).exists() else ([], None)
        asms = [a for a in dict.fromkeys(x.split('\t', 1)[0] for x in old) if (managed / f'{a}.dll').exists()]
        if asms:
            res = diff_snapshot([x for x in old if x.split('\t', 1)[0] in asms], snapshot(managed, asms))
            for key, items in res.items():
                if items:
                    print(f'{key} ({len(items)}):')
                    for x in items if args.all or len(items) <= 50 else items[:50] + [f'... +{len(items) - 50} more (--all)']:
                        print('  ' + x.replace('\t', '  '))
        if not warns:
            print('no type changes vs baseline')
        return 1 if warns else 0
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
