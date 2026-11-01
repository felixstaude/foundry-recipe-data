#!/usr/bin/env python3
"""Re-check the native simulation facts the extractor hard-codes, straight from FoundryNative.dll.

    python3 extractor/tools/check_native_constants.py [<game_dir>] [--disasm] [--find TEXT]
    python3 extractor/tools/check_native_constants.py --dll FoundryNative.dll --pdb FoundryNative.pdb

Run it when the export warns `code-changed: FoundryNative.dll` (UPDATE.md step g). The simulation runs in
`foundry_Data/Plugins/x86_64/FoundryNative.dll`; the game ships the full symbol file `FoundryNative.pdb` (MSF 7.0) next
to it, so every function is located BY NAME through the PDB (no addresses are stored here) and its machine code is scanned
for the immediate operands the extractor relies on:

  0. The PDB belongs to the DLL (CodeView GUID + age in the PE debug directory = PDB info/DBI stream).
  1. `CraftingAction::reinitialize` (the overload with the parameter `recipe`; the other one copies saved ticks):
     the recipe time multiplied by 10000, followed by a 32-bit immediate = hand-crafting divisor
     -> build.CHARACTER_SPEED * 10000.
  2. `ProducerEntity` / `AutoProducerEntity` / `ModularProducerEntity::tryStartProduction` and
     `BaseStationEntity::BaseStationFurnace::tickUpdate`: a 32-bit immediate equal to build.MACHINE_MS_PER_TICK_FPM
     (ms -> ticks).
  3. PDB S_CONSTANT records: AssemblyLineSystem::ASSEMBLY_RAIL_ITEM_LENGTH / ASSEMBLY_RAIL_SLOTS_PER_M and
     AssemblyLineProducerActionTemplate::MAX_REQUIREMENT_COUNT.
  4. Presence of the functions the assembly-line conclusions in findings/assembly_line.md rest on.

Only immediate operands are compared. Never read static data for fixed-point scales: the global the code uses as "one"
holds 100000000 in the file and is set to 10000 at runtime (preInitializeNativeFixedPointLibrary), see
findings/verification.md.

Output: one line per check, `OK` / `MISMATCH` / `NOT FOUND`. Exit code 0 = all OK, 1 = any MISMATCH / NOT FOUND
(function changed or code restructured -> disassemble it by hand, findings/verification.md), 2 = DLL/PDB missing or
unreadable, 3 = game folder not found. `--disasm` adds objdump context for every hit (optional, needs binutils);
`--find TEXT` lists all functions whose name contains TEXT (to look up renamed functions).

Stdlib only: a minimal MSF 7.0 / PDB reader (superblock, stream directory, DBI module list, module symbol streams,
global symbol records), a PE reader and an x86-64 instruction-length decoder for a linear sweep over each function.
"""
from __future__ import annotations

import argparse
import mmap
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from foundry_export import build  # noqa: E402
from foundry_export.steam import HINT_FILE, GameNotFound, find_game  # noqa: E402

NATIVE_DIR = Path('Plugins') / 'x86_64'
DLL_NAME = 'FoundryNative.dll'
PDB_NAME = 'FoundryNative.pdb'
FPM_ONE = 10000                       # fixed-point factor of the simulation (runtime value of the "one" global)

EXIT_OK, EXIT_FAIL, EXIT_INPUT, EXIT_NO_GAME = 0, 1, 2, 3


class FormatError(Exception):
    """File is not the expected MSF 7.0 PDB / PE32+ image."""


# ---------------------------------------------------------------- MSF 7.0 container

MSF7_MAGIC = b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0'


