"""Minimal read-only access to a UnityFS asset bundle (Unity 2022.3, serialized file format 22).

Only what the exporter needs:
  * UnityFS header / block table / directory (LZ4 / LZ4HC or uncompressed blocks)
  * lazy, block-wise decompression with random access
  * serialized-file object table
  * the AssetBundle object's m_Container (asset path -> object path id)
  * raw object bytes

  * type trees (SerializedType nodes, script types, externals) for typetree.py

No third-party dependencies (pure-Python LZ4 block decoder; lz4.block is used when installed).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import lru_cache

try:  # optional C implementation (pip install lz4); the pure-Python decoder below is the fallback
    from lz4.block import decompress as _lz4_c
except ImportError:  # pragma: no cover - depends on the environment
    _lz4_c = None


def lz4_block_decompress(src: bytes, uncompressed_size: int) -> bytes:
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:  # overlapping copy == repeating the last `off` bytes
            dst += (dst[start:] * (ml // off + 1))[:ml]
    if len(dst) != uncompressed_size:
        raise ValueError(f'LZ4: expected {uncompressed_size} bytes, got {len(dst)}')
    return bytes(dst)


def _cstr(b: bytes, p: int) -> tuple[str, int]:
    e = b.index(0, p)
    return b[p:e].decode('utf-8', 'replace'), e + 1


@dataclass
class _Block:
    usize: int
    csize: int
    flags: int
    coff: int  # offset in bundle file
    uoff: int  # offset in uncompressed stream


@dataclass
class Node:
    offset: int
    size: int
    flags: int
    path: str


class UnityFSBundle:
    def __init__(self, path: str):
        self.path = path
        self.f = open(path, 'rb')
        head = self.f.read(256)
        if not head.startswith(b'UnityFS\0'):
            raise ValueError(f'{path}: not a UnityFS bundle')
        p = 8
        self.format_version = struct.unpack_from('>I', head, p)[0]; p += 4
        self.player_version, p = _cstr(head, p)
        self.unity_version, p = _cstr(head, p)
        self.size, ci_size, ui_size, flags = struct.unpack_from('>qIII', head, p); p += 20
        if self.format_version >= 7:
            p = (p + 15) & ~15
        if flags & 0x80:  # block info at end of file
            self.f.seek(self.size - ci_size)
        else:
            self.f.seek(p)
        info_c = self.f.read(ci_size)
        data_start = (p + ci_size) if not (flags & 0x80) else p
        if flags & 0x200:  # BlockInfoNeedPaddingAtStart
            data_start = (data_start + 15) & ~15
        comp = flags & 0x3F
        info = self._decompress(info_c, ui_size, comp)
        q = 16  # uncompressed data hash
        (nblocks,) = struct.unpack_from('>i', info, q); q += 4
        self.blocks: list[_Block] = []
        coff, uoff = data_start, 0
        for _ in range(nblocks):
            us, cs, bf = struct.unpack_from('>IIH', info, q); q += 10
            self.blocks.append(_Block(us, cs, bf, coff, uoff))
            coff += cs; uoff += us
        (nnodes,) = struct.unpack_from('>i', info, q); q += 4
        self.nodes: list[Node] = []
        for _ in range(nnodes):
            o, s, nf = struct.unpack_from('>qqI', info, q); q += 20
            name, q = _cstr(info, q)
            self.nodes.append(Node(o, s, nf, name))
        self._cache = lru_cache(maxsize=64)(self._load_block)
        self._sfiles: list[SerializedFile] | None = None

    def close(self):
        f = getattr(self, 'f', None)
        if f is not None:
            f.close()

    __del__ = close

    @staticmethod
    def _decompress(data: bytes, usize: int, comp: int) -> bytes:
        if comp == 0:
            return data
        if comp in (2, 3):
            if _lz4_c is not None:
                return _lz4_c(data, uncompressed_size=usize)
            return lz4_block_decompress(data, usize)
        raise NotImplementedError(f'bundle compression type {comp} (LZMA?) not supported')

    def _load_block(self, idx: int) -> bytes:
        b = self.blocks[idx]
        self.f.seek(b.coff)
        return self._decompress(self.f.read(b.csize), b.usize, b.flags & 0x3F)

    def read(self, offset: int, size: int) -> bytes:
        """Read from the uncompressed data stream."""
        out = bytearray()
        lo, hi = 0, len(self.blocks) - 1
        while lo < hi:  # binary search for first block
            mid = (lo + hi + 1) // 2
            if self.blocks[mid].uoff <= offset:
                lo = mid
            else:
                hi = mid - 1
        i = lo
        while size > 0:
            b = self.blocks[i]
            data = self._cache(i)
            s = offset - b.uoff
            chunk = data[s:s + size]
            out += chunk; size -= len(chunk); offset += len(chunk); i += 1
        return bytes(out)

    def serialized_files(self) -> list['SerializedFile']:
        if self._sfiles is None:  # parsed once, shared by all users of this bundle object
            self._sfiles = [SerializedFile(self, n) for n in self.nodes if not n.path.endswith(('.resS', '.resource'))]
        return list(self._sfiles)


@dataclass
class ObjectInfo:
    path_id: int
    byte_start: int
    byte_size: int
    class_id: int
    type_index: int = -1


@dataclass
class TypeTreeNode:
    level: int
    type: str
    name: str
    byte_size: int
    meta_flag: int
    is_array: bool


@dataclass
class SerializedType:
    class_id: int
    script_type_index: int
    nodes: list[TypeTreeNode]


# Unity's built-in type tree string table (CommonString), referenced by offsets with the high bit set
_COMMON_STRINGS = b''.join(s.encode() + b'\0' for s in (
    'AABB', 'AnimationClip', 'AnimationCurve', 'AnimationState', 'Array', 'Base', 'BitField', 'bitset', 'bool',
    'char', 'ColorRGBA', 'Component', 'data', 'deque', 'double', 'dynamic_array', 'FastPropertyName', 'first',
    'float', 'Font', 'GameObject', 'Generic Mono', 'GradientNEW', 'GUID', 'GUIStyle', 'int', 'list', 'long long',
    'map', 'Matrix4x4f', 'MdFour', 'MonoBehaviour', 'MonoScript', 'm_ByteSize', 'm_Curve', 'm_EditorClassIdentifier',
    'm_EditorHideFlags', 'm_Enabled', 'm_ExtensionPtr', 'm_GameObject', 'm_Index', 'm_IsArray', 'm_IsStatic',
    'm_MetaFlag', 'm_Name', 'm_ObjectHideFlags', 'm_PrefabInternal', 'm_PrefabParentObject', 'm_Script',
    'm_StaticEditorFlags', 'm_Type', 'm_Version', 'Object', 'pair', 'PPtr<Component>', 'PPtr<GameObject>',
    'PPtr<Material>', 'PPtr<MonoBehaviour>', 'PPtr<MonoScript>', 'PPtr<Object>', 'PPtr<Prefab>', 'PPtr<Sprite>',
    'PPtr<TextAsset>', 'PPtr<Texture>', 'PPtr<Texture2D>', 'PPtr<Transform>', 'Prefab', 'Quaternionf', 'Rectf',
    'RectInt', 'RectOffset', 'second', 'set', 'short', 'size', 'SInt16', 'SInt32', 'SInt64', 'SInt8', 'staticvector',
    'string', 'TextAsset', 'TextMesh', 'Texture', 'Texture2D', 'Transform', 'TypelessData', 'UInt16', 'UInt32',
    'UInt64', 'UInt8', 'unsigned int', 'unsigned long long', 'unsigned short', 'vector', 'Vector2f', 'Vector3f',
    'Vector4f', 'm_ScriptingClassIdentifier', 'Gradient', 'Type*', 'int2_storage', 'int3_storage', 'BoundsInt',
    'm_CorrespondingSourceObject', 'm_PrefabInstance', 'm_PrefabAsset', 'FileSize', 'Hash128', 'RenderingLayerMask',
))


def _tt_string(buf: bytes, off: int) -> str:
    if off & 0x80000000:
        buf, off = _COMMON_STRINGS, off & 0x7FFFFFFF
    return _cstr(buf, off)[0]


class SerializedFile:
    def __init__(self, bundle: UnityFSBundle, node: Node):
        self.bundle, self.node = bundle, node
        self._ab = None
        hdr = bundle.read(node.offset, 48)
        version = struct.unpack_from('>I', hdr, 8)[0]
        if version < 22:
            raise NotImplementedError(f'serialized file version {version} not supported')
        self.version = version
        meta_size, _file_size, self.data_offset = struct.unpack_from('>Iqq', hdr, 20)
        self.little = hdr[16] == 0
        meta = bundle.read(node.offset + 48, meta_size)
        e = '<' if self.little else '>'
        p = 0
        self.unity_version, p = _cstr(meta, p)
        p += 4  # target platform
        type_tree = meta[p] != 0; p += 1
        (ntypes,) = struct.unpack_from(e + 'i', meta, p); p += 4
        self.types: list[SerializedType] = []
        for _ in range(ntypes):
            cid, _stripped, sti = struct.unpack_from(e + 'i?h', meta, p); p += 7
            if cid == 114:
                p += 16  # script id
            p += 16  # old type hash
            nodes = []
            if type_tree:
                nn, sb = struct.unpack_from(e + 'ii', meta, p); p += 8
                strings = meta[p + nn * 32:p + nn * 32 + sb]
                for k in range(nn):
                    _v, lvl, tf, ts, ns, bs, _ix, mf = struct.unpack_from(e + 'HBBIIiii', meta, p + 32 * k)
                    nodes.append(TypeTreeNode(lvl, _tt_string(strings, ts), _tt_string(strings, ns), bs, mf,
                                              bool(tf & 1)))
                p += nn * 32 + sb
                (ndeps,) = struct.unpack_from(e + 'i', meta, p); p += 4 + 4 * ndeps
            self.types.append(SerializedType(cid, sti, nodes))
        (nobj,) = struct.unpack_from(e + 'i', meta, p); p += 4
        self.objects: dict[int, ObjectInfo] = {}
        for _ in range(nobj):
            p = (p + 3) & ~3
            pid, start, size, tidx = struct.unpack_from(e + 'qqIi', meta, p); p += 24
            self.objects[pid] = ObjectInfo(pid, start, size, self.types[tidx].class_id, tidx)
        # script types: PPtr<MonoScript> per SerializedType.script_type_index
        (nscripts,) = struct.unpack_from(e + 'i', meta, p); p += 4
        self.script_types: list[tuple[int, int]] = []
        for _ in range(nscripts):
            (fidx,) = struct.unpack_from(e + 'i', meta, p); p += 4
            p = (p + 3) & ~3
            (lid,) = struct.unpack_from(e + 'q', meta, p); p += 8
            self.script_types.append((fidx, lid))
        (next_,) = struct.unpack_from(e + 'i', meta, p); p += 4
        self.externals: list[str] = []
        for _ in range(next_):
            _tmp, p = _cstr(meta, p)
            p += 20  # guid + type
            path, p = _cstr(meta, p)
            self.externals.append(path)

    def object_bytes(self, path_id: int) -> bytes:
        o = self.objects[path_id]
        return self.bundle.read(self.node.offset + self.data_offset + o.byte_start, o.byte_size)

    def _asset_bundle(self) -> tuple[list[tuple[int, int]], list[tuple[str, int, int, int, int]]]:
        """AssetBundle (class 142): m_PreloadTable and m_Container entries
        (path, preloadIndex, preloadSize, fileID, pathID)."""
        if self._ab is not None:
            return self._ab
        ab = next((o for o in self.objects.values() if o.class_id == 142), None)
        if ab is None:
            return [], []
        r = Reader(self.object_bytes(ab.path_id), self.little)
        r.string()  # m_Name
        n = r.i32()
        preload = list(struct.iter_unpack(r.e + 'iq', r.b[r.p:r.p + 12 * n]))
        r.p += 12 * n
        entries = []
        for _ in range(r.i32()):
            key = r.string()
            pi, ps = r.i32(), r.i32()
            file_id, pid = r.pptr()
            entries.append((key, pi, ps, file_id, pid))
        self._ab = (preload, entries)
        return self._ab

    def container(self) -> dict[str, int]:
        """AssetBundle (class 142) m_Container: lower-case asset path -> path id (same file only)."""
        return {key: pid for key, _pi, _ps, file_id, pid in self._asset_bundle()[1] if file_id == 0}

    def container_paths(self) -> dict[int, str]:
        """path id -> m_Container asset path for every listed (explicitly bundled) object of this file."""
        out: dict[int, str] = {}
        for key, _pi, _ps, file_id, pid in self._asset_bundle()[1]:
            if file_id == 0:
                out.setdefault(pid, key)
        return out


class Reader:
    def __init__(self, b: bytes, little: bool = True):
        self.b, self.p, self.e = b, 0, '<' if little else '>'

    def align(self):
        self.p = (self.p + 3) & ~3

    def i32(self) -> int:
        v = struct.unpack_from(self.e + 'i', self.b, self.p)[0]; self.p += 4; return v

    def i64(self) -> int:
        v = struct.unpack_from(self.e + 'q', self.b, self.p)[0]; self.p += 8; return v

    def u8(self) -> int:
        v = self.b[self.p]; self.p += 1; return v

    def bytes_(self) -> bytes:
        n = self.i32(); v = self.b[self.p:self.p + n]; self.p += n; self.align(); return v

    def string(self) -> str:
        return self.bytes_().decode('utf-8', 'replace')

    def pptr(self) -> tuple[int, int]:
        return self.i32(), self.i64()


def read_odin_scriptable_object(raw: bytes, little: bool = True) -> tuple[str, int, bytes]:
    """MonoBehaviour header + Sirenix SerializationData: returns (m_Name, SerializedFormat, SerializedBytes)."""
    r = Reader(raw, little)
    r.pptr()           # m_GameObject
    r.u8(); r.align()  # m_Enabled
    r.pptr()           # m_Script
    name = r.string()  # m_Name
    fmt = r.i32()      # serializationData.SerializedFormat
    data = r.bytes_()  # serializationData.SerializedBytes
    return name, fmt, data
