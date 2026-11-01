"""Tests for tools/check_native_constants.py (FoundryNative.dll constants via FoundryNative.pdb).

Synthetic: x86-64 length decoder / imm32 scanner on hand-assembled code, CodeView numeric leaves, and a complete
synthetic MSF 7.0 PDB + PE32+ pair (all checks OK, then MISMATCH / NOT FOUND variants). With the game: all checks OK
on the installed FoundryNative.dll, CLI exit code, and the decoder's instruction boundaries against objdump.
"""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from _util import EXTRACTOR, GAME, require_game

sys.path.insert(0, str(EXTRACTOR / 'tools'))
import check_native_constants as cnc  # noqa: E402

TOOL = EXTRACTOR / 'tools' / 'check_native_constants.py'

# hand-assembled instructions (hex, length) - lengths cross-checked with objdump -b binary -m i386:x86-64
CODE = [
    ('55', 1),                                   # push rbp
    ('48 89 5c 24 08', 5),                       # mov [rsp+8],rbx
    ('48 83 ec 20', 4),                          # sub rsp,0x20
    ('48 69 8b 80 01 00 00 10 27 00 00', 11),    # imul r,[r+disp32],10000
    ('41 b9 30 75 00 00', 6),                    # mov r9d,30000 (REX.B)
    ('48 8b 05 00 00 00 00', 7),                 # mov rax,[rip+0]
    ('48 f7 e9', 3),                             # imul rcx
    ('41 ba 0a 8b 02 00', 6),                    # mov r10d,166666 (REX.B)
    ('49 f7 fa', 3),                             # idiv r10
    ('48 b8 88 77 66 55 44 33 22 11', 10),       # movabs rax,imm64
    ('c7 44 24 30 10 27 00 00', 8),              # mov dword [rsp+0x30],0x2710
    ('48 c7 c0 ff ff ff ff', 7),                 # mov rax,-1
    ('66 c7 00 34 12', 5),                       # mov word [rax],0x1234
    ('66 b8 34 12', 4),                          # mov ax,0x1234
    ('e8 00 00 00 00', 5),                       # call rel32
    ('0f 84 10 00 00 00', 6),                    # je rel32
    ('74 05', 2),                                # je rel8
    ('c5 f8 77', 3),                             # vzeroupper (VEX2, no ModRM)
    ('c4 e3 79 0f c1 08', 6),                    # vpalignr (VEX3 map 0F3A, imm8)
    ('c5 fa 10 44 24 20', 6),                    # vmovss xmm0,[rsp+0x20]
    ('62 f1 7c 48 10 44 24 01', 8),              # vmovups zmm0,[rsp+0x40] (EVEX)
    ('f3 0f 1e fa', 4),                          # endbr64
    ('0f 1f 44 00 00', 5),                       # nop dword [rax+rax]
    ('66 0f 3a 0f c1 08', 6),                    # palignr
    ('66 0f 38 00 c1', 5),                       # pshufb
    ('f6 c1 01', 3),                             # test cl,1
    ('f7 c1 00 00 01 00', 6),                    # test ecx,0x10000
    ('8b 04 25 44 33 22 11', 7),                 # mov eax,[abs32] (SIB, no base)
    ('48 8d 0c 85 00 00 00 00', 8),              # lea rcx,[rax*4]
    ('f0 48 0f b1 0a', 5),                       # lock cmpxchg [rdx],rcx
    ('0f ba e0 03', 4),                          # bt eax,3
    ('c2 08 00', 3),                             # ret 8
    ('c3', 1),                                   # ret
    ('cc', 1),                                   # int3
]


IMUL = '48 69 8b 80 01 00 00 10 27 00 00'      # multiplication by 10000 (imm32) with a disp32 memory operand


def asm(*hexes: str) -> bytes:
    return b''.join(bytes.fromhex(h) for h in hexes)


