"""Type information for serialized Unity objects.

1. Unity type trees (SerializedFile type metadata): compile_tree(nodes) turns the flat node list of one
   SerializedType into a tree of Field objects and a reader  read(buf, pos) -> (value, pos).  Values:
     * primitives -> int / float / bool, string -> str, TypelessData -> bytes
     * arrays (vector / staticvector / Array nodes) -> list,  PPtr<...> -> PPtr(file_id, path_id)
     * everything else -> dict field name -> value (insertion order = serialization order)
2. Managed (.NET) metadata of the game's Managed/*.dll (ClrAssembly): field visibility/attributes, enums.
"""
from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass, field

from .unity_bundle import TypeTreeNode

ALIGN_FLAG = 0x4000

_PRIM = {
    'bool': '?', 'SInt8': 'b', 'UInt8': 'B', 'char': 'B', 'SInt16': 'h', 'short': 'h', 'UInt16': 'H',
    'unsigned short': 'H', 'SInt32': 'i', 'int': 'i', 'UInt32': 'I', 'unsigned int': 'I', 'Type*': 'I',
    'SInt64': 'q', 'long long': 'q', 'UInt64': 'Q', 'unsigned long long': 'Q', 'FileSize': 'Q',
    'float': 'f', 'double': 'd',
}


class PPtr(tuple):
    """(file_id, path_id) of an object reference."""
    __slots__ = ()

    def __new__(cls, file_id: int, path_id: int):
        return super().__new__(cls, (file_id, path_id))

    file_id = property(lambda s: s[0])
    path_id = property(lambda s: s[1])

    def __bool__(self) -> bool:
        return self[1] != 0


@dataclass
class Field:
    type: str
    name: str
    meta_flag: int
    is_array: bool
    byte_size: int
    children: list['Field'] = field(default_factory=list)

    @property
    def align(self) -> bool:
        return bool(self.meta_flag & ALIGN_FLAG)

    def child(self, name: str) -> 'Field | None':
        return next((c for c in self.children if c.name == name), None)

    @property
    def array(self) -> 'Field | None':
        """The Array node if this field is a vector-like wrapper (or an array itself)."""
        if self.is_array:
            return self
        if len(self.children) == 1 and self.children[0].is_array:
            return self.children[0]
        return None

    @property
    def element(self) -> 'Field | None':
        a = self.array
        return a.children[1] if a is not None else None


def build_tree(nodes: list[TypeTreeNode]) -> Field:
    root, stack = None, []
    for n in nodes:
        f = Field(n.type, n.name, n.meta_flag, n.is_array, n.byte_size)
        while stack and stack[-1][0] >= n.level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(f)
        else:
            root = f
        stack.append((n.level, f))
    if root is None:
        raise ValueError('empty type tree')
    return root


def _aligned(fn):
    def read(b, p):
        v, p = fn(b, p)
        return v, (p + 3) & ~3
    return read


def compile_field(f: Field, little: bool = True):
    """Reader function (buf, pos) -> (value, pos) for one type tree field."""
    e = '<' if little else '>'
    fn = _compile(f, e)
    return _aligned(fn) if f.align else fn


