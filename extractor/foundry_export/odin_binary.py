"""Minimal decoder for Sirenix Odin binary serialization (SerializedFormat 0),
as used by AssemblyLineStages assets (serializationData.SerializedBytes)."""
import struct

class _R:
    def __init__(self, b): self.b, self.p = b, 0
    def u8(self): v = self.b[self.p]; self.p += 1; return v
    def i32(self): v = struct.unpack_from('<i', self.b, self.p)[0]; self.p += 4; return v
    def i64(self): v = struct.unpack_from('<q', self.b, self.p)[0]; self.p += 8; return v
    def u64(self): v = struct.unpack_from('<Q', self.b, self.p)[0]; self.p += 8; return v
    def fmt(self, f, n): v = struct.unpack_from(f, self.b, self.p)[0]; self.p += n; return v
    def s(self):
        wide = self.u8(); n = self.i32()
        if wide:
            v = self.b[self.p:self.p + 2 * n].decode('utf-16-le'); self.p += 2 * n
        else:
            v = self.b[self.p:self.p + n].decode('latin-1'); self.p += n
        return v

_SCALARS = {15: ('<b', 1), 17: ('<B', 1), 19: ('<h', 2), 21: ('<H', 2), 23: ('<i', 4), 25: ('<I', 4),
            27: ('<q', 8), 29: ('<Q', 8), 31: ('<f', 4), 33: ('<d', 8), 37: ('<H', 2)}

def decode(data: bytes):
    r = _R(data); types = {}

    def read_type():
        t = r.u8()
        if t == 47:
            tid = r.i32(); name = r.s(); types[tid] = name; return name
        if t == 48:
            return types[r.i32()]
        if t in (45, 46):  # null type
            return None
        raise ValueError(f'expected type entry, got {t} at {r.p-1}')

    def read_node():
        typ = read_type(); r.i32()  # reference id
        obj = {'$type': typ}
        while True:
            name, val, end = read_entry()
            if end: return obj
            obj[name if name is not None else "$items"] = val

    def read_array():
        r.i64(); items = []
        while True:
            name, val, end = read_entry()
            if end: return items
            items.append(val)

    def read_entry():
        t = r.u8()
        if t in (5, 7, 49): return None, None, True
        named = t in (1, 3, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 9, 11, 13, 50)
        name = r.s() if named else None
        if t in (1, 2): return name, read_node(), False
        if t in (3, 4):
            typ = read_type(); obj = {'$type': typ}
            while True:
                n, v, e = read_entry()
                if e: return name, obj, False
                obj[n if n is not None else "$items"] = v
        if t == 6: return name, read_array(), False
        if t == 8:
            n = r.i32(); sz = r.i32(); raw = r.b[r.p:r.p + n * sz]; r.p += n * sz
            return name, {'$primitiveArray': raw.hex(), 'count': n, 'elemSize': sz}, False
        if t in (9, 10, 11, 12): return name, {'$ref': r.i32()}, False
        if t in _SCALARS: f, n = _SCALARS[t]; return name, r.fmt(f, n), False
        if t in (16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 38):
            f, n = _SCALARS[t - 1]; return name, r.fmt(f, n), False
        if t in (39, 40): return name, r.s(), False
        if t in (43, 44): return name, bool(r.u8()), False
        if t in (45, 46): return name, None, False
        if t in (50, 51): return name, {'$extRef': r.s()}, False
        raise ValueError(f'unsupported Odin entry type {t} at offset {r.p-1}')

    root = {}
    while r.p < len(data):
        name, val, end = read_entry()
        if end: break
        root[name] = val
    return root