class Msf:
    """Multi-stream file (the PDB container): superblock -> block map -> stream directory -> streams.
    The file is mmapped; streams are assembled from their blocks only when requested."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = open(self.path, 'rb')
        try:
            self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError as e:              # empty file
            self._file.close()
            raise FormatError(f'{self.path}: {e}') from None
        try:
            self._parse()
        except (FormatError, struct.error, IndexError) as e:
            self.close()
            raise FormatError(f'{self.path}: {e}') from None

    def _parse(self) -> None:
        mm = self._mm
        if mm[:len(MSF7_MAGIC)] != MSF7_MAGIC:
            raise FormatError('not an MSF 7.0 file (PDB magic missing)')
        bs, _free_map, n_blocks, dir_bytes, _unknown, block_map_addr = struct.unpack_from('<6I', mm, 32)
        if bs not in (512, 1024, 2048, 4096, 8192, 16384, 32768) or n_blocks * bs > len(mm):
            raise FormatError(f'implausible superblock (block size {bs}, {n_blocks} blocks, file {len(mm)} bytes)')
        self.block_size = bs
        n_dir_blocks = -(-dir_bytes // bs)
        dir_blocks = struct.unpack_from(f'<{n_dir_blocks}I', mm, block_map_addr * bs)
        directory = self._gather(dir_blocks, dir_bytes)
        n_streams = struct.unpack_from('<I', directory, 0)[0]
        sizes = struct.unpack_from(f'<{n_streams}I', directory, 4)
        pos = 4 + 4 * n_streams
        self.sizes: list[int] = []
        self.blocks: list[tuple[int, ...]] = []
        for size in sizes:
            if size == 0xFFFFFFFF:           # deleted / nil stream
                size = 0
            k = -(-size // bs)
            self.blocks.append(struct.unpack_from(f'<{k}I', directory, pos))
            self.sizes.append(size)
            pos += 4 * k

    def _gather(self, blocks, size: int) -> bytes:
        bs, mm = self.block_size, self._mm
        if any((b + 1) * bs > len(mm) for b in blocks):
            raise FormatError('stream block outside the file')
        return b''.join(mm[b * bs:(b + 1) * bs] for b in blocks)[:size]

    def stream(self, index: int) -> bytes:
        if not 0 <= index < len(self.sizes):
            raise FormatError(f'stream {index} does not exist ({len(self.sizes)} streams)')
        return self._gather(self.blocks[index], self.sizes[index])

    def close(self) -> None:
        self._mm.close()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------- PDB symbols

S_END, S_BLOCK32, S_WITH32, S_CONSTANT = 0x0006, 0x1103, 0x1104, 0x1107
S_LPROC32, S_GPROC32, S_LOCAL, S_PROCREF, S_LPROCREF = 0x110F, 0x1110, 0x113E, 0x1125, 0x1127
S_LPROC32_ID, S_GPROC32_ID = 0x1146, 0x1147
S_INLINESITE, S_INLINESITE_END, S_INLINESITE2 = 0x114D, 0x114E, 0x115D
PROC_KINDS = (S_GPROC32, S_LPROC32, S_GPROC32_ID, S_LPROC32_ID)
_SCOPE_OPEN = {S_BLOCK32, S_WITH32, S_INLINESITE, S_INLINESITE2}
_SCOPE_CLOSE = {S_END, S_INLINESITE_END}
_LOCAL_IS_PARAM = 0x0001

# CodeView numeric leaves (value >= 0x8000 announces the type of the following value)
_NUMERIC_LEAVES = {0x8000: '<b', 0x8001: '<h', 0x8002: '<H', 0x8003: '<i', 0x8004: '<I', 0x8009: '<q', 0x800A: '<Q'}


def read_numeric_leaf(data: bytes, pos: int) -> tuple[int, int]:
    """CodeView numeric leaf at pos -> (value, position after it)."""
    leaf = struct.unpack_from('<H', data, pos)[0]
    if leaf < 0x8000:
        return leaf, pos + 2
    fmt = _NUMERIC_LEAVES.get(leaf)
    if fmt is None:
        raise FormatError(f'unsupported numeric leaf 0x{leaf:04x}')
    return struct.unpack_from(fmt, data, pos + 2)[0], pos + 2 + struct.calcsize(fmt)


def _cstr(data: bytes, pos: int) -> str:
    end = data.index(b'\0', pos)
    return data[pos:end].decode('utf-8', 'replace')


def iter_symbols(data: bytes, start: int = 0, end: int | None = None):
    """CodeView symbol records -> (offset, kind, record bytes incl. the 4-byte header)."""
    end = len(data) if end is None else min(end, len(data))
    pos = start
    while pos + 4 <= end:
        reclen, kind = struct.unpack_from('<HH', data, pos)
        if reclen < 2:
            break
        yield pos, kind, data[pos:pos + 2 + reclen]
        pos += 2 + reclen


@dataclass
class Proc:
    name: str
    segment: int
    offset: int
    length: int
    params: list[str]
    module: str
    kind: int


@dataclass
class ProcRef:
    name: str
    module_index: int        # 1-based, into the DBI module list
    symbol_offset: int       # offset of the S_*PROC32 record in that module's symbol stream


class Pdb:
    """The parts of a PDB this tool needs: GUID/age, DBI module list and the global symbol records
    (S_PROCREF/S_LPROCREF -> module symbol stream -> S_*PROC32, and S_CONSTANT)."""

    def __init__(self, path: str | Path):
        self.msf = Msf(path)
        try:
            self._parse()
        except (struct.error, IndexError, ValueError) as e:
            self.msf.close()
            raise FormatError(f'{path}: unreadable PDB ({e})') from None
        except FormatError:
            self.msf.close()
            raise
        self._module_streams: dict[int, bytes] = {}

    def _parse(self) -> None:
        info = self.msf.stream(1)            # PDB info stream: version, signature, age, GUID
        _ver, _sig, self.info_age = struct.unpack_from('<III', info, 0)
        self.guid = info[12:28]
        dbi = self.msf.stream(3)
        (vsig, _vhdr, self.age, _gsi, _build, _psi, _pdbdll, symrec, _rbld,
         modi_size) = struct.unpack_from('<iIIHHHHHHi', dbi, 0)
        if vsig != -1:
            raise FormatError(f'unexpected DBI signature {vsig}')
        self.modules: list[tuple[str, int, int]] = []     # (object file, symbol stream, symbol byte size)
        pos, end = 64, 64 + modi_size
        while pos < end:
            stream, sym_size = struct.unpack_from('<HI', dbi, pos + 34)
            name_end = dbi.index(b'\0', pos + 64)
            obj_end = dbi.index(b'\0', name_end + 1)
            name = dbi[pos + 64:name_end].decode('utf-8', 'replace')
            self.modules.append((name, stream, sym_size))
            pos = (obj_end + 1 + 3) & ~3
        self._globals = self.msf.stream(symrec)
        self.procrefs: dict[str, list[ProcRef]] = {}
        self.constants: dict[str, int] = {}
        for _off, kind, rec in iter_symbols(self._globals):
            if kind in (S_PROCREF, S_LPROCREF):
                _sum, sym_off, imod = struct.unpack_from('<IIH', rec, 4)
                name = _cstr(rec, 14)
                self.procrefs.setdefault(name, []).append(ProcRef(name, imod, sym_off))
            elif kind == S_CONSTANT:
                try:
                    value, npos = read_numeric_leaf(rec, 8)
                except FormatError:
                    continue
                self.constants[_cstr(rec, npos)] = value

    def _module_stream(self, imod: int) -> tuple[str, bytes]:
        if not 1 <= imod <= len(self.modules):
            raise FormatError(f'module {imod} does not exist')
        name, stream, sym_size = self.modules[imod - 1]
        if imod not in self._module_streams:
            self._module_streams[imod] = self.msf.stream(stream)[:sym_size]
        return name, self._module_streams[imod]

    def procs(self, name: str) -> list[Proc]:
        """All procedures with exactly this (qualified) name, e.g. 'CraftingAction::reinitialize' (overloads too)."""
        out = []
        for ref in self.procrefs.get(name, []):
            try:
                out.append(self._proc(ref))
            except (FormatError, struct.error, IndexError, ValueError):
                continue                     # dangling reference: treated like a missing function
        return [p for p in out if p is not None]

    def _proc(self, ref: ProcRef) -> Proc | None:
        module, data = self._module_stream(ref.module_index)
        reclen, kind = struct.unpack_from('<HH', data, ref.symbol_offset)
        if kind not in PROC_KINDS:
            return None
        _parent, p_end, _next, length, _dbg_start, _dbg_end, _type, offset, segment = struct.unpack_from(
            '<IIIIIIIIH', data, ref.symbol_offset + 4)
        params, depth = [], 0
        for _o, k, rec in iter_symbols(data, ref.symbol_offset + 2 + reclen, p_end):
            if k in _SCOPE_OPEN:
                depth += 1
            elif k in _SCOPE_CLOSE:
                depth -= 1
            elif k == S_LOCAL and depth == 0 and struct.unpack_from('<H', rec, 8)[0] & _LOCAL_IS_PARAM:
                params.append(_cstr(rec, 10))
        return Proc(ref.name, segment, offset, length, params, module.rsplit('\\', 1)[-1], kind)

    def find(self, text: str) -> list[str]:
        return sorted(n for n in self.procrefs if text in n)

    def close(self) -> None:
        self.msf.close()


# ---------------------------------------------------------------- PE image

@dataclass
class Section:
    name: str
    rva: int
    virtual_size: int
    raw_offset: int
    raw_size: int


class PeImage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        try:
            self._parse()
        except (struct.error, IndexError) as e:
            raise FormatError(f'{self.path}: truncated PE ({e})') from None

    def _parse(self) -> None:
        d = self.data
        if d[:2] != b'MZ':
            raise FormatError(f'{self.path}: not a PE file')
        pe = struct.unpack_from('<I', d, 0x3C)[0]
        if d[pe:pe + 4] != b'PE\0\0':
            raise FormatError(f'{self.path}: PE signature missing')
        n_sections, = struct.unpack_from('<H', d, pe + 6)
        opt_size, = struct.unpack_from('<H', d, pe + 20)
        opt = pe + 24
        if struct.unpack_from('<H', d, opt)[0] != 0x20B:
            raise FormatError(f'{self.path}: not PE32+ (x86-64)')
        self.image_base, = struct.unpack_from('<Q', d, opt + 24)
        n_dirs, = struct.unpack_from('<I', d, opt + 108)
        self.sections = []
        for i in range(n_sections):
            so = opt + opt_size + 40 * i
            vsize, rva, rsize, roff = struct.unpack_from('<IIII', d, so + 8)
            self.sections.append(Section(d[so:so + 8].rstrip(b'\0').decode('ascii', 'replace'), rva, vsize, roff, rsize))
        self.codeview = None                 # (guid, age) from the RSDS debug record
        if n_dirs > 6:
            dbg_rva, dbg_size = struct.unpack_from('<II', d, opt + 112 + 8 * 6)
            for i in range(dbg_size // 28):
                entry = self.rva_to_offset(dbg_rva) + 28 * i
                dtype, size, _rva, ptr = struct.unpack_from('<IIII', d, entry + 12)
                if dtype == 2 and size >= 24 and d[ptr:ptr + 4] == b'RSDS':
                    self.codeview = (d[ptr + 4:ptr + 20], struct.unpack_from('<I', d, ptr + 20)[0])

    def rva_to_offset(self, rva: int) -> int:
        for s in self.sections:
            if s.rva <= rva < s.rva + max(s.virtual_size, s.raw_size):
                return s.raw_offset + rva - s.rva
        raise FormatError(f'RVA 0x{rva:x} is in no section')

    def seg_rva(self, segment: int, offset: int) -> int:
        """PDB segment:offset (segment = 1-based section index) -> RVA."""
        if not 1 <= segment <= len(self.sections):
            raise FormatError(f'segment {segment} out of range')
        return self.sections[segment - 1].rva + offset

    def code(self, segment: int, offset: int, length: int) -> bytes:
        self.seg_rva(segment, offset)        # validates the segment
        s = self.sections[segment - 1]
        start = s.raw_offset + offset
        return self.data[start:start + min(length, max(0, s.raw_size - offset))]


# ---------------------------------------------------------------- x86-64 instruction lengths

@dataclass
class Insn:
    offset: int                  # within the decoded buffer
    length: int
    map: int                     # 1 = one-byte, 2 = 0F, 3 = 0F38, 4 = 0F3A, 0x10+ = VEX/EVEX map
    opcode: int
    rex: int = 0
    modrm: int | None = None
    imm: int | None = None       # unsigned little-endian value of the (last) immediate
    imm_size: int = 0
    valid: bool = True

    @property
    def reg(self) -> int | None:
        """ModRM.reg (the /digit of group opcodes), without REX.R."""
        return None if self.modrm is None else (self.modrm >> 3) & 7

    @property
    def rex_w(self) -> bool:
        return bool(self.rex & 8)


_LEGACY_PREFIXES = frozenset(b'\xf0\xf2\xf3\x2e\x36\x3e\x26\x64\x65\x66\x67')
_INVALID_64 = frozenset((0x06, 0x07, 0x0E, 0x16, 0x17, 0x1E, 0x1F, 0x27, 0x2F, 0x37, 0x3F, 0x60, 0x61,
                         0x82, 0x9A, 0xCE, 0xD4, 0xD5, 0xD6, 0xEA))
# one-byte map: opcode -> (has ModRM, immediate kind); kinds: b=1 w=2 z=2/4 v=2/4/8 r=rel32 m=moffs e=enter(3)
_ONE: dict[int, tuple[bool, str]] = {}
for _op in range(0x40):
    if _op & 7 < 4:
        _ONE[_op] = (True, '')
    elif _op & 7 == 4:
        _ONE[_op] = (False, 'b')
    elif _op & 7 == 5:
        _ONE[_op] = (False, 'z')
_ONE.update({0x63: (True, ''), 0x68: (False, 'z'), 0x69: (True, 'z'), 0x6A: (False, 'b'), 0x6B: (True, 'b'),
             0x80: (True, 'b'), 0x81: (True, 'z'), 0x83: (True, 'b'), 0xA8: (False, 'b'), 0xA9: (False, 'z'),
             0xC0: (True, 'b'), 0xC1: (True, 'b'), 0xC2: (False, 'w'), 0xC6: (True, 'b'), 0xC7: (True, 'z'),
             0xC8: (False, 'e'), 0xCA: (False, 'w'), 0xCD: (False, 'b'), 0xE8: (False, 'r'), 0xE9: (False, 'r'),
             0xEB: (False, 'b'), 0xF6: (True, ''), 0xF7: (True, ''), 0xFE: (True, ''), 0xFF: (True, '')})
for _op in range(0x84, 0x90):
    _ONE[_op] = (True, '')
for _op in (*range(0x70, 0x80), *range(0xB0, 0xB8), *range(0xE0, 0xE8)):
    _ONE[_op] = (False, 'b')
for _op in range(0xB8, 0xC0):
    _ONE[_op] = (False, 'v')
for _op in range(0xA0, 0xA4):
    _ONE[_op] = (False, 'm')
for _op in (*range(0xD0, 0xD4), *range(0xD8, 0xE0)):
    _ONE[_op] = (True, '')
_0F_NO_MODRM = frozenset((0x05, 0x06, 0x07, 0x08, 0x09, 0x0B, 0x0E, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x37,
                          0x77, 0xA0, 0xA1, 0xA2, 0xA8, 0xA9, 0xAA, *range(0x80, 0x90), *range(0xC8, 0xD0)))
_0F_IMM8 = frozenset((0x0F, 0x70, 0x71, 0x72, 0x73, 0xA4, 0xAC, 0xBA, 0xC2, 0xC4, 0xC5, 0xC6))
_VEX_MAP1_IMM8 = frozenset((0x70, 0x71, 0x72, 0x73, 0xC2, 0xC4, 0xC5, 0xC6))


def _modrm_size(code: bytes, p: int) -> int:
    """Bytes taken by ModRM + SIB + displacement starting at p (64-bit mode; 0x67 does not change the size)."""
    modrm = code[p]
    mod, rm = modrm >> 6, modrm & 7
    if mod == 3:
        return 1
    n = 1
    if rm == 4:
        n += 1
        if mod == 0 and code[p + 1] & 7 == 5:
            n += 4
    elif mod == 0 and rm == 5:           # RIP-relative
        n += 4
    return n + (1 if mod == 1 else 4 if mod == 2 else 0)


def decode_one(code: bytes, pos: int) -> Insn:
    """Length (and immediate) of the instruction at pos. Raises IndexError if it runs past the buffer."""
    p = pos
    opsize16 = addr32 = False
    while code[p] in _LEGACY_PREFIXES:
        opsize16 |= code[p] == 0x66
        addr32 |= code[p] == 0x67
        p += 1
    rex = 0
    if 0x40 <= code[p] <= 0x4F:
        rex = code[p]
        p += 1
    op = code[p]
    p += 1
    has_modrm, imm_kind, valid, op_map = False, '', True, 1
    if op in (0xC4, 0xC5, 0x62):          # VEX3 / VEX2 / EVEX (always in 64-bit mode)
        if op == 0xC5:
            op_map, p = 1, p + 1
        elif op == 0xC4:
            op_map, p = code[p] & 0x1F, p + 2
        else:
            op_map, p = code[p] & 0x07, p + 3
        op = code[p]
        p += 1
        has_modrm = not (op_map == 1 and op == 0x77)          # vzeroupper / vzeroall
        imm_kind = 'b' if op_map == 3 or (op_map == 1 and op in _VEX_MAP1_IMM8) else ''
        op_map |= 0x10
    elif op == 0x0F:
        op = code[p]
        p += 1
        if op == 0x38:
            op_map, op, has_modrm = 3, code[p], True
            p += 1
        elif op == 0x3A:
            op_map, op, has_modrm, imm_kind = 4, code[p], True, 'b'
            p += 1
        else:
            op_map = 2
            has_modrm = op not in _0F_NO_MODRM
            imm_kind = 'r' if 0x80 <= op <= 0x8F else 'b' if op in _0F_IMM8 else ''
    elif op in _INVALID_64:
        valid = False
    else:
        has_modrm, imm_kind = _ONE.get(op, (False, ''))
    modrm = None
    if has_modrm:
        modrm = code[p]
        p += _modrm_size(code, p)
        if op_map == 1 and op in (0xF6, 0xF7) and (modrm >> 3) & 7 < 2:   # test r/m, imm
            imm_kind = 'b' if op == 0xF6 else 'z'
    size = {'': 0, 'b': 1, 'w': 2, 'r': 4, 'e': 3,
            'z': 2 if opsize16 else 4,
            'v': 8 if rex & 8 else 2 if opsize16 else 4,
            'm': 4 if addr32 else 8}[imm_kind]
    if p + size > len(code):
        raise IndexError('instruction runs past the end of the buffer')
    imm = int.from_bytes(code[p + size - (1 if imm_kind == 'e' else size):p + size], 'little') if size else None
    return Insn(pos, p + size - pos, op_map, op, rex, modrm, imm, size, valid)


def decode(code: bytes) -> list[Insn]:
    """Linear sweep over a function. Undecodable bytes become 1-byte invalid entries (resync)."""
    out, pos = [], 0
    while pos < len(code):
        try:
            ins = decode_one(code, pos)
        except IndexError:
            ins = Insn(pos, 1, 0, code[pos], valid=False)
        out.append(ins)
        pos += ins.length
    return out


_REG64 = ('rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi')


def _reg_name(n: int, wide: bool) -> str:
    if n < 8:
        return _REG64[n] if wide else 'e' + _REG64[n][1:]
    return f'r{n}' if wide else f'r{n}d'


def mov_imm(ins: Insn) -> int | None:
    """Immediate of `mov r32,imm32` (B8+r) or `mov r/m,imm32` (C7 /0); movabs r64,imm64 is not counted."""
    if ins.map == 1 and 0xB8 <= ins.opcode <= 0xBF and ins.imm_size == 4:
        return ins.imm
    if ins.map == 1 and ins.opcode == 0xC7 and ins.reg == 0 and ins.imm_size == 4:
        return ins.imm
    return None


def imul_imm(ins: Insn) -> int | None:
    """Immediate of `imul r,r/m,imm32` (69 /r)."""
    return ins.imm if ins.map == 1 and ins.opcode == 0x69 and ins.imm_size == 4 else None


def describe(ins: Insn) -> str:
    if mov_imm(ins) is not None:
        if ins.opcode == 0xC7:
            return f'mov {"qword" if ins.rex_w else "dword"} [r/m],0x{ins.imm:x}'
        return f'mov {_reg_name((ins.opcode & 7) | (ins.rex & 1) << 3, False)},0x{ins.imm:x}'
    if imul_imm(ins) is not None:
        return f'imul r,r/m,0x{ins.imm:x}'
    return f'opcode {ins.map}:{ins.opcode:02x}'


def movs_after_imul(insns: list[Insn], imul_value: int, window: int = 8) -> list[tuple[Insn, Insn]]:
    """For every `imul r,r/m,imul_value`: the first `mov r32,imm32` among the next `window` instructions."""
    out = []
    for i, ins in enumerate(insns):
        if imul_imm(ins) == imul_value:
            for nxt in insns[i + 1:i + 1 + window]:
                if mov_imm(nxt) is not None:
                    out.append((ins, nxt))
                    break
    return out


def idiv_divisors(insns: list[Insn]) -> list[Insn]:
    """`mov reg,imm32` that feeds an `idiv reg` (F7 /7, register operand) within the next 2 instructions:
    the inlined fixed-point divisions by a constant."""
    out = []
    for i, ins in enumerate(insns):
        if mov_imm(ins) is None or ins.opcode == 0xC7:
            continue
        reg = (ins.opcode & 7) | (ins.rex & 1) << 3
        for nxt in insns[i + 1:i + 3]:
            if (nxt.map == 1 and nxt.opcode == 0xF7 and nxt.reg == 7 and nxt.modrm >> 6 == 3
                    and (nxt.modrm & 7) | (nxt.rex & 1) << 3 == reg):
                out.append(ins)
                break
    return out


# ---------------------------------------------------------------- checks

AL_FUNCTIONS = (  # what the assembly-line conclusions (findings/assembly_line.md, verification.md) rest on
    ('AL_EndConsumerEntity::alcm_validateItemForConsumption', 'painting is mandatory (finished + painted flag)'),
    ('AL_Item::processPainting', 'only setter of the painted flag'),
    ('AL_Item::_isReadyForActionIterativeCheck', 'free action order, parents before children'),
    ('AL_ProducerEntity::tickUpdate', 'PCM charging, 2-action buffer, no action time'),
    ('AL_StartEntity::tickUpdate', 'spawn only at gap >= RAIL_ITEM_LENGTH (singleStartObjectsPerMinute)'),
    ('AL_ProducerEntity::recalculatePainterCosts', 'painter energy summed over all parts (derived.painterPowerKJ)'),
    ('CraftingQueue::tickUpdate', 'hand crafting counts 1 per tick'),
)
MACHINE_FUNCTIONS = ('ProducerEntity::tryStartProduction', 'AutoProducerEntity::tryStartProduction',
                     'ModularProducerEntity::tryStartProduction', 'BaseStationEntity::BaseStationFurnace::tickUpdate')
CONSTANTS = (  # (S_CONSTANT name, expected, what)
    ('AssemblyLineSystem::ASSEMBLY_RAIL_ITEM_LENGTH', build.RAIL_ITEM_LENGTH, 'build.RAIL_ITEM_LENGTH'),
    ('AssemblyLineSystem::ASSEMBLY_RAIL_SLOTS_PER_M', build.SLOTS_PER_METER, 'build.SLOTS_PER_METER'),
    ('AssemblyLineProducerActionTemplate::MAX_REQUIREMENT_COUNT', 8, 'info: max ALPA requirements, not used by the extractor'),
)


@dataclass
class Result:
    status: str                  # OK | MISMATCH | NOT FOUND
    what: str
    where: str
    detail: str
    hits: list[tuple[int, int]] = field(default_factory=list)   # (va, length) of relevant instructions, for --disasm


def _proc_where(pe: PeImage, proc: Proc, ins: Insn | None = None, suffix: str = '') -> str:
    va = pe.image_base + pe.seg_rva(proc.segment, proc.offset)
    return f'{proc.name}{suffix} @0x{va:x}' + (f'+0x{ins.offset:x}' if ins is not None else '')


def _va(pe: PeImage, proc: Proc, ins: Insn) -> tuple[int, int]:
    return pe.image_base + pe.seg_rva(proc.segment, proc.offset) + ins.offset, ins.length


def check_pairing(pe: PeImage, pdb: Pdb) -> Result:
    what = f'{PDB_NAME} belongs to {DLL_NAME} (CodeView GUID + age)'
    if pe.codeview is None:
        return Result('NOT FOUND', what, DLL_NAME, 'no RSDS debug record in the DLL')
    guid, age = pe.codeview
    ok = guid == pdb.guid and age == pdb.age
    return Result('OK' if ok else 'MISMATCH', what, 'PE debug directory / PDB info+DBI',
                  f'DLL {guid.hex()} age {age}, PDB {pdb.guid.hex()} age {pdb.age}')


def check_hand_crafting(pe: PeImage, pdb: Pdb) -> Result:
    expected = build.CHARACTER_SPEED * FPM_ONE
    name = 'CraftingAction::reinitialize'
    what = f'hand-crafting divisor = build.CHARACTER_SPEED*{FPM_ONE} ({expected})'
    procs = pdb.procs(name)
    with_recipe = [p for p in procs if 'recipe' in p.params]
    if len(with_recipe) != 1:
        sigs = '; '.join(f'({", ".join(p.params)})' for p in procs) or 'no such function'
        return Result('NOT FOUND', what, name, f'need exactly one overload with parameter "recipe", found: {sigs}')
    proc = with_recipe[0]
    pairs = movs_after_imul(decode(pe.code(proc.segment, proc.offset, proc.length)), FPM_ONE)
    if not pairs:
        return Result('NOT FOUND', what, _proc_where(pe, proc, suffix='(recipe)'),
                      f'no multiplication by {FPM_ONE} followed by a 32-bit immediate')
    good = [(a, b) for a, b in pairs if mov_imm(b) == expected]
    imul, mov = (good or pairs)[0]
    hits = [_va(pe, proc, imul), _va(pe, proc, mov)]
    if good:
        return Result('OK', what, _proc_where(pe, proc, mov, '(recipe)'),
                      f'{describe(mov)} after {describe(imul)} = /{expected // FPM_ONE}', hits)
    found = ', '.join(f'{mov_imm(b)} (/{mov_imm(b) / FPM_ONE:g})' for _a, b in pairs)
    return Result('MISMATCH', what, _proc_where(pe, proc, mov, '(recipe)'),
                  f'game {found} = immediate after the multiplication by {FPM_ONE}, extractor {expected}', hits)


def check_machine_ticks(pe: PeImage, pdb: Pdb, name: str) -> Result:
    expected = build.MACHINE_MS_PER_TICK_FPM
    what = f'ms->ticks divisor = build.MACHINE_MS_PER_TICK_FPM ({expected})'
    procs = pdb.procs(name)
    if not procs:
        return Result('NOT FOUND', what, name, 'function not in the PDB')
    candidates: list[tuple[Proc, Insn]] = []
    for proc in procs:
        insns = decode(pe.code(proc.segment, proc.offset, proc.length))
        hit = next((i for i in insns if mov_imm(i) == expected), None)
        if hit is not None:
            return Result('OK', what, _proc_where(pe, proc, hit), describe(hit), [_va(pe, proc, hit)])
        candidates += [(proc, i) for i in idiv_divisors(insns)]
    if candidates:
        proc, ins = candidates[0]
        found = ', '.join(str(i.imm) for _p, i in candidates)
        return Result('MISMATCH', what, _proc_where(pe, proc, ins),
                      f'game divides by {found} (constant divisor), extractor {expected}',
                      [_va(pe, p, i) for p, i in candidates])
    return Result('NOT FOUND', what, _proc_where(pe, procs[0]), f'no immediate {expected} and no constant divisor')


def check_constant(pdb: Pdb, name: str, expected: int, what: str) -> Result:
    label = f'{name.split("::")[-1]} = {expected} ({what})'
    if name not in pdb.constants:
        return Result('NOT FOUND', label, 'PDB S_CONSTANT', name)
    got = pdb.constants[name]
    return Result('OK' if got == expected else 'MISMATCH', label, 'PDB S_CONSTANT',
                  f'{name}: game {got}, extractor {expected}')


def check_present(pe: PeImage, pdb: Pdb, name: str, why: str) -> Result:
    procs = [p for p in pdb.procs(name) if p.length > 0]
    if not procs:
        return Result('NOT FOUND', f'function present: {why}', name, 'code restructured? review by hand')
    sizes = ', '.join(f'{p.length} bytes' for p in procs)
    return Result('OK', f'function present: {why}', _proc_where(pe, procs[0]), sizes)


def checks(pe: PeImage, pdb: Pdb) -> list[Result]:
    out = [check_pairing(pe, pdb), check_hand_crafting(pe, pdb)]
    out += [check_machine_ticks(pe, pdb, n) for n in MACHINE_FUNCTIONS]
    out += [check_constant(pdb, *c) for c in CONSTANTS]
    out += [check_present(pe, pdb, n, why) for n, why in AL_FUNCTIONS]
    return out


def run_checks(dll: Path, pdb_path: Path) -> list[Result]:
    pe = PeImage(dll)
    pdb = Pdb(pdb_path)
    try:
        return checks(pe, pdb)
    finally:
        pdb.close()


# ---------------------------------------------------------------- CLI

def native_files(game_dir: Path) -> tuple[Path, Path]:
    for data in sorted(game_dir.glob('*_Data')):
        dll = data / NATIVE_DIR / DLL_NAME
        if dll.is_file():
            return dll, dll.with_name(PDB_NAME)
    return game_dir / 'foundry_Data' / NATIVE_DIR / DLL_NAME, game_dir / 'foundry_Data' / NATIVE_DIR / PDB_NAME


def objdump_context(dll: Path, va: int, length: int) -> list[str]:
    exe = shutil.which('objdump')
    if not exe:
        return ['    (objdump not installed)']
    r = subprocess.run([exe, '-d', '-w', '-M', 'intel', f'--start-address=0x{va:x}', f'--stop-address=0x{va + length:x}',
                        str(dll)], capture_output=True, text=True)
    return ['    ' + ln.strip() for ln in r.stdout.splitlines() if ln[:1] == ' ' and ':\t' in ln]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('game_dir', nargs='?', help='FOUNDRY folder (default: Steam libraries, FOUNDRY_GAME_DIR, game_path.txt)')
    ap.add_argument('--dll', help=f'{DLL_NAME} to check (overrides game_dir)')
    ap.add_argument('--pdb', help=f'matching {PDB_NAME} (default: next to the DLL)')
    ap.add_argument('--disasm', action='store_true', help='print objdump context for every hit (needs binutils)')
    ap.add_argument('--find', metavar='TEXT', help='list functions whose name contains TEXT and exit')
    args = ap.parse_args(argv)

    if args.dll:
        dll = Path(args.dll)
        pdb_path = Path(args.pdb) if args.pdb else dll.with_name(PDB_NAME)
        version = ''
    else:
        try:
            root = find_game(args.game_dir, hint_file=HINT_FILE).root
        except GameNotFound as e:
            print(e, file=sys.stderr)
            return EXIT_NO_GAME
        dll, pdb_path = native_files(root)
        if args.pdb:
            pdb_path = Path(args.pdb)
        vf = root / 'version.txt'
        version = f' (game {vf.read_text(encoding="utf-8").strip()})' if vf.is_file() else ''
    for p in (dll, pdb_path):
        if not p.is_file():
            hint = (' - the game no longer ships its symbols? Then the native facts can only be re-checked by hand '
                    '(findings/verification.md)') if p == pdb_path else ''
            print(f'{p}: not found{hint}', file=sys.stderr)
            return EXIT_INPUT
    t0 = time.perf_counter()
    try:
        if args.find:
            pdb = Pdb(pdb_path)
            try:
                pe = PeImage(dll)
                for name in pdb.find(args.find):
                    for proc in pdb.procs(name):
                        print(f'{_proc_where(pe, proc)}  {proc.length} bytes  ({", ".join(proc.params)})  [{proc.module}]')
            finally:
                pdb.close()
            return EXIT_OK
        results = run_checks(dll, pdb_path)
    except (FormatError, OSError) as e:
        print(f'error: {e}', file=sys.stderr)
        return EXIT_INPUT
    print(f'{dll}{version}')
    for r in results:
        print(f'{r.status:9} {r.what}  [{r.where}: {r.detail}]')
        if args.disasm:
            for va, length in r.hits:
                print('\n'.join(objdump_context(dll, va, length)))
    bad = [r for r in results if r.status != 'OK']
    print(f'{len(results) - len(bad)}/{len(results)} OK ({time.perf_counter() - t0:.1f} s)')
    if bad:
        print('MISMATCH / NOT FOUND: disassemble the named function (findings/verification.md), adjust build.py, '
              'set the affected items in findings/open_questions.md to "neu messen".')
    return EXIT_FAIL if bad else EXIT_OK


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