def _compile(f: Field, e: str):
    t = f.type
    if t in _PRIM and not f.children:
        st = struct.Struct(e + ('H' if t == 'char' and f.byte_size == 2 else _PRIM[t]))  # C# char: UTF-16 unit
        size, unpack = st.size, st.unpack_from
        return lambda b, p: (unpack(b, p)[0], p + size)
    if t == 'string' and f.array is not None:
        ln = struct.Struct(e + 'i').unpack_from

        def read_string(b, p):
            n = ln(b, p)[0]; p += 4
            return b[p:p + n].decode('utf-8', 'surrogateescape'), p + n
        return _aligned(read_string) if f.array.align else read_string
    if t == 'TypelessData':
        ln = struct.Struct(e + 'i').unpack_from

        def read_blob(b, p):
            n = ln(b, p)[0]; p += 4
            return bytes(b[p:p + n]), p + n
        return read_blob
    if t.startswith('PPtr<'):
        st = struct.Struct(e + 'iq')
        unpack = st.unpack_from
        return lambda b, p: (PPtr(*unpack(b, p)), p + 12)
    arr = f.array
    if arr is not None:
        elem = arr.children[1]
        ln = struct.Struct(e + 'i').unpack_from
        if elem.type in _PRIM and not elem.children and not elem.align:
            code = _PRIM[elem.type]
            esize = struct.calcsize(code)

            def read_prim_array(b, p):
                n = ln(b, p)[0]; p += 4
                return list(struct.unpack_from(f'{e}{n}{code}', b, p)), p + n * esize
            fn = read_prim_array
        else:
            efn = compile_field(elem, e == '<')

            def read_array(b, p):
                n = ln(b, p)[0]; p += 4
                out = []
                for _ in range(n):
                    v, p = efn(b, p)
                    out.append(v)
                return out, p
            fn = read_array
        if f is not arr:  # wrapper node (vector / staticvector / field name) around the Array node
            return _aligned(fn) if arr.align else fn
        return fn
    subs = [(c.name, compile_field(c, e == '<')) for c in f.children]

    def read_compound(b, p):
        out = {}
        for name, fn in subs:
            out[name], p = fn(b, p)
        return out, p
    return read_compound


def compile_tree(nodes: list[TypeTreeNode], little: bool = True):
    """(root Field, reader) for a SerializedType's node list."""
    root = build_tree(nodes)
    return root, compile_field(root, little)


# ================================================================ managed (.NET) type metadata
# Minimal ECMA-335 metadata reader for the game's Managed/*.dll (Mono builds): type definitions,
# instance fields (flags, signature, [HideInInspector]), enums ([Flags], names, values) and base types.
# Type signatures are nested lists: ['prim', 'i4'] | ['string'] | ['object'] | ['class'|'valuetype', name]
# | ['array', sig] | ['generic', name, [args]] | ['var', n]   (name = 'Namespace.Type' or 'Outer/Nested').

_CODED = {  # name: (tag bits, tables)
    'TypeDefOrRef': (2, (0x02, 0x01, 0x1B)), 'HasConstant': (2, (0x04, 0x08, 0x17)),
    'HasCustomAttribute': (5, (0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11, 0x1A, 0x1B,
                               0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B)),
    'HasFieldMarshal': (1, (0x04, 0x08)), 'HasDeclSecurity': (2, (0x02, 0x06, 0x20)),
    'MemberRefParent': (3, (0x02, 0x01, 0x1A, 0x06, 0x1B)), 'HasSemantics': (1, (0x14, 0x17)),
    'MethodDefOrRef': (1, (0x06, 0x0A)), 'MemberForwarded': (1, (0x04, 0x06)),
    'Implementation': (2, (0x26, 0x23, 0x27)),
    'CustomAttributeType': (3, (-1, -1, 0x06, 0x0A, -1)), 'ResolutionScope': (2, (0x00, 0x1A, 0x23, 0x01)),
    'TypeOrMethodDef': (1, (0x02, 0x06)),
}
# column kinds: 'H'/'I' = u16/u32, 'S' string, 'G' guid, 'B' blob, int = table index, other str = coded index
_TABLES = {
    0x00: ('H', 'S', 'G', 'G', 'G'), 0x01: ('ResolutionScope', 'S', 'S'),
    0x02: ('I', 'S', 'S', 'TypeDefOrRef', 0x04, 0x06),
    0x03: (0x04,), 0x04: ('H', 'S', 'B'), 0x05: (0x06,), 0x06: ('I', 'H', 'H', 'S', 'B', 0x08), 0x07: (0x08,),
    0x08: ('H', 'H', 'S'), 0x09: (0x02, 'TypeDefOrRef'), 0x0A: ('MemberRefParent', 'S', 'B'),
    0x0B: ('H', 'HasConstant', 'B'),
    0x0C: ('HasCustomAttribute', 'CustomAttributeType', 'B'), 0x0D: ('HasFieldMarshal', 'B'),
    0x0E: ('H', 'HasDeclSecurity', 'B'), 0x0F: ('H', 'I', 0x02), 0x10: ('I', 0x04), 0x11: ('B',), 0x12: (0x02, 0x14),
    0x13: (0x14,), 0x14: ('H', 'S', 'TypeDefOrRef'), 0x15: (0x02, 0x17), 0x16: (0x17,), 0x17: ('H', 'S', 'B'),
    0x18: ('H', 0x06, 'HasSemantics'), 0x19: (0x02, 'MethodDefOrRef', 'MethodDefOrRef'), 0x1A: ('S',), 0x1B: ('B',),
    0x1C: ('H', 'MemberForwarded', 'S', 0x1A), 0x1D: ('I', 0x04), 0x1E: ('I', 'I'), 0x1F: ('I',),
    0x20: ('I', 'H', 'H', 'H', 'H', 'I', 'B', 'S', 'S'), 0x21: ('I',), 0x22: ('I', 'I', 'I'),
    0x23: ('H', 'H', 'H', 'H', 'I', 'B', 'S', 'S', 'B'), 0x24: ('I', 0x23), 0x25: ('I', 'I', 'I', 0x23),
    0x26: ('I', 'S', 'B'), 0x27: ('I', 'I', 'S', 'S', 'Implementation'), 0x28: ('I', 'I', 'S', 'Implementation'),
    0x29: (0x02, 0x02), 0x2A: ('H', 'H', 'TypeOrMethodDef', 'S'), 0x2B: ('MethodDefOrRef', 'B'),
    0x2C: (0x2A, 'TypeDefOrRef'),
}
_ELEM = {0x02: 'bool', 0x03: 'char', 0x04: 'i1', 0x05: 'u1', 0x06: 'i2', 0x07: 'u2', 0x08: 'i4', 0x09: 'u4',
         0x0A: 'i8', 0x0B: 'u8', 0x0C: 'r4', 0x0D: 'r8', 0x18: 'i', 0x19: 'u'}