class DecoderTests(unittest.TestCase):
    def test_lengths(self):
        code = asm(*(h for h, _n in CODE))
        self.assertEqual([i.length for i in cnc.decode(code)], [n for _h, n in CODE])

    def test_immediates(self):
        insns = cnc.decode(asm(*(h for h, _n in CODE)))
        movs = [cnc.mov_imm(i) for i in insns if cnc.mov_imm(i) is not None]
        # movabs (imm64) and the 16-bit forms are not imm32 movs; REX.W C7 is (sign-extended imm32)
        self.assertEqual(movs, [30000, 166666, 10000, 0xFFFFFFFF])
        self.assertEqual([cnc.imul_imm(i) for i in insns if cnc.imul_imm(i) is not None], [10000])
        self.assertEqual([cnc.describe(i) for i in insns if cnc.mov_imm(i) is not None][:2],
                         [f'mov r9d,0x{30000:x}', f'mov r10d,0x{166666:x}'])

    def test_mov_after_imul_ignores_bytes_inside_other_instructions(self):
        # 'e8 b9 30 75 00' + '00 c0' contains 'b9 30 75 00 00' (a 32-bit immediate 30000) at a non-boundary; a byte scan
        # would report it, the linear sweep must find the real immediate 50000.
        code = asm(IMUL, 'e8 b9 30 75 00', '00 c0', '41 b9 50 c3 00 00', 'c3')
        self.assertIn(bytes.fromhex('b9 30 75 00 00'), code)
        pairs = cnc.movs_after_imul(cnc.decode(code), 10000)
        self.assertEqual([cnc.mov_imm(m) for _i, m in pairs], [50000])
        self.assertEqual(cnc.movs_after_imul(cnc.decode(asm(IMUL, *['90'] * 9, '41 b9 30 75 00 00')), 10000),
                         [])   # outside window

    def test_idiv_divisors(self):
        insns = cnc.decode(asm('48 f7 e9', '41 ba 0a 8b 02 00', '49 f7 fa',       # 166666 into r10d ; idiv r10
                               'ba 10 27 00 00', '48 f7 f9',                       # mov edx,10000 ; idiv rcx (other reg)
                               '41 b9 20 4e 00 00', '90', '49 f7 f9'))              # mov r9d,20000 ; nop ; idiv r9
        self.assertEqual([i.imm for i in cnc.idiv_divisors(insns)], [166666, 20000])

    def test_truncated_and_invalid_bytes_resync(self):
        insns = cnc.decode(asm('06', 'b9 8b 8b'))            # invalid opcode, then a mov cut off by the buffer end
        self.assertEqual([(i.length, i.valid) for i in insns], [(1, False), (1, False), (1, False), (1, False)])

    def test_numeric_leaf(self):
        self.assertEqual(cnc.read_numeric_leaf(b'\x65\x04', 0), (1125, 2))
        self.assertEqual(cnc.read_numeric_leaf(b'\x01\x80\xff\xff', 0), (-1, 4))
        self.assertEqual(cnc.read_numeric_leaf(struct.pack('<HI', 0x8004, 166666), 0), (166666, 6))
        with self.assertRaises(cnc.FormatError):
            cnc.read_numeric_leaf(b'\x05\x80\0\0\0\0', 0)                  # LF_REAL32: not an integer


# ---------------------------------------------------------------- synthetic PDB + DLL

GUID = bytes(range(16))
BASE = 0x10000000                  # synthetic image base


def _rec(kind: int, payload: bytes) -> bytes:
    payload += b'\0' * (-(len(payload) + 4) % 4)
    return struct.pack('<HH', len(payload) + 2, kind) + payload


