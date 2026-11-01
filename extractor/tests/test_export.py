"""End-to-end export tests.

ExportTests (installed game): a double export is byte-identical except timestamps, every file validates against its
schema and the manifest hashes (data and schemas) match, the pinned reference values hold, and the committed
out/<latest> is exactly what the current extractor produces (re-exported into a copy of out/, so the previous
version, warnings, templateCounts, codeHashes, schemaHashes and CHANGES.md are compared too).

FakeGameExportTests (slow; FOUNDRY_SKIP_SLOW=1 skips them): fake game folders that symlink into the installed game,
with another Steam build or a modified, emptied, missing or broken Templates dump:
  (a) a second Steam build of the same version goes to v<ver>-b<build>, the first folder stays untouched
  (b) dump differs from foundry_main_bundle -> bundle data + source-mismatch warnings
  (c) dump without files / without folder -> bundle fallback, full data
  (d) unreadable YAML in a non-exported type -> exit 0, 'source: cannot scan'
  (e) sanity gate (exit 6, nothing written; --force exports with a 'sanity:' warning)
  (f) overwrite guard (exit 7, nothing changed; --overwrite replaces)
  (g) exit 2 (schema error in a data file or in the manifest) writes nothing
The exports run in parallel subprocesses (one in-process run per phase for the mock-based exit 2 tests).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import (GAME, REPO, describe, make_fake_game, parallel, require_game, run_cli, run_export, slow,
                   tree)

from foundry_export import cli
from foundry_export import diff as diffmod
from foundry_export.checks import EXPORTED_TYPES
from foundry_export.jsonschema_lite import validate
from foundry_export.sources import FALLBACK_WARNING
from foundry_export.steam import find_game

REFERENCE = Path(__file__).with_name('reference_values.json')
TIMESTAMP_KEYS = {'generatedAt'}


def version_dir(out: Path) -> Path:
    return out / json.loads((out / 'latest.json').read_text(encoding='utf-8'))['version']


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def strip_ts(obj):
    if isinstance(obj, dict):
        return {k: strip_ts(v) for k, v in obj.items() if k not in TIMESTAMP_KEYS}
    if isinstance(obj, list):
        return [strip_ts(v) for v in obj]
    return obj


_TS_LINE = re.compile(r'^.*\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.*$', re.M)


def strip_ts_text(b: bytes) -> str:
    """CHANGES.md carries generatedAt of both versions; blank out lines with an ISO timestamp."""
    return _TS_LINE.sub('<timestamp>', b.decode('utf-8'))


def files_of(d: Path) -> list[str]:
    return sorted(tree(d))


def version_dir_problems(first: Path, second: Path, labels: tuple[str, str] = ('first', 'second')) -> list[str]:
    """Differences between two version folders: files only in one of them, differing bytes; manifest.json compared
    key by key without generatedAt, CHANGES.md without timestamp lines."""
    a, b = tree(first), tree(second)
    out = [f'only in {labels[0]}: {rel}' for rel in sorted(a.keys() - b.keys())]
    out += [f'only in {labels[1]}: {rel}' for rel in sorted(b.keys() - a.keys())]
    for rel in sorted(a.keys() & b.keys()):
        if rel == 'manifest.json':
            ma, mb = strip_ts(json.loads(a[rel])), strip_ts(json.loads(b[rel]))
            out += [f'manifest.json: {k} differs' for k in sorted(ma.keys() | mb.keys()) if ma.get(k) != mb.get(k)]
        elif rel == 'CHANGES.md':
            if strip_ts_text(a[rel]) != strip_ts_text(b[rel]):
                out.append('CHANGES.md differs')
        elif a[rel] != b[rel]:
            out.append(f'differs {rel}')
    return out


_SEL = re.compile(r'^([^\[]+)(?:\[([^=\]]+)=([^\]]+)\])?$')


def resolve(doc, spec: dict):
    """Follow a reference-value spec: optional top-level list + identifier, then a dotted path with [key=value] selectors."""
    cur = doc
    if 'list' in spec:
        cur = next((e for e in cur[spec['list']] if e.get('identifier') == spec['id']), None)
        if cur is None:
            raise KeyError(f'{spec["list"]}[identifier={spec["id"]}] not found')
    for part in spec['path'].split('.'):
        m = _SEL.match(part)
        if not m:
            raise KeyError(f'bad path part {part!r}')
        key, sk, sv = m.groups()
        cur = cur[key]
        if sk:
            cur = next((e for e in cur if str(e.get(sk)) == sv), None)
            if cur is None:
                raise KeyError(f'{key}[{sk}={sv}] not found')
    return cur


@require_game
class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='fx_export_test_')
        tmp = Path(cls._tmp.name)
        cls.out_a, cls.out_b, cls.out_repro = tmp / 'a', tmp / 'b', tmp / 'repro'
        try:
            cls.committed, cls.repro_skip = cls._prepare_repro(cls.out_repro)
            tasks = {'a': lambda: run_export(GAME, cls.out_a), 'b': lambda: run_export(GAME, cls.out_b)}
            if cls.committed and cls.out_repro.is_dir():          # prepared copy of out/
                tasks['repro'] = lambda: run_export(GAME, cls.out_repro)
            res = parallel(tasks)
        except BaseException:         # tearDownClass does not run after a failed setUpClass
            cls._tmp.cleanup()
            raise
        cls.run_a, cls.run_b, cls.run_repro = res['a'], res['b'], res.get('repro')

    @classmethod
    def _prepare_repro(cls, target: Path) -> tuple[dict | None, str | None]:
        """Copy out/index.json, latest.json, the latest version folder and its previous version into target, so that
        re-exporting the installed game there reproduces the committed folder (incl. previousVersion, count/code
        warnings and CHANGES.md)."""
        out = REPO / 'out'
        if not (out / 'latest.json').exists():
            return None, 'no committed out/latest.json yet'
        committed = read_json(out / 'latest.json')
        loc = find_game(GAME)
        installed = ((GAME / 'version.txt').read_text(encoding='utf-8').strip(), loc.build_id)
        if (committed['gameVersion'], committed.get('steamBuildId')) != installed:
            return None, (f'installed game {installed[0]} (build {installed[1]}) differs from out/latest.json '
                          f'{committed["gameVersion"]} (build {committed.get("steamBuildId")}) - export pending')
        cdir = out / committed['version']
        if not (cdir / 'manifest.json').is_file():
            return committed, None      # reported as failure by the test
        target.mkdir(parents=True)
        for name in ('index.json', 'latest.json'):
            if (out / name).exists():
                shutil.copy2(out / name, target / name)
        prev = read_json(cdir / 'manifest.json').get('previousVersion')
        for name in (committed['version'], prev):
            if name and (out / name).is_dir():
                shutil.copytree(out / name, target / name, symlinks=True)
        return committed, None

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_export_succeeds(self):
        for r in (self.run_a, self.run_b):
            self.assertEqual(r.returncode, 0, describe(r))

    def test_double_export_identical_except_timestamps(self):
        va, vb = version_dir(self.out_a), version_dir(self.out_b)
        self.assertEqual(version_dir_problems(va, vb), [])
        for name in ('index.json', 'latest.json'):
            self.assertEqual(strip_ts(read_json(self.out_a / name)), strip_ts(read_json(self.out_b / name)), name)
        self.assertEqual(sorted(p.name for p in self.out_a.iterdir()), ['index.json', 'latest.json', va.name])

    def test_files_validate_against_schemas(self):
        vdir = version_dir(self.out_a)
        schemas = {p.name[:-len('.schema.json')]: read_json(p) for p in (vdir / 'schemas').glob('*.schema.json')}
        manifest = read_json(vdir / 'manifest.json')
        self.assertEqual(validate(manifest, schemas['manifest']), [])
        self.assertIn('template_fields.json', manifest['files'])
        self.assertIn('FoundryNative.dll', manifest['codeHashes'])
        for rel, info in manifest['files'].items():
            data = (vdir / rel).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), info['sha256'], f'{rel}: sha256 mismatch')
            doc = json.loads(data)
            name = 'localization' if rel.startswith('localization/') else rel[:-len('.json')]
            self.assertEqual(validate(doc, schemas[name]), [], rel)
            self.assertEqual(doc['count'], info['count'], rel)
        self.assertEqual(sorted(manifest['schemaHashes']), sorted(p.name for p in (vdir / 'schemas').iterdir()))
        for n, sha in manifest['schemaHashes'].items():
            self.assertEqual(hashlib.sha256((vdir / 'schemas' / n).read_bytes()).hexdigest(), sha, n)
        code, msg = run_cli(['verify', str(vdir)])
        self.assertEqual(code, 0, msg)
        self.assertNotIn('not listed in manifest', msg)

    def test_known_warnings_only(self):
        """The warnings of 0.6.0.26518 are reviewed and documented; anything else needs a look (UPDATE.md step d)."""
        manifest = read_json(version_dir(self.out_a) / 'manifest.json')
        if manifest['gameVersion'] != '0.6.0.26518':
            self.skipTest(f'known warnings are listed for 0.6.0.26518, game is {manifest["gameVersion"]}')
        known = (r'recipes use undefined crafting tag base_station$',
                 r"recipe _base_pipe_adapter: no machine accepts tags \['character'\]$",
                 r'source: Templates/PlanetTemplate/\S+\.yaml line \d+ is not valid YAML - ',
                 r'source: Templates/SkyPlatformUpgradeTemplate: 11 unquoted value\(s\) contain " #" ')
        unknown = [w for w in manifest['warnings'] if not any(re.match(k, w) for k in known)]
        self.assertEqual(unknown, [])
        self.assertEqual(len(manifest['warnings']), 5, manifest['warnings'])
        self.assertEqual(manifest['templateSource'], 'StreamingAssets/Templates')

    def test_item_categories(self):
        """Every category an item references is exported with a name, and en.json carries the same English name."""
        vdir = version_dir(self.out_a)
        doc, en = read_json(vdir / 'items.json'), read_json(vdir / 'localization' / 'en.json')['strings']
        for list_key, item_key, loc_key in (('categories', 'category', 'itemCategories'),
                                            ('creativeModeCategories', 'creativeModeCategory', 'creativeModeCategories')):
            cats = {c['identifier']: c for c in doc[list_key]}
            self.assertTrue(cats, list_key)
            used = {i[item_key] for i in doc['items'] if i[item_key]}
            self.assertLessEqual(used, set(cats), list_key)
            for ident, c in cats.items():
                self.assertTrue(c['name'], f'{list_key} {ident}')
                self.assertEqual(en.get(loc_key, {}).get(ident, {}).get('name'), c['name'], f'{loc_key} {ident}')

    def test_reference_values(self):
        ref = read_json(REFERENCE)
        vdir = version_dir(self.out_a)
        docs, problems = {}, []
        for spec in ref['values']:
            doc = docs.setdefault(spec['file'], read_json(vdir / spec['file']))
            label = f'{spec["file"]} {spec.get("id", "")} {spec["path"]}'.replace('  ', ' ')
            try:
                got = resolve(doc, spec)
            except (KeyError, TypeError) as e:
                problems.append(f'{label}: missing ({e})')
                continue
            if got != spec['value']:
                problems.append(f'{label}: expected {spec["value"]!r}, got {got!r}')
        manifest = read_json(vdir / 'manifest.json')
        self.assertFalse(problems, f'{len(problems)} reference value(s) differ (pinned at {ref["pinnedAt"]}, export is '
                                   f'{manifest["gameVersion"]}, template source {manifest["templateSource"]}). Check '
                                   'CHANGES.md and the manifest warnings (with source-mismatch the bundle counts, not the '
                                   'YAML) before changing reference_values.json:\n  ' + '\n  '.join(problems))

    def test_committed_latest_is_reproducible(self):
        if self.committed is None:
            self.skipTest(self.repro_skip)
        name = self.committed['version']
        cdir = REPO / 'out' / name
        self.assertTrue((cdir / 'manifest.json').is_file(), f'out/latest.json points to {name}, which has no manifest.json')
        self.assertEqual(self.run_repro.returncode, 0, describe(self.run_repro))
        fresh = self.out_repro / name
        self.assertTrue(fresh.is_dir(), f're-export did not write {name}: {sorted(p.name for p in self.out_repro.iterdir())}')
        problems = version_dir_problems(cdir, fresh, labels=(f'out/{name}', 're-export'))
        for f in ('index.json', 'latest.json'):
            if strip_ts(read_json(REPO / 'out' / f)) != strip_ts(read_json(self.out_repro / f)):
                problems.append(f'out/{f} differs')
        self.assertFalse(problems, f'out/{name} is not what the current extractor produces (re-export needed, or the '
                                   f'extractor changed its output): {problems[:15]}')


# ---------------------------------------------------------------- fake game folders

BUILD_A, BUILD_B = '900000001', '900000002'
BROKEN_LINE = '    garbage line without colon\n'


def _broken_type(templates: Path) -> tuple[str, str]:
    """(type, file) of a non-exported template type with YAML files (QuestTemplate if present)."""
    types = sorted(p.name for p in templates.iterdir() if p.is_dir() and p.name not in EXPORTED_TYPES)
    for t in ['QuestTemplate'] + types:
        files = sorted((templates / t).glob('*.yaml')) if (templates / t).is_dir() else []
        if files:
            return t, files[0].name
    raise unittest.SkipTest('no non-exported template type with YAML files')


def _data(vdir: Path, drop: tuple[str, ...] = ()) -> dict:
    """{file: parsed JSON} for every data file of the manifest, with top-level keys `drop` removed."""
    return {rel: {k: v for k, v in read_json(vdir / rel).items() if k not in drop}
            for rel in read_json(vdir / 'manifest.json')['files']}


@require_game
@slow
class FakeGameExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='fx_fake_game_')
        try:
            cls._run_exports(Path(cls._tmp.name))
        except BaseException:         # SkipTest / failure: tearDownClass does not run
            cls._tmp.cleanup()
            raise

    @classmethod
    def _run_exports(cls, t: Path):
        cls.version = (Path(GAME) / 'version.txt').read_text(encoding='utf-8').strip()
        cls.vname, cls.bname = f'v{cls.version}', f'v{cls.version}-b{BUILD_B}'
        tpl = next(Path(GAME).resolve().glob('*_Data/StreamingAssets/Templates'), None)
        if tpl is None or not tpl.is_dir():
            raise unittest.SkipTest('game has no StreamingAssets/Templates dump')
        head = (tpl / 'CraftingRecipe' / '_base_robot01_head.yaml').read_text(encoding='utf-8')
        modified = head.replace('timeMs: 15000', 'timeMs: 12345', 1)
        if modified == head:
            raise unittest.SkipTest('_base_robot01_head.yaml has no "timeMs: 15000" any more - pick another recipe')
        cls.broken_type, broken_file = _broken_type(tpl)
        broken = (tpl / cls.broken_type / broken_file).read_text(encoding='utf-8')
        broken += ('' if broken.endswith('\n') else '\n') + BROKEN_LINE

        game_a = make_fake_game(t / 'game_a', BUILD_A)
        game_b = make_fake_game(t / 'game_b', BUILD_B)
        game_mod = make_fake_game(t / 'game_mod', BUILD_A, templates='patch',
                                  patch={'CraftingRecipe': {'_base_robot01_head.yaml': modified}})
        game_empty = make_fake_game(t / 'game_empty', BUILD_A, templates='empty')
        game_none = make_fake_game(t / 'game_none', BUILD_A, templates='none')
        game_broken = make_fake_game(t / 'game_broken', BUILD_A, templates='patch',
                                     patch={cls.broken_type: {broken_file: broken}})

        cls.out1 = t / 'out1'                                  # A, then B (-b folder), then refuse / overwrite on copies
        cls.out_mod, cls.out_empty, cls.out_none, cls.out_broken = (t / f'out_{n}' for n in ('mod', 'empty', 'none',
                                                                                             'broken'))
        cls.out_sane_refused, cls.out_sane_forced = t / 'out_sane_refused', t / 'out_sane_forced'
        for o in (cls.out_sane_refused, cls.out_sane_forced):
            cls._previous_with_5000_items(o)
        cls.sane_before = tree(cls.out_sane_refused)
        cls.out_g_docs = t / 'out_g_docs'
        cls._previous_with_5000_items(cls.out_g_docs)
        cls.g_docs_before = tree(cls.out_g_docs)

        # phase 1: everything that needs no earlier export
        r = parallel({
            'a1': lambda: run_export(game_a, cls.out1),
            'mod': lambda: run_export(game_mod, cls.out_mod),
            'empty': lambda: run_export(game_empty, cls.out_empty),
            'none': lambda: run_export(game_none, cls.out_none),
            'broken': lambda: run_export(game_broken, cls.out_broken),
            'sane_refused': lambda: run_export(game_a, cls.out_sane_refused),
            'sane_forced': lambda: run_export(game_a, cls.out_sane_forced, '--force'),
            'g_docs': lambda: cls._export_with_bad_data_doc(game_a, cls.out_g_docs),
        })
        cls.r = dict(r)
        if r['a1'].returncode != 0:
            raise AssertionError(f'plain export of the fake game failed: {describe(r["a1"])}')
        cls.ref = cls.out1 / cls.vname
        cls.after_a = tree(cls.out1)

        # phase 2: second Steam build into the same out; manifest schema error on a copy of out1
        cls.out_g_manifest = t / 'out_g_manifest'
        shutil.copytree(cls.out1, cls.out_g_manifest)
        cls.g_manifest_before = tree(cls.out_g_manifest)
        cls.r.update(parallel({
            'b': lambda: run_export(game_b, cls.out1),
            'g_manifest': lambda: cls._export_with_bad_manifest(game_a, cls.out_g_manifest),
        }))
        cls.after_b = tree(cls.out1)

        # phase 3: build A again into copies of out1 (v<ver> exists with build A but is no longer the latest)
        cls.out_refuse, cls.out_over = t / 'out_refuse', t / 'out_over'
        shutil.copytree(cls.out1, cls.out_refuse)
        shutil.copytree(cls.out1, cls.out_over)
        cls.r.update(parallel({
            'refuse': lambda: run_export(game_a, cls.out_refuse),
            'over': lambda: run_export(game_a, cls.out_over, '--overwrite'),
        }))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @staticmethod
    def _previous_with_5000_items(out: Path) -> None:
        """An out folder whose only (older) version claims 5000 items."""
        entry = {'version': 'v0.0.0.1', 'gameVersion': '0.0.0.1', 'steamBuildId': '1', 'generatedAt': '2026-01-01T00:00:00+00:00'}
        (out / 'v0.0.0.1').mkdir(parents=True)
        (out / 'v0.0.0.1' / 'manifest.json').write_text(json.dumps({
            'gameVersion': '0.0.0.1', 'steamBuildId': '1', 'templateSource': 'StreamingAssets/Templates', 'warnings': [],
            'files': {'items.json': {'count': 5000, 'sha256': '0' * 64}}}), encoding='utf-8')
        (out / 'index.json').write_text(json.dumps({'latest': 'v0.0.0.1', 'versions': [entry]}), encoding='utf-8')
        (out / 'latest.json').write_text(json.dumps(entry), encoding='utf-8')

    @staticmethod
    def _export_with_bad_data_doc(game: Path, out: Path) -> tuple[int, str]:
        real = cli.build_all

        def bad_build_all(*a, **kw):
            docs = real(*a, **kw)
            docs['items.json']['count'] = 'not-a-number'
            return docs
        with mock.patch.object(cli, 'build_all', bad_build_all):
            return run_cli(['export', str(game), str(out)])

    @staticmethod
    def _export_with_bad_manifest(game: Path, out: Path) -> tuple[int, str]:
        real, manifest_schema = cli.validate, cli.SCHEMAS['manifest']

        def bad_validate(doc, schema):
            return ['injected manifest error'] if schema is manifest_schema else real(doc, schema)
        with mock.patch.object(cli, 'validate', bad_validate):
            return run_cli(['export', str(game), str(out)])

    def ok(self, key: str) -> Path:
        r = self.r[key]
        self.assertEqual(r.returncode, 0, describe(r))
        return version_dir(getattr(self, 'out_' + key))

    def warnings(self, vdir: Path) -> list[str]:
        return read_json(vdir / 'manifest.json')['warnings']

    def assert_same_data(self, vdir: Path, skip: tuple[str, ...] = ()):
        """Data files byte-identical to the plain export (template_fields.json without templateSource)."""
        ref_files = read_json(self.ref / 'manifest.json')['files']
        self.assertEqual(sorted(read_json(vdir / 'manifest.json')['files']), sorted(ref_files))
        for rel in ref_files:
            if rel in skip:
                continue
            if rel == 'template_fields.json':
                a, b = read_json(self.ref / rel), read_json(vdir / rel)
                a.pop('templateSource')
                b.pop('templateSource')
                self.assertEqual(a, b, rel)
            else:
                self.assertEqual((self.ref / rel).read_bytes(), (vdir / rel).read_bytes(), rel)

    def require_dump_equals_bundle(self):
        """(b) and (d) need a plain export that read the dump; with an installed dump that already differs from the
        bundle they cannot test their case (test_bundle_fallback.SourceComparison reports that difference)."""
        mismatch = [x for x in self.warnings(self.ref) if x.startswith('source-mismatch:')]
        if mismatch:
            self.skipTest(f'installed Templates dump already differs from foundry_main_bundle: {mismatch[0]}')

    def assert_no_tmp(self, out: Path):
        self.assertEqual([p.name for p in out.iterdir() if p.name.startswith(('.tmp-', '.old-'))], [])

    # (a) second Steam build of the same version
    def test_a_other_build_goes_to_b_folder(self):
        r = self.r['b']
        self.assertEqual(r.returncode, 0, describe(r))
        bdir = self.out1 / self.bname
        self.assertIn(f'source: v{self.version} already exists with Steam build {BUILD_A}; build {BUILD_B} has the same '
                      f'version.txt and is written to {self.bname}', self.warnings(bdir))
        index = read_json(self.out1 / 'index.json')
        self.assertEqual(index['latest'], self.bname)
        self.assertEqual([v['version'] for v in index['versions']], [self.vname, self.bname])
        latest = read_json(self.out1 / 'latest.json')
        self.assertEqual((latest['version'], latest['steamBuildId']), (self.bname, BUILD_B))
        manifest = read_json(bdir / 'manifest.json')
        self.assertEqual((manifest['previousVersion'], manifest['steamBuildId']), (self.vname, BUILD_B))
        # same data apart from the build id in the headers
        self.assertEqual(_data(bdir, drop=('steamBuildId',)), _data(self.ref, drop=('steamBuildId',)))
        self.assertEqual(sorted(p.name for p in self.out1.iterdir()), sorted(['index.json', 'latest.json', self.vname,
                                                                              self.bname]))

    def test_a_first_folder_untouched(self):
        before = {k[len(self.vname) + 1:]: v for k, v in self.after_a.items() if k.startswith(self.vname + '/')}
        after = {k[len(self.vname) + 1:]: v for k, v in self.after_b.items() if k.startswith(self.vname + '/')}
        self.assertTrue(before)
        self.assertEqual(sorted(before), sorted(after))
        self.assertEqual([k for k in before if before[k] != after[k]], [])
        code, msg = run_cli(['verify', str(self.out1 / self.vname)])
        self.assertEqual(code, 0, msg)

    def test_a_changes_md_says_no_data_changes(self):
        text = (self.out1 / self.bname / 'CHANGES.md').read_text(encoding='utf-8')
        self.assertIn(f'# Änderungen {self.vname} → {self.bname}', text)
        self.assertRegex(text, r'\*\*Ergebnis: keine (Ä|Datenä)nderungen\*\*')
        self.assertFalse(diffmod.diff_versions(self.out1 / self.vname, self.out1 / self.bname)['hasChanges'])

    # (b) dump differs from the bundle
    def test_b_bundle_wins_over_modified_dump(self):
        self.require_dump_equals_bundle()
        vdir = self.ok('mod')
        w = self.warnings(vdir)
        mismatch = [x for x in w if x.startswith('source-mismatch: CraftingRecipe: 1 templates differ')]
        self.assertEqual(len(mismatch), 1, w)
        self.assertIn('_base_robot01_head.timeMs', mismatch[0])
        self.assertIn('dump 12345 vs bundle 15000', mismatch[0])
        self.assertEqual([x for x in w if x.startswith('source-mismatch:')], mismatch, 'only the modified recipe differs')
        self.assertIn('source: Templates dump differs from foundry_main_bundle (see source-mismatch) - data taken from '
                      'foundry_main_bundle, which is what the game loads', w)
        self.assertEqual(read_json(vdir / 'manifest.json')['templateSource'], 'foundry_main_bundle')
        self.assert_same_data(vdir)
        head = next(x for x in read_json(vdir / 'recipes.json')['recipes'] if x['identifier'] == '_base_robot01_head')
        self.assertEqual(head['timeMs'], 15000)

    # (c) dump without files / without folder
    def test_c_empty_dump_falls_back_to_bundle(self):
        vdir = self.ok('empty')
        w = self.warnings(vdir)
        fb = [x for x in w if x.startswith('source: StreamingAssets/Templates incomplete (no files for ')]
        self.assertEqual(len(fb), 1, w)
        self.assertTrue(fb[0].endswith(' - templates read from foundry_main_bundle (fallback)'), fb[0])
        for t in EXPORTED_TYPES:
            self.assertIn(t, fb[0])
        self.assert_fallback(vdir, fb[0])

    def test_c_missing_dump_falls_back_to_bundle(self):
        vdir = self.ok('none')
        self.assertIn(FALLBACK_WARNING, self.warnings(vdir))
        self.assert_fallback(vdir, FALLBACK_WARNING)

    def assert_fallback(self, vdir: Path, warning: str):
        manifest, ref = read_json(vdir / 'manifest.json'), read_json(self.ref / 'manifest.json')
        self.assertEqual(manifest['templateSource'], 'foundry_main_bundle')
        self.assertEqual(manifest['templateCounts'], ref['templateCounts'])
        self.assert_same_data(vdir)
        extra = sorted(set(manifest['warnings']) - set(ref['warnings']))
        self.assertIn(warning, extra)
        self.assertEqual([x for x in extra if not x.startswith('source:')], [], 'fallback adds non-source warnings')

    # (d) unreadable YAML in a type the extractor does not export
    def test_d_broken_non_exported_type_is_a_warning(self):
        self.require_dump_equals_bundle()
        vdir = self.ok('broken')
        w = self.warnings(vdir)
        t = self.broken_type
        cannot = [x for x in w if x.startswith(f'source: cannot scan {t}: Templates/{t}/')]
        self.assertEqual(len(cannot), 1, w)
        self.assertIn('invalid YAML', cannot[0])
        manifest = read_json(vdir / 'manifest.json')
        self.assertEqual(manifest['templateSource'], 'StreamingAssets/Templates')
        self.assertNotIn(t, manifest['templateCounts'])
        self.assertNotIn(t, read_json(vdir / 'template_fields.json')['types'])
        self.assert_same_data(vdir, skip=('template_fields.json',))

    # (e) sanity gate
    def test_e_sanity_gate_refuses_and_writes_nothing(self):
        r = self.r['sane_refused']
        self.assertEqual(r.returncode, cli.EXIT_SANITY, describe(r))
        self.assertIn('items.json: 5000 -> ', r.stderr)
        self.assertEqual(tree(self.out_sane_refused), self.sane_before)
        self.assert_no_tmp(self.out_sane_refused)

    def test_e_force_exports_with_sanity_warning(self):
        r = self.r['sane_forced']
        self.assertEqual(r.returncode, 0, describe(r))
        vdir = self.out_sane_forced / self.vname
        w = self.warnings(vdir)
        sanity = [x for x in w if x.startswith('sanity: ')]
        self.assertEqual(len(sanity), 1, w)
        self.assertTrue(sanity[0].startswith('sanity: items.json: 5000 -> '), sanity)
        self.assertTrue(sanity[0].endswith(' (exported with --force)'), sanity)
        self.assertEqual(read_json(self.out_sane_forced / 'index.json')['latest'], self.vname)
        self.assertEqual(read_json(vdir / 'manifest.json')['previousVersion'], 'v0.0.0.1')

    # (f) overwrite guard
    def test_f_same_build_not_latest_is_refused(self):
        r = self.r['refuse']
        self.assertEqual(r.returncode, cli.EXIT_OVERWRITE, describe(r))
        self.assertIn('REFUSED', r.stderr)
        self.assertEqual(tree(self.out_refuse), self.after_b)
        self.assert_no_tmp(self.out_refuse)

    def test_f_overwrite_replaces(self):
        r = self.r['over']
        self.assertEqual(r.returncode, 0, describe(r))
        code, msg = run_cli(['verify', str(self.out_over / self.vname)])
        self.assertEqual(code, 0, msg)
        self.assertEqual(read_json(self.out_over / self.vname / 'manifest.json')['steamBuildId'], BUILD_A)
        self.assertEqual(read_json(self.out_over / 'index.json')['latest'], self.bname)      # still the newest
        after = tree(self.out_over)
        self.assertEqual({k: v for k, v in after.items() if k.startswith(self.bname + '/')},
                         {k: v for k, v in self.after_b.items() if k.startswith(self.bname + '/')})
        self.assertEqual(_data(self.out_over / self.vname), _data(self.ref))
        self.assert_no_tmp(self.out_over)

    # (g) exit 2 writes nothing
    def test_g_schema_error_in_data_writes_nothing(self):
        code, msg = self.r['g_docs']
        self.assertEqual(code, 2, msg)
        self.assertIn('SCHEMA ERRORS', msg)
        self.assertIn('items.json', msg)
        self.assertEqual(tree(self.out_g_docs), self.g_docs_before)
        self.assert_no_tmp(self.out_g_docs)

    def test_g_schema_error_in_manifest_writes_nothing(self):
        code, msg = self.r['g_manifest']
        self.assertEqual(code, 2, msg)
        self.assertIn('SCHEMA ERRORS (manifest)', msg)
        self.assertEqual(tree(self.out_g_manifest), self.g_manifest_before)    # v<ver> would have been replaced
        self.assert_no_tmp(self.out_g_manifest)


if __name__ == '__main__':
    unittest.main()
