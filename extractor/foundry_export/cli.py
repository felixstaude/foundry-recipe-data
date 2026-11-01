"""foundry-export command line (see extractor/README.md and UPDATE.md).

    export [<Spielordner>] <Ausgabe> [--strict] [--force] [--overwrite] [--source auto|yaml|bundle]
                                                  writes <Ausgabe>/v<gameVersion>/ (JSON, manifest.json, CHANGES.md)
                                                  atomically, then index.json / latest.json; game folder auto-detected
    check  [--game DIR] [--out out]               compare the installed game with <out>/latest.json (exit codes CHECK_*)
    locate [--game DIR] [--field NAME]            where the game is and which version/build it has
    verify <version_dir>                          re-hash all files listed in manifest.json (data + schemas)
    diff   <old_dir|none> <new_dir> [--out FILE]  write CHANGES.md
    baseline [--game DIR] [--source ...]          accept the current template fields / enum values / DLL classes as
                                                  reviewed (also refreshes data/managed_types.json)
    itemsheet <identifier|name> [--kind ...] [--json] [--out DIR]
                                                  wiki data sheet for an item, building or assembly-line robot
    schemas [<dir>]                               write the JSON Schemas (default: package schemas/ folder)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, checks, dll_types
from . import diff as diffmod
from .build import Data, build_all, build_localization
from .game import GamePaths, locate, read_versions
from .jsonschema_lite import validate
from .localization import load_catalogs
from .schemas import FILE_SCHEMA, MANIFEST_SCHEMA_VERSION, SCHEMAS
from .sources import SOURCE_MODES, TemplateLoadError
from .steam import HINT_FILE, GameLocation, GameNotFound, find_game

SCHEMA_DIR = Path(__file__).parent / 'schemas'
CODE_DLLS = ('Main.dll', 'Channel3.dll', 'Assembly-CSharp.dll')

# export exit codes (besides 0 ok, 1 warnings with --strict, 2 schema error / usage)
EXIT_NOT_FOUND, EXIT_CHANGES_FAILED, EXIT_TEMPLATE_LOAD, EXIT_SANITY, EXIT_OVERWRITE = 3, 4, 5, 6, 7
SANITY_DROP = 0.5   # an exported data file losing more than half its entries vs. the previous version is refused
# check exit codes
CHECK_SAME, CHECK_NOT_FOUND = 0, 3
CHECK_NEW_VERSION, CHECK_NEW_BUILD, CHECK_UPDATE_PENDING, CHECK_FIRST_EXPORT, CHECK_OLDER, CHECK_INCONSISTENT = \
    10, 11, 12, 13, 14, 15


class ExportRefused(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def _dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _read_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schema_files() -> dict[str, bytes]:
    return {f'{name}.schema.json': _dump(sch) for name, sch in SCHEMAS.items()}


def write_schemas(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, data in schema_files().items():
        (target / name).write_bytes(data)


def _find(game_arg: str | None) -> tuple[GameLocation, GamePaths, dict]:
    loc = find_game(game_arg, hint_file=HINT_FILE)
    try:
        gp = locate(loc.root)
        return loc, gp, read_versions(gp, loc)
    except SystemExit as e:  # game.locate / read_versions: folder found but incomplete (e.g. mid-install)
        raise GameNotFound([f'{loc.root} (found via {loc.source}): incomplete game folder - {e}']) from None


def _code_hashes(gp: GamePaths) -> dict[str, str]:
    """sha256 of the managed game code and of the native simulation library (FoundryNative.dll)."""
    files = [gp.data / 'Managed' / n for n in CODE_DLLS] + [gp.data / 'Plugins' / 'x86_64' / 'FoundryNative.dll']
    return {f.name: _sha(f.read_bytes()) for f in files if f.is_file()}


def _code_warnings(code: dict, old_code: dict, prev_name: str | None) -> list[str]:
    out = []
    for n in sorted(set(code) | set(old_code)):
        native = n == 'FoundryNative.dll'
        hint = ('native simulation - run extractor/tools/check_native_constants.py (UPDATE.md step g)' if native
                else 'decompile and run extractor/tools/check_code_constants.py')
        if n in code and n in old_code and code[n] != old_code[n]:
            out.append(f'code-changed: {n} differs from {prev_name} - {hint}')
        elif n in old_code and n not in code:
            out.append(f'code-changed: {n} missing (present in {prev_name}) - the checks that rely on it are unverified')
        elif n in code and old_code and n not in old_code:
            out.append(f'code-changed: {n} is new (not hashed in {prev_name})')
    return out


# ---------------------------------------------------------------- export

def _version_dir_name(root: Path, ver: dict, warnings: list[str], overwrite: bool = False) -> str:
    """v<gameVersion>. An existing folder is only replaced if it holds the same Steam build AND is the newest export
    (re-export during an update); another build goes to v<gameVersion>-b<build>. Anything else is refused
    unless overwrite=True, so committed versions cannot be overwritten by accident."""
    index_p = root / 'index.json'
    latest = None
    if index_p.exists():
        try:
            latest = _read_json(index_p).get('latest')
        except ValueError:
            latest = None
    name = f'v{ver["gameVersion"]}'
    for _ in range(2):
        mf = root / name / 'manifest.json'
        if not mf.exists():
            return name
        old_build = _read_json(mf).get('steamBuildId')
        if old_build == ver['steamBuildId']:
            if name == latest or overwrite:
                return name
            raise ExportRefused(EXIT_OVERWRITE, f'{root / name} exists (same build) but is not the newest export '
                                                f'({latest}); refusing to overwrite it - use --overwrite if intended')
        if old_build and ver['steamBuildId'] and not name.endswith(f'-b{ver["steamBuildId"]}'):
            new = f'v{ver["gameVersion"]}-b{ver["steamBuildId"]}'
            warnings.append(f'source: v{ver["gameVersion"]} already exists with Steam build {old_build}; build '
                            f'{ver["steamBuildId"]} has the same version.txt and is written to {new}')
            name = new
            continue
        if overwrite:
            return name
        raise ExportRefused(EXIT_OVERWRITE, f'{root / name} exists with Steam build {old_build!r}, installed build is '
                                            f'{ver["steamBuildId"]!r}; refusing to overwrite - use --overwrite if intended')
    return name


def _sanity(outputs: list[tuple[str, dict]], prev_manifest: dict | None, prev_name: str | None) -> list[str]:
    """Problems that make an export unusable: an empty exported data file, or one losing > SANITY_DROP of its entries."""
    old = (prev_manifest or {}).get('files', {})
    bad = []
    for fname, content in outputs:
        if fname.startswith('localization/') or fname == 'template_fields.json':
            continue
        n = content['count']
        if n == 0:
            bad.append(f'{fname} is empty')
        elif fname in old and old[fname]['count'] and n < old[fname]['count'] * (1 - SANITY_DROP):
            bad.append(f'{fname}: {old[fname]["count"]} -> {n} entries vs {prev_name}')
    return bad


def _template_fields_doc(scan: dict, header: dict, source_label: str) -> dict:
    types = {t: {'count': v['count'], 'fields': sorted(v['fields'])} for t, v in sorted(scan.items()) if 'error' not in v}
    return {'schema': 'foundry-data/template_fields@1', **header, 'templateSource': source_label, 'count': len(types),
            'types': types}


def _swap_in(tmp: Path, vdir: Path) -> None:
    """Replace vdir by the fully written tmp folder (old content removed, no stale files)."""
    if vdir.exists():
        old = vdir.with_name(f'.old-{vdir.name}')
        shutil.rmtree(old, ignore_errors=True)
        os.replace(vdir, old)
        os.replace(tmp, vdir)
        shutil.rmtree(old)
    else:
        os.replace(tmp, vdir)


def cmd_export(game_arg: str | None, out_dir: str, strict: bool, force: bool, overwrite: bool, source_mode: str) -> int:
    loc, gp, ver = _find(game_arg)
    print(f'FOUNDRY {ver["gameVersion"]} (Steam build {ver["steamBuildId"] or "?"}'
          f'{", branch " + ver["steamBranch"] if ver["steamBranch"] else ""}) at {gp.root} [{loc.source}]', flush=True)
    for alt in loc.alternatives:
        print(f'  (other installation ignored: {alt})')
    if loc.update_pending and not force:
        print(f'Steam has not finished installing/updating FOUNDRY (StateFlags={loc.state_flags}). Wait, or use --force.',
              file=sys.stderr)
        return CHECK_UPDATE_PENDING
    d = Data(gp, source_mode)
    if loc.update_pending:
        d.warnings.append(f'source: Steam update pending (StateFlags {loc.state_flags}); game files may be mid-update')
    header = {'gameVersion': ver['gameVersion'], 'steamBuildId': ver['steamBuildId']}
    docs = build_all(d, header)
    catalogs = load_catalogs(gp.locale)
    loc_docs = build_localization(d, catalogs, header)

    # ---- nothing may silently drop: template types/fields/enum values, decoded AL stages, counts, game code
    scan = checks.scan(d.source.type_names(), d.source.load) | checks.scan_stages(d.stages)
    baseline = checks.load_baseline()
    d.warnings += checks.template_warnings(scan, baseline, template_source=d.source.label)
    d.warnings += checks.enum_warnings(checks.enum_values(d.source.load), baseline)
    docs['template_fields.json'] = _template_fields_doc(scan, header, d.source.label)

    errors = []
    for fname, content in docs.items():
        errors += [f'{fname}: {e}' for e in validate(content, SCHEMAS[FILE_SCHEMA[fname]])]
    for lang, content in loc_docs.items():
        errors += [f'localization/{lang}.json: {e}' for e in validate(content, SCHEMAS['localization'])]
    if errors:
        print('SCHEMA ERRORS:\n  ' + '\n  '.join(errors[:50]), file=sys.stderr)
        return 2

    root = Path(out_dir)
    try:
        vname = _version_dir_name(root, ver, d.warnings, overwrite)
    except ExportRefused as ex:
        print(f'REFUSED: {ex}', file=sys.stderr)
        return ex.code
    outputs = list(docs.items()) + [(f'localization/{k}.json', v) for k, v in loc_docs.items()]
    template_counts = {t: n for t, n in checks.template_counts(scan).items() if t != checks.STAGES_TYPE}
    prev = checks.previous_version(root, vname)
    prev_name, prev_manifest = prev if prev else (None, None)
    insane = _sanity(outputs, prev_manifest, prev_name)
    if insane and not force:
        print('REFUSED (looks like a broken export, nothing written; --force to export anyway):\n  ' + '\n  '.join(insane),
              file=sys.stderr)
        return EXIT_SANITY
    d.warnings += [f'sanity: {p} (exported with --force)' for p in insane]
    d.warnings += checks.count_warnings(prev_manifest, {f: {'count': c['count']} for f, c in outputs}, template_counts,
                                        prev_name=prev_name)
    d.warnings += dll_types.warnings_for(gp.data / 'Managed')
    code = _code_hashes(gp)
    d.warnings += _code_warnings(code, (prev_manifest or {}).get('codeHashes') or {}, prev_name)

    # ---- everything is computed and validated in memory first; then written to a temp folder and swapped in
    blobs = {fname: _dump(content) for fname, content in outputs}
    schemas = schema_files()
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    warnings = sorted(set(d.warnings))
    manifest = {'schemaVersion': MANIFEST_SCHEMA_VERSION, **ver, 'unityVersion': d.bundle.unity_version, 'generatedAt': now,
                'generator': f'foundry-export {__version__}', 'templateSource': d.source.label, 'previousVersion': prev_name,
                'languages': sorted(loc_docs), 'warnings': warnings, 'templateCounts': template_counts,
                'codeHashes': code, 'schemaHashes': {n: _sha(b) for n, b in sorted(schemas.items())},
                'files': {f: {'count': c['count'], 'sha256': _sha(blobs[f])} for f, c in outputs}}
    errs = validate(manifest, SCHEMAS['manifest'])
    if errs:
        print('SCHEMA ERRORS (manifest):', errs, file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f'.tmp-{vname}'
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / 'localization').mkdir(parents=True)
    (tmp / 'schemas').mkdir()
    for fname, data in blobs.items():
        (tmp / fname).write_bytes(data)
    for fname, data in schemas.items():
        (tmp / 'schemas' / fname).write_bytes(data)
    (tmp / 'manifest.json').write_bytes(_dump(manifest))
    vdir = root / vname
    _swap_in(tmp, vdir)

    idx_path = root / 'index.json'
    index = _read_json(idx_path) if idx_path.exists() else {'versions': []}
    entry = {'version': vname, 'gameVersion': ver['gameVersion'], 'steamBuildId': ver['steamBuildId'], 'generatedAt': now}
    index['versions'] = [v for v in index.get('versions', []) if v.get('version') != vname] + [entry]
    index['versions'].sort(key=lambda v: checks.version_key(v['version']))
    index['latest'] = index['versions'][-1]['version']
    idx_path.write_bytes(_dump({'latest': index['latest'], 'versions': index['versions']}))
    (root / 'latest.json').write_bytes(_dump(index['versions'][-1]))

    try:
        changes = diffmod.write_changes(root / prev_name if prev_name else None, vdir)
        changes_msg = f'CHANGES.md vs {prev_name or "(first export)"}'
    except Exception as ex:  # noqa: BLE001 - a diff problem must not invalidate a good export
        changes, changes_msg = None, f'CHANGES.md FAILED: {ex!r} (run: export diff ... by hand)'

    for fname, content in outputs:
        if not fname.startswith('localization/'):
            print(f'  {fname:22} {content["count"]:5}')
    print(f'  localization: {len(loc_docs)} languages; template source: {d.source.label}; {changes_msg}')
    if warnings:
        print(f'{len(warnings)} warnings (see manifest.json):')
        for w in warnings:
            print('  -', w)
    print(f'written to {vdir}')
    if changes is None:
        return EXIT_CHANGES_FAILED
    return 1 if (strict and warnings) else 0


# ---------------------------------------------------------------- check / locate / verify / baseline

def cmd_check(game_arg: str | None, out_dir: str) -> int:
    try:
        loc = find_game(game_arg, hint_file=HINT_FILE)
    except GameNotFound as e:
        print(f'STATUS: not-found\n{e}')
        return CHECK_NOT_FOUND
    newer_pending = [a for a in loc.alternative_locations
                     if a.update_pending and (a.last_updated or 0) > (loc.last_updated or 0)]
    for a in loc.alternatives:
        print(f'note: other installation {a}')
    if loc.update_pending or newer_pending:
        where = newer_pending[0].root if newer_pending else loc.root
        print(f'STATUS: update-pending (Steam is installing/updating {where}, StateFlags != 4) - wait until Steam has finished')
        return CHECK_UPDATE_PENDING
    try:
        gp = locate(loc.root)
        ver = read_versions(gp, loc)
    except SystemExit as e:
        print(f'STATUS: not-found\n{loc.root}: incomplete game folder ({e})')
        return CHECK_NOT_FOUND
    branch = f', branch {ver["steamBranch"]}' if ver['steamBranch'] else ''
    print(f'installed: {ver["gameVersion"]} (Steam build {ver["steamBuildId"] or "?"}{branch}) at {gp.root} [{loc.source}]')
    latest_p = Path(out_dir) / 'latest.json'
    if not latest_p.exists():
        print(f'STATUS: first-export ({latest_p} missing)')
        return CHECK_FIRST_EXPORT
    latest = _read_json(latest_p)
    print(f'exported:  {latest["gameVersion"]} (Steam build {latest.get("steamBuildId") or "?"}) as {latest["version"]}')
    if not (Path(out_dir) / latest['version'] / 'manifest.json').exists():
        print(f'STATUS: inconsistent - {latest_p} points to {latest["version"]}, which has no manifest.json '
              '(folder deleted? restore it or fix index.json/latest.json)')
        return CHECK_INCONSISTENT
    if latest['gameVersion'] == ver['gameVersion']:
        if latest.get('steamBuildId') == ver['steamBuildId'] or not ver['steamBuildId']:
            print('STATUS: same - no new version')
            return CHECK_SAME
        print('STATUS: new-build - same version.txt, different Steam build')
        return CHECK_NEW_BUILD
    if checks.version_key(ver['gameVersion']) < checks.version_key(latest['gameVersion']):
        print('STATUS: older-version - installed game is OLDER than out/latest.json (Steam beta branch switched?)')
        return CHECK_OLDER
    print('STATUS: new-version')
    return CHECK_NEW_VERSION


def cmd_locate(game_arg: str | None, field: str | None) -> int:
    loc, gp, ver = _find(game_arg)
    info = {'gameDir': str(gp.root), **ver, 'source': loc.source, 'manifest': str(loc.manifest) if loc.manifest else None,
            'library': str(loc.library) if loc.library else None, 'stateFlags': loc.state_flags,
            'updatePending': loc.update_pending, 'templatesDump': gp.templates.is_dir(),
            'templatesDir': str(gp.templates), 'alternatives': [str(p) for p in loc.alternatives]}
    if field:
        if field not in info:
            print(f'unknown field {field!r}; available: {", ".join(info)}', file=sys.stderr)
            return 1
        print(info[field])
    else:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def cmd_verify(vdir_s: str) -> int:
    vdir = Path(vdir_s)
    mf = vdir / 'manifest.json'
    if not mf.exists():
        print(f'{mf} missing', file=sys.stderr)
        return 1
    manifest = _read_json(mf)
    bad = []
    hashed = {rel: info['sha256'] for rel, info in manifest['files'].items()}
    hashed |= {f'schemas/{n}': h for n, h in (manifest.get('schemaHashes') or {}).items()}
    for rel, sha in sorted(hashed.items()):
        p = vdir / rel
        if not p.exists():
            bad.append(f'missing {rel}')
        elif _sha(p.read_bytes()) != sha:
            bad.append(f'changed {rel}')
    listed = set(hashed) | {'manifest.json', 'CHANGES.md'}
    extra = sorted(r for r in (str(p.relative_to(vdir)) for p in vdir.rglob('*') if p.is_file()) if r not in listed)
    for b in bad:
        print('  ' + b)
    if extra:
        print('  not listed in manifest (info): ' + ', '.join(extra))
    if not (vdir / 'CHANGES.md').exists():
        print('  CHANGES.md missing (info: regenerate with export diff)')
    if 'schemaHashes' not in manifest:
        print('  schemas/ not checked (manifest before schemaHashes)')
    print(f'{vdir}: {"OK" if not bad else "FAILED"} ({len(hashed)} files checked)')
    return 1 if bad else 0


def cmd_baseline(game_arg: str | None, source_mode: str) -> int:
    loc, gp, ver = _find(game_arg)
    d = Data(gp, source_mode)
    scan = checks.scan(d.source.type_names(), d.source.load) | checks.scan_stages(d.stages)
    broken = [f'{t}: {v["error"]}' for t, v in scan.items() if 'error' in v]
    if broken:
        print('cannot write baseline, template types failed to load:\n  ' + '\n  '.join(broken), file=sys.stderr)
        return 2
    baseline = checks.load_baseline()
    enums = checks.enum_values(d.source.load)
    for w in checks.template_warnings(scan, baseline, template_source=d.source.label) + checks.enum_warnings(enums, baseline):
        print('  accepted:', w)
    p = checks.write_baseline(scan, game_version=ver['gameVersion'], template_source=d.source.label, enums=enums)
    print(f'template baseline: {len(scan)} types from {d.source.label} (game {ver["gameVersion"]}) -> {p}')
    for w in dll_types.warnings_for(gp.data / 'Managed'):
        print('  accepted:', w)
    print(f'DLL class baseline -> {dll_types.write_baseline(gp.data / "Managed", game_version=ver["gameVersion"])}')
    if (gp.data / 'Managed' / 'Main.dll').is_file():
        from .bundle_templates import TABLE_FILE, TypeTable
        TABLE_FILE.write_text(TypeTable.from_managed(gp.data / 'Managed').to_json(ver['gameVersion']), encoding='utf-8')
        print(f'managed type metadata (bundle fallback without DLLs) -> {TABLE_FILE}')
    for w in d.warnings:
        print('  note:', w)
    return 0


def cmd_itemsheet(query: str, kind: str | None, as_json: bool, out: str | None, game_arg: str | None, source_mode: str) -> int:
    from .itemsheet import Sheets, render_markdown
    loc, gp, ver = _find(game_arg)
    sheets = Sheets(gp, ver, source_mode)
    try:
        sheet = sheets.sheet(query, kind)
    except LookupError as ex:
        print(ex, file=sys.stderr)
        return 1
    md = render_markdown(sheet)
    js = json.dumps(sheet, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if out:
        ident = next(v['identifier']['value'] for k, v in sheet.items() if k in ('item', 'building', 'robot'))
        Path(out).mkdir(parents=True, exist_ok=True)
        base = Path(out) / f'{ident}.{sheet["kind"]}'   # identifiers are shared between items, buildings and robots
        Path(f'{base}.md').write_text(md, encoding='utf-8')
        Path(f'{base}.json').write_text(js, encoding='utf-8')
        print(f'{sheet["kind"]} {ident}: {base}.md, {base}.json')
    else:
        sys.stdout.write(js if as_json else md)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='export', description='FOUNDRY data exporter (foundry-data v1)')
    sub = ap.add_subparsers(dest='cmd')
    e = sub.add_parser('export', help='export one game version')
    e.add_argument('paths', nargs='+', metavar='[game_dir] out_dir')
    e.add_argument('--game', help='game folder (overrides auto-detection)')
    e.add_argument('--strict', action='store_true', help='exit code 1 if warnings occurred')
    e.add_argument('--force', action='store_true', help='export even if Steam reports an unfinished update or the '
                                                        'sanity check fails (empty / halved data files)')
    e.add_argument('--overwrite', action='store_true', help='allow replacing an existing version folder that is not '
                                                            'the newest export or holds another build')
    e.add_argument('--source', choices=SOURCE_MODES, default='auto', help='template source (default: auto)')
    c = sub.add_parser('check', help='compare installed game with <out>/latest.json')
    c.add_argument('--game'); c.add_argument('--out', default='out')
    lo = sub.add_parser('locate', help='find the game folder')
    lo.add_argument('--game'); lo.add_argument('--field')
    v = sub.add_parser('verify', help='check file hashes of an exported version against its manifest')
    v.add_argument('version_dir')
    df = sub.add_parser('diff', help='write CHANGES.md: diff <old_dir|none> <new_dir> [--out FILE] [--json FILE]')
    df.add_argument('rest', nargs=argparse.REMAINDER)
    b = sub.add_parser('baseline', help='accept current template fields / DLL classes as reviewed (UPDATE.md step d)')
    b.add_argument('--game')
    b.add_argument('--source', choices=SOURCE_MODES, default='auto')
    it = sub.add_parser('itemsheet', help='wiki data sheet (Markdown/JSON, every value with its source) for an item, '
                                           'building or assembly-line robot')
    it.add_argument('query', nargs='+', help='identifier or name (any language)')
    it.add_argument('--kind', choices=('item', 'building', 'robot'), help='force the kind when a name matches several')
    it.add_argument('--json', action='store_true', help='print JSON instead of Markdown')
    it.add_argument('--out', help='write <identifier>.<kind>.md and .json into this folder')
    it.add_argument('--game'); it.add_argument('--source', choices=SOURCE_MODES, default='auto')
    s = sub.add_parser('schemas', help='write JSON schemas')
    s.add_argument('dir', nargs='?', default=str(SCHEMA_DIR))
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'export':
            if len(args.paths) > 2:
                ap.error('export takes [game_dir] out_dir')
            game = args.paths[0] if len(args.paths) == 2 else args.game
            return cmd_export(game, args.paths[-1], args.strict, args.force, args.overwrite, args.source)
        if args.cmd == 'check':
            return cmd_check(args.game, args.out)
        if args.cmd == 'locate':
            return cmd_locate(args.game, args.field)
        if args.cmd == 'verify':
            return cmd_verify(args.version_dir)
        if args.cmd == 'diff':
            return diffmod.main(args.rest)
        if args.cmd == 'baseline':
            return cmd_baseline(args.game, args.source)
        if args.cmd == 'itemsheet':
            return cmd_itemsheet(' '.join(args.query), args.kind, args.json, args.out, args.game, args.source)
        if args.cmd == 'schemas':
            write_schemas(Path(args.dir)); return 0
    except GameNotFound as ex:
        print(ex, file=sys.stderr)
        return EXIT_NOT_FOUND
    except TemplateLoadError as ex:
        print(f'TEMPLATE LOAD ERROR: {ex}', file=sys.stderr)
        return EXIT_TEMPLATE_LOAD
    ap.print_help(); return 1