def build_msf(streams: list[bytes], bs: int = 512) -> bytes:
    """MSF 7.0 with the stream blocks written in reverse order (non-contiguous, like real PDBs)."""
    blocks: list[bytes] = [b'', b'', b'']            # 0 superblock, 1/2 free page maps
    stream_blocks = []
    for data in streams:
        chunks = [data[i:i + bs] for i in range(0, len(data), bs)]
        ids = []
        for chunk in reversed(chunks):
            ids.insert(0, len(blocks))
            blocks.append(chunk)
        stream_blocks.append(ids)
    directory = struct.pack('<I', len(streams)) + b''.join(struct.pack('<I', len(s)) for s in streams)
    directory += b''.join(struct.pack(f'<{len(ids)}I', *ids) for ids in stream_blocks)
    dir_ids = []
    for i in range(0, len(directory), bs):
        dir_ids.append(len(blocks))
        blocks.append(directory[i:i + bs])
    block_map = len(blocks)
    blocks.append(struct.pack(f'<{len(dir_ids)}I', *dir_ids))
    blocks[0] = cnc.MSF7_MAGIC + struct.pack('<6I', bs, 1, len(blocks) + 0, len(directory), 0, block_map)
    return b''.join(b.ljust(bs, b'\0') for b in blocks)


def build_pdb(procs: list[tuple[str, int, int, list[str]]], constants: dict[str, int], guid: bytes = GUID) -> bytes:
    """procs: (name, .text offset, length, parameter names)."""
    module, refs = bytearray(struct.pack('<I', 4)), []
    for name, off, length, params in procs:
        start = len(module)
        body = b''.join(_rec(cnc.S_LOCAL, struct.pack('<IH', 0x74, 1) + p.encode() + b'\0') for p in params)
        # an inlinee's parameter must not be taken for one of the function's own parameters
        body += _rec(cnc.S_INLINESITE, struct.pack('<III', 0, 0, 0x1000))
        body += _rec(cnc.S_LOCAL, struct.pack('<IH', 0x74, 1) + b'inlineeParam\0') + _rec(cnc.S_INLINESITE_END, b'')
        head_len = len(_rec(cnc.S_GPROC32, struct.pack('<IIIIIIIIHB', *[0] * 10) + name.encode() + b'\0'))
        end = start + head_len + len(body)
        module += _rec(cnc.S_GPROC32, struct.pack('<IIIIIIIIHB', 0, end, 0, length, 0, length, 0x1000, off, 1, 0)
                       + name.encode() + b'\0') + body + _rec(cnc.S_END, b'')
        refs.append((name, start))
    symrec = b''.join(_rec(cnc.S_PROCREF, struct.pack('<IIH', 0, ib, 1) + n.encode() + b'\0') for n, ib in refs)
    for name, value in constants.items():
        leaf = struct.pack('<H', value) if value < 0x8000 else struct.pack('<HI', 0x8004, value)
        symrec += _rec(cnc.S_CONSTANT, struct.pack('<I', 0x74) + leaf + name.encode() + b'\0')
    modi = bytearray(64)
    struct.pack_into('<HI', modi, 34, 4, len(module))
    modi += b'Synthetic.obj\0Synthetic.obj\0'
    modi += b'\0' * (-len(modi) % 4)
    dbi = struct.pack('<iIIHHHHHHiiiiiIiiHHI', -1, 19990903, 1, 0xFFFF, 0, 0xFFFF, 0, 5, 0, len(modi),
                      0, 0, 0, 0, 0, 0, 0, 0, 0x8664, 0) + bytes(modi)
    info = struct.pack('<III', 20000404, 0, 1) + guid
    return build_msf([b'', info, b'', dbi, bytes(module), symrec])


