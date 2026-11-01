#!/usr/bin/env python3
"""Regenerate extractor/foundry_export/data/managed_types.json from the game's managed assemblies.

    python3 extractor/tools/gen_enums.py <game_dir> [--out <file>]

The table holds derived metadata only (type/field/enum names, enum values, field visibility, base types) of
all types reachable from the C3.FoundryTemplate subclasses. The bundle template fallback
(foundry_export/bundle_templates.py) reads the same metadata directly from <game>/*_Data/Managed/*.dll when
those exist and uses this committed snapshot otherwise (e.g. IL2CPP builds).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foundry_export.bundle_templates import TABLE_FILE, TypeTable  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('game_dir')
    ap.add_argument('--out', default=str(TABLE_FILE))
    args = ap.parse_args(argv)
    root = Path(args.game_dir).expanduser()
    managed = next((d / 'Managed' for d in root.glob('*_Data') if (d / 'Managed' / 'Main.dll').exists()), None)
    if managed is None:
        print(f'{root}: no *_Data/Managed/Main.dll found', file=sys.stderr)
        return 1
    version_file = root / 'version.txt'
    version = version_file.read_text(encoding='utf-8').strip() if version_file.exists() else None
    table = TypeTable.from_managed(managed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table.to_json(version), encoding='utf-8')
    n_enum = sum(1 for e in table.types.values() if e and 'enum' in e)
    print(f'{out}: {len(table.types)} types ({n_enum} enums) from {managed} (game {version})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
