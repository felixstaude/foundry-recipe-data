#!/usr/bin/env python3
"""
Bereitet einen lokalen Reverse-Engineering-Workspace fuer FOUNDRY vor.

    python setup.py "<Pfad zum FOUNDRY-Spielordner>" [weitere-DLL-Namen-ohne-.dll ...]

Macht:
  1. sucht die Spiel-DLLs (FOUNDRY_Data/Managed) und prueft Mono vs. IL2CPP
  2. dekompiliert sie mit ilspycmd nach ./decompiled/<DLL-Name>/ (C#-Projekt)
  3. legt ./raw/ an (hier kommt der AssetRipper-Export hin)
  4. ergaenzt .gitignore (ueberschreibt sie nicht), damit nichts davon im Repo landet

Bei einer neuen Spielversion vorher den alten Ordner wegschieben (bestehende Ordner werden uebersprungen):
    rm -rf decompiled.prev && mv decompiled decompiled.prev     (Details: UPDATE.md, Anhang "Dekompilieren")

Exit-Code 0 = alles dekompiliert, 1 = Fehler (mindestens eine DLL nicht dekompiliert, ilspycmd fehlt, falscher Ordner).

Voraussetzungen: .NET SDK, danach einmalig:  dotnet tool install -g ilspycmd
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_DLLS = ("Assembly-CSharp", "Channel3", "Main", "ThirdParty")
SKIP_PREFIXES = ("Unity", "System", "mscorlib", "Mono.", "netstandard", "Microsoft.",
                 "Newtonsoft", "nunit", "Rewired", "FMOD", "Steamworks", "com.unity")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    game = Path(sys.argv[1])
    here = Path(__file__).resolve().parent

    data_dirs = [d for d in game.glob("*_Data") if d.is_dir()]
    if not data_dirs:
        print("Kein *_Data Ordner gefunden -- ist das der FOUNDRY-Spielordner?")
        return 1
    data = data_dirs[0]
    managed = data / "Managed"

    if not managed.is_dir():
        print(f"{managed} fehlt. Wenn GameAssembly.dll im Spielordner liegt, ist das IL2CPP:")
        print("dann brauchst du Il2CppDumper statt ilspycmd.")
        return 1

    wanted = set(DEFAULT_DLLS) | set(sys.argv[2:])
    all_dlls = [p for p in sorted(managed.glob("*.dll")) if not p.name.startswith(SKIP_PREFIXES)]
    dlls = [p for p in all_dlls if p.stem in wanted]
    print("Vorhandene Spiel-DLLs:", ", ".join(p.name for p in all_dlls))
    print("Wird dekompiliert:", ", ".join(p.name for p in dlls))

    ilspy = shutil.which("ilspycmd") or str(Path.home() / ".dotnet" / "tools" / "ilspycmd")
    if not Path(ilspy).exists():
        print("ilspycmd fehlt:  dotnet tool install -g ilspycmd")
        return 1
    env = dict(os.environ, DOTNET_ROLL_FORWARD="Major")  # ilspycmd laeuft sonst nicht auf neueren .NET-Runtimes
    user_dotnet = Path.home() / ".dotnet"
    if "DOTNET_ROOT" not in env and user_dotnet.is_dir():
        env["DOTNET_ROOT"] = str(user_dotnet)  # benutzerlokales .NET; ohne findet ilspycmd die Runtime nicht

    failed = []
    for dll in dlls:
        out = here / "decompiled" / dll.stem
        if out.exists() and any(out.iterdir()):
            print(f"uebersprungen (existiert): {out.name}")
            continue
        out.mkdir(parents=True, exist_ok=True)
        print(f"dekompiliere {dll.name} ...")
        r = subprocess.run([ilspy, "-p", "-o", str(out), str(dll)], env=env)
        if r.returncode != 0:
            print(f"  FEHLER bei {dll.name} (Exit-Code {r.returncode})")
            shutil.rmtree(out, ignore_errors=True)
            failed.append(dll.name)

    (here / "raw").mkdir(exist_ok=True)
    gi = here / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [x for x in ("decompiled/", "raw/", "*.dll", "*.pdb", "game_path.txt") if x not in have]
    if missing:
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(("\n" if have and have[-1] else "") + "\n".join(missing) + "\n")
    (here / "game_path.txt").write_text(str(game), encoding="utf-8")
    if failed:
        print(f"\nFEHLGESCHLAGEN: {', '.join(failed)} nicht dekompiliert (Ausgabe oben). Exit-Code 1.")
        return 1
    print("\nFertig. Naechster Schritt: AssetRipper -> Export nach ./raw/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
