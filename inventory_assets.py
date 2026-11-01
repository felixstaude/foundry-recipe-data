#!/usr/bin/env python3
"""
Inventory of a Unity project exported with AssetRipper.

Zeigt, welche ScriptableObject-Typen (MonoBehaviour .asset) es gibt, wie viele,
und welche Felder sie haben -- damit man sieht, wo Assembly Line / Roboter /
Forschung usw. wirklich liegen.

Usage:
    python inventory_assets.py <AssetRipper-Export-Ordner> [--grep robot,assembly] [--out inventory.txt]
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})", re.M)
SCRIPT_RE = re.compile(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})")
TOPKEY_RE = re.compile(r"^  ([A-Za-z_][A-Za-z0-9_]*):", re.M)
SKIP_KEYS = {"m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance",
             "m_PrefabAsset", "m_GameObject", "m_Enabled", "m_EditorHideFlags",
             "m_Script", "m_Name", "m_EditorClassIdentifier"}


def build_guid_map(root: Path) -> dict:
    """guid -> Klassenname, aus den .cs.meta Dateien des Exports."""
    m = {}
    for meta in root.rglob("*.cs.meta"):
        try:
            g = GUID_RE.search(meta.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if g:
            m[g.group(1)] = meta.name[: -len(".cs.meta")]
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--grep", default="robot,assembly,research,blueprint,recipe",
                    help="Kommaliste: Stichworte fuer Klassen-/Dateinamen-Treffer")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    guid_map = build_guid_map(a.root)
    print(f"{len(guid_map)} Skript-GUIDs gefunden", file=sys.stderr)

    by_class = defaultdict(list)
    for f in a.root.rglob("*.asset"):
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "MonoBehaviour:" not in head[:400]:
            continue
        s = SCRIPT_RE.search(head)
        if not s:
            continue
        cls = guid_map.get(s.group(1), f"<unknown {s.group(1)[:8]}>")
        by_class[cls].append((f, head))

    lines = []
    lines.append(f"{'Klasse':50} {'Anzahl':>6}  Beispiel")
    lines.append("-" * 110)
    for cls, items in sorted(by_class.items(), key=lambda kv: -len(kv[1])):
        ex = items[0][0].relative_to(a.root)
        lines.append(f"{cls:50} {len(items):>6}  {ex}")

    lines.append("\n\n=== Felder pro Klasse (aus erstem Beispiel) ===")
    for cls, items in sorted(by_class.items()):
        keys = [k for k in TOPKEY_RE.findall(items[0][1]) if k not in SKIP_KEYS]
        lines.append(f"\n[{cls}] x{len(items)}")
        lines.append("  " + ", ".join(dict.fromkeys(keys)))

    words = [w.strip().lower() for w in a.grep.split(",") if w.strip()]
    lines.append(f"\n\n=== Treffer fuer {words} (Klassenname oder Dateipfad) ===")
    for cls, items in sorted(by_class.items()):
        hits = [str(f.relative_to(a.root)) for f, _ in items
                if any(w in cls.lower() or w in str(f).lower() for w in words)]
        if hits:
            lines.append(f"\n[{cls}] {len(hits)} Treffer, z.B.:")
            lines += [f"  {h}" for h in hits[:5]]

    text = "\n".join(lines)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"geschrieben: {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
