#!/usr/bin/env python3
"""Validate the published data before GitHub Pages serves it.

    python3 scripts/validate.py [--base <git ref>]

Checks (exit 1 on any error, every problem is listed):
  * every *.json file in the repository parses;
  * legacy root: index.json / latest.json point to version folders whose manifest.json lists existing files;
  * foundry-data v1 (v1/): index.json lists exactly the version folders, latest.json is its last entry,
    latest_stable.json its newest stable entry (absent if there is none);
  * every v1 version folder: manifest schemaVersion 1.x, each file of manifest.files exists with that sha256 and count,
    schemas/ match manifest.schemaHashes, every data file (and the manifest) validates against its JSON Schema,
    no files besides manifest.json, CHANGES.md, manifest.files and schemas/;
  * with --base: published v1 files are immutable - a file under v1/<version>/ that exists in <base> must be unchanged,
    unless that version is a beta in <base> (re-export of an experimental build). New versions and new files are fine.

Needs: Python >= 3.10 and the jsonschema package (pip install jsonschema).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / 'v1'
V1_POINTERS = ('index.json', 'latest.json', 'latest_stable.json')


def read_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def channel_of(manifest: dict) -> str:
    """Same rule as the extractor (foundry_export/channel.py): channel field, else derived from steamBranch."""
    ch = manifest.get('channel')
    if ch in ('stable', 'beta'):
        return ch
    return 'stable' if (manifest.get('steamBranch') or '').strip().lower() in ('', 'public') else 'beta'


def version_key(v: str) -> tuple:
    head, _, build = v.lstrip('v').partition('-b')
    return tuple(int(x) if x.isdigit() else 0 for x in head.split('.')) + ((int(build),) if build.isdigit() else (0,))


def check_json_files(errors: list[str]) -> None:
    for p in sorted(ROOT.rglob('*.json')):
        if '.git' in p.relative_to(ROOT).parts:
            continue
        try:
            read_json(p)
        except (OSError, ValueError) as ex:
            errors.append(f'{p.relative_to(ROOT)}: not valid JSON ({ex})')


def check_legacy(errors: list[str]) -> None:
    try:
        index = read_json(ROOT / 'index.json')
        latest = read_json(ROOT / 'latest.json')
    except (OSError, ValueError) as ex:
        errors.append(f'legacy index.json/latest.json unreadable: {ex}')
        return
    versions = [e.get('version') for e in index.get('versions', [])]
    if index.get('latest') not in versions:
        errors.append(f'index.json: latest {index.get("latest")!r} is not one of its versions')
    if latest.get('version') != index.get('latest'):
        errors.append(f'latest.json points to {latest.get("version")!r}, index.json to {index.get("latest")!r}')
    for v in versions:
        mf_p = ROOT / str(v) / 'manifest.json'
        if not mf_p.is_file():
            errors.append(f'index.json lists {v}, but {v}/manifest.json is missing')
            continue
        for f in read_json(mf_p).get('files', []):
            if not (ROOT / str(v) / f).is_file():
                errors.append(f'{v}/manifest.json lists {f}, which is missing')


def load_validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.exit('jsonschema missing: pip install jsonschema')
    return Draft202012Validator


def schema_for(rel: str) -> str:
    return 'localization.schema.json' if rel.startswith('localization/') else rel.replace('.json', '.schema.json')


def check_v1_version(vdir: Path, errors: list[str], Validator) -> dict | None:
    name = vdir.name
    try:
        mf = read_json(vdir / 'manifest.json')
    except (OSError, ValueError) as ex:
        errors.append(f'v1/{name}/manifest.json unreadable: {ex}')
        return None
    if not str(mf.get('schemaVersion', '')).startswith('1.'):
        errors.append(f'v1/{name}: manifest schemaVersion {mf.get("schemaVersion")!r} is not 1.x')
    files = mf.get('files') or {}
    schema_hashes = mf.get('schemaHashes') or {}
    allowed = {'manifest.json', 'CHANGES.md'} | set(files) | {f'schemas/{n}' for n in schema_hashes}
    for p in sorted(vdir.rglob('*')):
        if p.is_file() and str(p.relative_to(vdir)) not in allowed:
            errors.append(f'v1/{name}/{p.relative_to(vdir)}: not part of the export (not in manifest.json)')
    for n, h in schema_hashes.items():
        p = vdir / 'schemas' / n
        if not p.is_file():
            errors.append(f'v1/{name}/schemas/{n}: missing')
        elif sha256(p) != h:
            errors.append(f'v1/{name}/schemas/{n}: sha256 differs from manifest.json')
    schemas = {}
    for rel, info in sorted(files.items()):
        p = vdir / rel
        if not p.is_file():
            errors.append(f'v1/{name}/{rel}: missing')
            continue
        if sha256(p) != info.get('sha256'):
            errors.append(f'v1/{name}/{rel}: sha256 differs from manifest.json')
        try:
            doc = read_json(p)
        except ValueError:
            continue                                            # reported by check_json_files
        if 'count' in info and isinstance(doc, dict) and 'count' in doc and doc['count'] != info['count']:
            errors.append(f'v1/{name}/{rel}: count {doc["count"]} differs from manifest.json ({info["count"]})')
        if isinstance(doc, dict) and doc.get('gameVersion') not in (None, mf.get('gameVersion')):
            errors.append(f'v1/{name}/{rel}: gameVersion {doc.get("gameVersion")!r} differs from manifest.json')
        sname = schema_for(rel)
        sp = vdir / 'schemas' / sname
        if not sp.is_file():
            errors.append(f'v1/{name}/{rel}: no schema schemas/{sname}')
            continue
        schemas.setdefault(sname, Validator(read_json(sp)))
        for e in list(schemas[sname].iter_errors(doc))[:5]:
            errors.append(f'v1/{name}/{rel}: schema error at /{"/".join(map(str, e.absolute_path))}: {e.message[:200]}')
    sp = vdir / 'schemas' / 'manifest.schema.json'
    if sp.is_file():
        for e in list(Validator(read_json(sp)).iter_errors(mf))[:5]:
            errors.append(f'v1/{name}/manifest.json: schema error at /{"/".join(map(str, e.absolute_path))}: '
                          f'{e.message[:200]}')
    return mf


def check_v1(errors: list[str]) -> None:
    if not V1.exists():
        return
    Validator = load_validator()
    folders, manifests = [], {}
    for p in sorted(V1.iterdir()):
        if p.is_file() and p.name in V1_POINTERS:
            continue
        if p.is_dir() and (p / 'manifest.json').is_file():
            folders.append(p.name)
            mf = check_v1_version(p, errors, Validator)
            if mf is not None:
                manifests[p.name] = mf
            continue
        errors.append(f'v1/{p.name}: only version folders and {", ".join(V1_POINTERS)} belong in v1/')
    try:
        index = read_json(V1 / 'index.json')
    except (OSError, ValueError) as ex:
        errors.append(f'v1/index.json unreadable: {ex}')
        return
    entries = index.get('versions', [])
    listed = [e.get('version') for e in entries]
    if sorted(listed, key=lambda v: version_key(str(v))) != listed:
        errors.append('v1/index.json: versions are not sorted')
    if sorted(listed) != sorted(folders):
        errors.append(f'v1/index.json lists {sorted(listed)}, v1/ has {sorted(folders)}')
    for e in entries:
        mf = manifests.get(e.get('version'))
        if mf is None:
            continue
        for key in ('gameVersion', 'steamBuildId', 'title', 'description'):
            if e.get(key) != mf.get(key):
                errors.append(f'v1/index.json {e["version"]}: {key} {e.get(key)!r} differs from its manifest '
                              f'({mf.get(key)!r})')
        if e.get('channel') != channel_of(mf):
            errors.append(f'v1/index.json {e["version"]}: channel {e.get("channel")!r}, manifest says {channel_of(mf)!r}')
    if not entries:
        errors.append('v1/index.json has no versions')
        return
    if index.get('latest') != entries[-1].get('version'):
        errors.append(f'v1/index.json: latest {index.get("latest")!r} is not its newest version')
    try:
        if read_json(V1 / 'latest.json') != entries[-1]:
            errors.append('v1/latest.json is not the newest entry of v1/index.json')
    except (OSError, ValueError) as ex:
        errors.append(f'v1/latest.json unreadable: {ex}')
    stable = next((e for e in reversed(entries) if e.get('channel', 'stable') == 'stable'), None)
    ls = V1 / 'latest_stable.json'
    if stable is None and ls.exists():
        errors.append('v1/latest_stable.json exists, but v1/index.json has no stable version')
    if stable is not None:
        try:
            if read_json(ls) != stable:
                errors.append('v1/latest_stable.json is not the newest stable entry of v1/index.json')
        except (OSError, ValueError) as ex:
            errors.append(f'v1/latest_stable.json unreadable: {ex}')


def git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def check_immutable(base: str, errors: list[str]) -> None:
    """Files under v1/<version>/ that exist in base must not change (except versions that are a beta in base)."""
    changed = [line.split('\t') for line in git('diff', '--name-status', '--no-renames', base, '--', 'v1/').splitlines()]
    beta_cache: dict[str, bool] = {}

    def was_beta(version: str) -> bool:
        if version not in beta_cache:
            try:
                beta_cache[version] = channel_of(json.loads(git('show', f'{base}:v1/{version}/manifest.json'))) == 'beta'
            except (subprocess.CalledProcessError, ValueError):
                beta_cache[version] = False
        return beta_cache[version]

    for status, path in ((c[0], c[-1]) for c in changed if c):
        parts = path.split('/')
        if len(parts) < 3 or status == 'A':                    # pointer files, or a new file
            continue
        if not was_beta(parts[1]):
            errors.append(f'{path}: published file {"deleted" if status == "D" else "changed"} ({status}); '
                          f'published versions are immutable - publish a new version or new files instead')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--base', help='git ref to compare against for the immutability check (e.g. origin/main)')
    args = ap.parse_args(argv)
    errors: list[str] = []
    check_json_files(errors)
    check_legacy(errors)
    check_v1(errors)
    if args.base:
        check_immutable(args.base, errors)
    for e in errors:
        print(f'ERROR: {e}')
    n_v1 = len([p for p in V1.iterdir() if p.is_dir()]) if V1.exists() else 0
    print(f'{"FAILED" if errors else "OK"}: {len(errors)} problems; legacy root and {n_v1} v1 versions checked'
          f'{f", immutability against {args.base}" if args.base else ""}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