def build_dll(text: bytes, guid: bytes = GUID, age: int = 1) -> bytes:
    pe_off, opt_size = 0x40, 240
    sec_hdr = pe_off + 24 + opt_size
    text_raw, rdata_raw = 0x400, 0x400 + -(-len(text) // 0x200) * 0x200
    text_rva, rdata_rva = 0x1000, 0x1000 + -(-len(text) // 0x1000) * 0x1000
    rsds = b'RSDS' + guid + struct.pack('<I', age) + b'Synthetic.pdb\0'
    rdata = struct.pack('<IIHHIIII', 0, 0, 0, 0, 2, len(rsds), rdata_rva + 28, rdata_raw + 28) + rsds
    img = bytearray(rdata_raw + -(-len(rdata) // 0x200) * 0x200)
    img[0:2] = b'MZ'
    struct.pack_into('<I', img, 0x3C, pe_off)
    img[pe_off:pe_off + 4] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', img, pe_off + 4, 0x8664, 2, 0, 0, 0, opt_size, 0x2022)
    opt = pe_off + 24
    struct.pack_into('<H', img, opt, 0x20B)
    struct.pack_into('<Q', img, opt + 24, BASE)
    struct.pack_into('<I', img, opt + 108, 16)
    struct.pack_into('<II', img, opt + 112 + 8 * 6, rdata_rva, 28)
    for i, (name, rva, data, raw) in enumerate(((b'.text', text_rva, text, text_raw),
                                                 (b'.rdata', rdata_rva, rdata, rdata_raw))):
        struct.pack_into('<8sIIII', img, sec_hdr + 40 * i, name, len(data), rva, -(-len(data) // 0x200) * 0x200, raw)
        img[raw:raw + len(data)] = data
    return bytes(img)


def synthetic_game(divisor: int = 30000, ms_per_tick: int = 166666, drop: str = '', guid: bytes = GUID,
                   rail_len: int = 1125):
    """-> (dll bytes, pdb bytes) with every function and constant check_native_constants looks for."""
    text, procs = bytearray(), []

    def add(name, code, params=('this',)):
        if name != drop:
            procs.append((name, len(text), len(code), list(params)))
        text.extend(code + b'\xcc' * (-len(code) % 16))

    # the overload without 'recipe' comes first and loads a different constant: the check must pick by parameter
    add('CraftingAction::reinitialize', asm('55', IMUL, '41 b9 50 c3 00 00', 'c3'), ('this', 'data', 'parentCraftingQueue'))
    add('CraftingAction::reinitialize', asm('55', '48 83 ec 20', IMUL, '41 b9', divisor.to_bytes(4, 'little').hex(),
                                            '48 8b 3d 00 00 00 00', 'c3'), ('this', 'id', 'recipe', 'parentCraftingQueue'))
    for name in cnc.MACHINE_FUNCTIONS:
        add(name, asm(IMUL, '48 f7 e9', '41 ba', ms_per_tick.to_bytes(4, 'little').hex(), '49 f7 fa', 'c3'))
    for name, _why in cnc.AL_FUNCTIONS:
        add(name, asm('33 c0', 'c3'))
    constants = {'AssemblyLineSystem::ASSEMBLY_RAIL_ITEM_LENGTH': rail_len,
                 'AssemblyLineSystem::ASSEMBLY_RAIL_SLOTS_PER_M': 600,
                 'AssemblyLineProducerActionTemplate::MAX_REQUIREMENT_COUNT': 8,
                 'EntityManager::ET_ASSEMBLY_LINE_RAIL': 79}
    return build_dll(bytes(text)), build_pdb(procs, constants, guid)


class SyntheticPdbTests(unittest.TestCase):
    def run_synthetic(self, **kw) -> list[cnc.Result]:
        dll_bytes, pdb_bytes = synthetic_game(**kw)
        with tempfile.TemporaryDirectory() as tmp:
            dll, pdb = Path(tmp) / cnc.DLL_NAME, Path(tmp) / cnc.PDB_NAME
            dll.write_bytes(dll_bytes)
            pdb.write_bytes(pdb_bytes)
            return cnc.run_checks(dll, pdb)

    def status(self, results, needle):
        return [r.status for r in results if needle in r.what or needle in r.where]

    def test_all_ok(self):
        res = self.run_synthetic()
        self.assertEqual([r.status for r in res], ['OK'] * len(res), '\n'.join(map(str, res)))
        self.assertEqual(len(res), 16)
        hand = res[1]
        self.assertIn(f'CraftingAction::reinitialize(recipe) @0x{BASE + 0x1020:x}+', hand.where)   # the second overload
        self.assertIn(f'mov r9d,0x{30000:x}', hand.detail)

    def test_mismatch_and_not_found(self):
        res = self.run_synthetic(divisor=50000, ms_per_tick=333333, rail_len=1000,
                                 drop='AL_Item::processPainting', guid=bytes(16))
        self.assertEqual(self.status(res, 'CodeView'), ['MISMATCH'])
        self.assertEqual(self.status(res, 'hand-crafting'), ['MISMATCH'])
        self.assertIn('game 50000 (/5)', res[1].detail)
        self.assertEqual(self.status(res, 'ms->ticks'), ['MISMATCH'] * 4)
        self.assertIn('game divides by 333333', res[2].detail)
        self.assertEqual(self.status(res, 'ASSEMBLY_RAIL_ITEM_LENGTH'), ['MISMATCH'])
        self.assertEqual(self.status(res, 'AL_Item::processPainting'), ['NOT FOUND'])
        self.assertEqual(sum(r.status == 'OK' for r in res), 8)

    def test_missing_overload(self):
        res = self.run_synthetic(drop='CraftingAction::reinitialize')     # drops both overloads
        self.assertEqual(res[1].status, 'NOT FOUND')

    def test_cli_exit_codes(self):
        for kw, code in (({}, 0), ({'divisor': 50000}, 1)):
            dll_bytes, pdb_bytes = synthetic_game(**kw)
            with tempfile.TemporaryDirectory() as tmp:
                dll, pdb = Path(tmp) / 'a.dll', Path(tmp) / 'a.pdb'
                dll.write_bytes(dll_bytes)
                pdb.write_bytes(pdb_bytes)
                r = subprocess.run([sys.executable, str(TOOL), '--dll', str(dll), '--pdb', str(pdb)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                bad = Path(tmp) / 'bad.pdb'
                bad.write_bytes(b'not a pdb' * 100)
                r = subprocess.run([sys.executable, str(TOOL), '--dll', str(dll), '--pdb', str(bad)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, cnc.EXIT_INPUT, r.stdout + r.stderr)
                self.assertIn('MSF 7.0', r.stderr)


@require_game
class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll, cls.pdb = cnc.native_files(GAME)
        t0 = time.perf_counter()
        cls.results = cnc.run_checks(cls.dll, cls.pdb)
        cls.seconds = time.perf_counter() - t0

    def test_all_checks_ok(self):
        self.assertEqual([r.status for r in self.results], ['OK'] * len(self.results),
                         '\n'.join(f'{r.status} {r.what} [{r.where}: {r.detail}]' for r in self.results))
        self.assertEqual(len(self.results), 16)

    def test_fast(self):
        # generous bound against a pathological slowdown only (mmap, only the needed streams; typically ~1 s)
        self.assertLess(self.seconds, 60)

    def test_cli(self):
        r = subprocess.run([sys.executable, str(TOOL), str(GAME)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(re.match(r'16/16 OK', lines[-1]), lines[-1])
        self.assertEqual(sum(ln.startswith('OK ') for ln in lines), 16)

    @unittest.skipUnless(shutil.which('objdump'), 'objdump not installed')
    def test_decoder_matches_objdump(self):
        """Instruction boundaries of the linear sweep = objdump's for every function the checks read."""
        pe, pdb = cnc.PeImage(self.dll), cnc.Pdb(self.pdb)
        try:
            names = ['CraftingAction::reinitialize', *cnc.MACHINE_FUNCTIONS, *(n for n, _w in cnc.AL_FUNCTIONS)]
            for proc in (p for n in names for p in pdb.procs(n)):
                va = pe.image_base + pe.seg_rva(proc.segment, proc.offset)
                out = subprocess.run(['objdump', '-d', '-w', f'--start-address=0x{va:x}',
                                      f'--stop-address=0x{va + proc.length:x}', str(self.dll)],
                                     capture_output=True, text=True, check=True).stdout
                want = [int(m.group(1), 16) - va for m in re.finditer(r'^\s+([0-9a-f]+):\t', out, re.M)]
                got = [i.offset for i in cnc.decode(pe.code(proc.segment, proc.offset, proc.length))]
                self.assertEqual(got, want, proc.name)
        finally:
            pdb.close()


if __name__ == '__main__':
    unittest.main()