_CONST = {0x02: '<?', 0x03: '<H', 0x04: '<b', 0x05: '<B', 0x06: '<h', 0x07: '<H', 0x08: '<i', 0x09: '<I',
          0x0A: '<q', 0x0B: '<Q'}
FIELD_PUBLIC, FIELD_STATIC, FIELD_INITONLY, FIELD_NOT_SERIALIZED = 0x6, 0x10, 0x20, 0x80


class ClrAssembly:
    """Type definitions of one managed assembly (only what template serialization needs)."""

    def __init__(self, path):
        with open(path, 'rb') as fh:
            self.b = b = fh.read()
        pe = struct.unpack_from('<I', b, 0x3C)[0]
        nsec, opt_size = struct.unpack_from('<H12xH', b, pe + 6)
        opt = pe + 24
        dd = opt + (96 if struct.unpack_from('<H', b, opt)[0] == 0x10B else 112)
        cli_rva = struct.unpack_from('<I', b, dd + 14 * 8)[0]
        self._secs = [struct.unpack_from('<8xIIII', b, opt + opt_size + 40 * i) for i in range(nsec)]
        meta_rva = struct.unpack_from('<I', b, self._off(cli_rva) + 8)[0]
        root = self._off(meta_rva)
        vlen = struct.unpack_from('<I', b, root + 12)[0]
        p = root + 16 + vlen + 2
        nstreams = struct.unpack_from('<H', b, p)[0]; p += 2
        streams = {}
        for _ in range(nstreams):
            off, size = struct.unpack_from('<II', b, p); p += 8
            name, p = _cstr0(b, p)
            p = (p + 3) & ~3
            streams[name] = (root + off, size)
        self._mstarts: list[int] | None = None
        self._strings = streams['#Strings'][0]
        self._blob = streams['#Blob'][0]
        if '#~' not in streams:  # '#-' (uncompressed, with *Ptr indirection tables) is not supported
            raise ValueError(f'{path}: no compressed metadata stream (#~)')
        self._read_tables(*streams['#~'])
        self._build()

    def _off(self, rva: int) -> int:
        for vsize, va, rsize, raw in self._secs:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + raw
        raise ValueError(f'RVA {rva:#x} outside sections')

    def _str(self, i: int) -> str:
        e = self.b.index(0, self._strings + i)
        return self.b[self._strings + i:e].decode('utf-8', 'replace')

    def _blobv(self, i: int) -> bytes:
        p = self._blob + i
        n, p = _cuint(self.b, p)
        return self.b[p:p + n]

    def _read_tables(self, off: int, _size: int):
        b = self.b
        heap = b[off + 6]
        valid = struct.unpack_from('<Q', b, off + 8)[0]
        p = off + 24
        rows = {}
        for t in range(64):
            if valid >> t & 1:
                rows[t] = struct.unpack_from('<I', b, p)[0]; p += 4
        if heap & 0x40:
            p += 4
        ssz, gsz, bsz = (4 if heap & 1 else 2), (4 if heap & 2 else 2), (4 if heap & 4 else 2)
        coded = {k: 2 if max(rows.get(t, 0) for t in ts) < (1 << (16 - bits)) else 4
                 for k, (bits, ts) in _CODED.items()}
        self.rows: dict[int, list[tuple]] = {}
        for t in sorted(rows):
            cols = _TABLES[t]
            fmt = '<'
            for c in cols:
                if c in ('H', 'I'):
                    fmt += c; continue
                if isinstance(c, int):
                    sz = 2 if rows.get(c, 0) < 65536 else 4
                else:
                    sz = {'S': ssz, 'G': gsz, 'B': bsz}.get(c) or coded[c]
                fmt += 'H' if sz == 2 else 'I'
            st = struct.Struct(fmt)
            self.rows[t] = [st.unpack_from(b, p + i * st.size) for i in range(rows[t])]
            p += rows[t] * st.size

    @staticmethod
    def _decode(kind: str, v: int) -> tuple[int, int]:
        bits, ts = _CODED[kind]
        return ts[v & ((1 << bits) - 1)], (v >> bits) - 1  # (table, 0-based row)

    def _build(self):
        R = self.rows
        tdefs, trefs = R.get(0x02, []), R.get(0x01, [])
        nested = {n - 1: e - 1 for n, e in R.get(0x29, [])}
        aref_names = [self._str(r[6]) for r in R.get(0x23, [])]
        asm = R.get(0x20)
        self.name = self._str(asm[0][7]) if asm else ''

        def tdef_name(i):
            ns, n = self._str(tdefs[i][2]), self._str(tdefs[i][1])
            if i in nested:
                return tdef_name(nested[i]) + '/' + n
            return f'{ns}.{n}' if ns else n

        def tref_name(i):
            scope, n, ns = trefs[i]
            t, row = self._decode('ResolutionScope', scope)
            n = self._str(n)
            if t == 0x01 and row >= 0:
                return tref_name(row) + '/' + n
            ns = self._str(ns)
            return f'{ns}.{n}' if ns else n
        self.typedef_names = [tdef_name(i) for i in range(len(tdefs))]
        self.typeref_names = [tref_name(i) for i in range(len(trefs))]

        def tref_scope(i):  # assembly name of a TypeRef (nested refs: of the outermost type)
            t, row = self._decode('ResolutionScope', trefs[i][0])
            if t == 0x01 and row >= 0:
                return tref_scope(row)
            return aref_names[row] if t == 0x23 and 0 <= row < len(aref_names) else None
        self.typeref_scopes = [tref_scope(i) for i in range(len(trefs))]

        # custom attribute type names per (table, row)
        mrefs = R.get(0x0A, [])
        attrs: dict[tuple[int, int], set] = {}
        for parent, ctype, _v in R.get(0x0C, []):
            t, row = self._decode('CustomAttributeType', ctype)
            name = None
            if t == 0x0A:
                pt, prow = self._decode('MemberRefParent', mrefs[row][0])
                name = self._tdor_name(pt, prow)
            elif t == 0x06:
                name = self._method_owner(row)
            if name:
                attrs.setdefault(self._decode('HasCustomAttribute', parent), set()).add(name)
        consts = {}
        for typ, parent, val in R.get(0x0B, []):
            t, row = self._decode('HasConstant', parent)
            if t == 0x04 and typ in _CONST:
                consts[row] = struct.unpack_from(_CONST[typ], self._blobv(val))[0]
        fields = R.get(0x04, [])
        self.types: dict[str, dict] = {}
        for i, (flags, name, ns, extends, flist, _ml) in enumerate(tdefs):
            end = tdefs[i + 1][4] - 1 if i + 1 < len(tdefs) else len(fields)
            base = None
            if extends:
                bt, brow = self._decode('TypeDefOrRef', extends)
                base = self._tdor_name(bt, brow)
            tattrs = attrs.get((0x02, i), set())
            info = {'name': self.typedef_names[i], 'base': base, 'assembly': self.name, 'fields': [], 'enum': None,
                    'valuetype': base in ('System.ValueType', 'System.Enum')}
            if base == 'System.Enum':
                vals = [(self._str(fields[k][1]), consts.get(k, 0)) for k in range(flist - 1, end)
                        if fields[k][0] & FIELD_STATIC]
                info['enum'] = {'flags': 'System.FlagsAttribute' in tattrs, 'values': vals}
            else:
                for k in range(flist - 1, end):
                    fflags, fname, sig = fields[k]
                    if fflags & FIELD_STATIC:
                        continue
                    fa = attrs.get((0x04, k), set())
                    info['fields'].append({'name': self._str(fname), 'flags': fflags, 'sig': self._field_sig(sig),
                                           'hide': 'UnityEngine.HideInInspector' in fa})
            self.types[info['name']] = info

    def _method_owner(self, mrow: int) -> str | None:
        if self._mstarts is None:
            self._mstarts = [t[5] - 1 for t in self.rows.get(0x02, [])]
        i = bisect.bisect_right(self._mstarts, mrow) - 1
        return self.typedef_names[i] if i >= 0 else None

    def _tdor_name(self, t: int, row: int):
        if t == 0x02:
            return self.typedef_names[row]
        if t == 0x01:
            return self.typeref_names[row]
        if t == 0x1B:  # TypeSpec (generic instance as base type)
            sig = self._type(self._blobv(self.rows[0x1B][row][0]), 0)[0]
            return sig[1] if sig[0] == 'generic' else None
        return None

    def _field_sig(self, blob_idx: int):
        b = self._blobv(blob_idx)
        return self._type(b, 1)[0]  # skip FIELD (0x06)

    def _type(self, b: bytes, p: int):
        e = b[p]; p += 1
        while e in (0x1F, 0x20):  # custom modifiers
            _, p = _cuint(b, p)
            e = b[p]; p += 1
        if e in _ELEM:
            return ['prim', _ELEM[e]], p
        if e == 0x0E:
            return ['string'], p
        if e == 0x1C:
            return ['object'], p
        if e in (0x11, 0x12):
            v, p = _cuint(b, p)
            return ['valuetype' if e == 0x11 else 'class', self._tdor_name(*self._decode_tdor(v))], p
        if e == 0x1D:
            el, p = self._type(b, p)
            return ['array', el], p
        if e == 0x15:
            _kind = b[p]; p += 1
            v, p = _cuint(b, p)
            n, p = _cuint(b, p)
            args = []
            for _ in range(n):
                a, p = self._type(b, p)
                args.append(a)
            return ['generic', self._tdor_name(*self._decode_tdor(v)), args], p
        if e in (0x13, 0x1E):
            n, p = _cuint(b, p)
            return ['var', n], p
        if e == 0x14:  # multi-dimensional array: not serializable, keep opaque
            el, p = self._type(b, p)
            rank, p = _cuint(b, p)
            nsz, p = _cuint(b, p)
            for _ in range(nsz):
                _, p = _cuint(b, p)
            nlo, p = _cuint(b, p)
            for _ in range(nlo):
                _, p = _cuint(b, p)
            return ['mdarray', el], p
        return ['other', e], p

    @staticmethod
    def _decode_tdor(v: int) -> tuple[int, int]:
        return (0x02, 0x01, 0x1B, -1)[v & 3], (v >> 2) - 1


def _cstr0(b: bytes, p: int) -> tuple[str, int]:
    e = b.index(0, p)
    return b[p:e].decode('ascii', 'replace'), e + 1


def _cuint(b: bytes, p: int) -> tuple[int, int]:
    x = b[p]
    if x & 0x80 == 0:
        return x, p + 1
    if x & 0xC0 == 0x80:
        return ((x & 0x3F) << 8) | b[p + 1], p + 2
    return ((x & 0x1F) << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3], p + 4
