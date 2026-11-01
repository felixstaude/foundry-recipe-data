#!/usr/bin/env python3
"""Check the constants the extractor hard-codes against freshly decompiled game code.

    python3 extractor/tools/check_code_constants.py [decompiled/Main]

These values live in C# code, not in templates, so the export cannot see when they change.
Run this after every re-decompile (UPDATE.md step d/g). Exit code 0 = all OK, 1 = mismatch or
pattern not found (code was restructured -> read the named method by hand).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from foundry_export import build  # noqa: E402


def _find(root: Path, rel: str, pattern: str) -> re.Match | None:
    f = root / rel
    if not f.exists():
        return None
    return re.search(pattern, f.read_text(encoding='utf-8', errors='replace'), re.S)


def checks(root: Path) -> list[tuple[str, str, str, str]]:
    """-> [(status, what, where, detail)]"""
    out = []

    def num(what, rel, pattern, expected, conv=int):
        m = _find(root, rel, pattern)
        if not m:
            out.append(('NOT FOUND', what, rel, f'pattern {pattern!r}'))
            return
        got = conv(m.group(1))
        out.append(('OK' if got == expected else 'MISMATCH', what, rel, f'game {got}, extractor {expected}'))

    num('ticks per second (build.TICKS_PER_SECOND)', 'GameRoot.cs',
        r'LOCKSTEP_TICKS_PER_SECOND\s*=\s*(\d+)', build.TICKS_PER_SECOND)
    num('slots per meter (build.SLOTS_PER_METER)', 'AssemblyLineSystem.cs',
        r'SLOTS_PER_METER\s*=\s*(\d+)', build.SLOTS_PER_METER)
    num('rail item length (build.RAIL_ITEM_LENGTH)', 'AssemblyLineSystem.cs',
        r'RAIL_ITEM_LENGTH\s*=\s*(\d+)', build.RAIL_ITEM_LENGTH)
    # The C# helper only feeds tooltips; the simulation (FoundryNative CraftingAction::reinitialize) divides by 3 and the
    # extractor follows the simulation (build.CHARACTER_SPEED). If this C# divisor changes, re-check the native side too.
    num('C# tooltip hand-crafting divisor 5 (native uses build.CHARACTER_SPEED=3), Character.getCraftingTimeForRecipeInMs', 'Character.cs',
        r'getCraftingTimeForRecipeInMs\(Character character, CraftingRecipe recipe\)\s*\{[^}]*?fpm_div\(\(long\)recipe\.timeMs \* 10000L, (\d+)L\)',
        5, lambda s: int(s) / 10000)
    num('AssemblyStageActionType.AttachComponent = 1', 'AssemblyLineObjectTemplate.cs',
        r'enum AssemblyStageActionType\s*\{\s*AttachComponent\s*=\s*(\d+),\s*MachineInteraction\s*\}', 1)
    m = _find(root, 'AssemblyLineProducerActionTemplate.cs',
              r'getItemsPerMinute\(.*?al_producer_speedInSlotsPerTick \* 60 \* 60 / AssemblyLineSystem\.RAIL_ITEM_LENGTH.*?/ 10000\.0')
    out.append(('OK' if m else 'NOT FOUND', 'AL items/min = speed*3600/RAIL_ITEM_LENGTH, fluids /10000 (build.py assembly line)',
                'AssemblyLineProducerActionTemplate.cs', 'getItemsPerMinute'))
    m = _find(root, 'ExtensionMethods.cs', r'toFPM\(this long number, int digits\)\s*\{\s*return Math\.Round\(\(float\)number / (\d+)f')
    out.append(('OK' if m and m.group(1) == '10000' else ('NOT FOUND' if not m else 'MISMATCH'),
                'fixed-point factor 10000 (*_str fields, ALPA fluid amounts)', 'ExtensionMethods.cs',
                f'game {m.group(1) if m else "?"}'))
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else HERE.parents[1] / 'decompiled' / 'Main')
    if not root.is_dir():
        print(f'{root}: not found - decompile first (UPDATE.md, Anhang "Dekompilieren")', file=sys.stderr)
        return 2
    res = checks(root)
    for status, what, where, detail in res:
        print(f'{status:9} {what}  [{where}: {detail}]')
    bad = [r for r in res if r[0] != 'OK']
    print(f'{len(res) - len(bad)}/{len(res)} OK')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
