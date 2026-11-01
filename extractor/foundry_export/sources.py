"""Template sources.

  * 'yaml'   StreamingAssets/Templates/<Type>/<identifier>.yaml, the dump of the developer tool TemplateExporter
             (shipped with the game; the game itself never reads it, so it can go stale)
  * 'bundle' the FoundryTemplate ScriptableObjects of foundry_main_bundle (what the game loads), converted to the
             same values (see bundle_templates.py)

open_template_source(mode='auto') uses the dump when it is complete and agrees with the bundle for the exported
types, the bundle otherwise (with 'source:' / 'source-mismatch:' warnings).

Both return {identifier: body} per template type with body = yaml.load(CSafeLoader) of the dump file
(+ body.setdefault('identifier')), in file name order.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .game import GamePaths
from .unity_bundle import UnityFSBundle

try:
    _Loader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - libyaml missing
    _Loader = yaml.SafeLoader

FALLBACK_WARNING = 'source: StreamingAssets/Templates missing - templates read from foundry_main_bundle (fallback)'
SOURCE_MODES = ('auto', 'yaml', 'bundle')
# plain (unquoted) scalar containing ' #': YAML reads the rest of the line as a comment, the value is truncated
_HASH_COMMENT = re.compile(r'^\s*(?:- )*[A-Za-z_$][\w$]*: (?!["\'])[^\n]*?\s#')


class TemplateLoadError(Exception):
    """A template type cannot be read (missing folder, unrepairable YAML, type not in the bundle)."""


class TemplateSource:
    kind: str = ''
    label: str = ''

    def __init__(self, warnings: list[str] | None = None):
        self.warnings = warnings if warnings is not None else []
        self._cache: dict[str, dict[str, dict]] = {}

    def type_names(self) -> list[str]:
        """All template types available (sorted)."""
        raise NotImplementedError

    def load(self, type_name: str) -> dict[str, dict]:
        """All templates of one type, keyed by identifier (cached)."""
        if type_name not in self._cache:
            self._cache[type_name] = self._load(type_name)
        return self._cache[type_name]

    def _load(self, type_name: str) -> dict[str, dict]:
        raise NotImplementedError


class YamlTemplateSource(TemplateSource):
    kind, label = 'yaml', 'StreamingAssets/Templates'

    def __init__(self, folder: Path, warnings: list[str] | None = None):
        super().__init__(warnings)
        self.folder = Path(folder)

    def type_names(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir() if p.is_dir())

    def _load(self, type_name: str) -> dict[str, dict]:
        out = {}
        folder = self.folder / type_name
        if not folder.is_dir():
            raise TemplateLoadError(f'missing template folder {folder}')
        truncated = []
        for f in sorted(folder.glob('*.yaml')):
            text = f.read_text(encoding='utf-8')
            truncated += [f'{f.name}:{n}' for n, line in enumerate(text.split('\n'), 1) if _HASH_COMMENT.match(line)]
            try:
                doc = yaml.load(text, Loader=_Loader)
            except yaml.YAMLError as ex:
                doc = self._repair(text, ex, f'{type_name}/{f.name}')
            for ident, body in doc[type_name].items():
                body = dict(body or {})
                body.setdefault('identifier', ident)
                out[body['identifier']] = body
        if truncated:
            self.warnings.append(f'source: Templates/{type_name}: {len(truncated)} unquoted value(s) contain " #" - YAML reads '
                                 f'the rest as a comment, the value is truncated (e.g. {truncated[0]})')
        return out

    _LINE = re.compile(r'^(\s*(?:- )*[^\s:"][^:"]*): (.+)$')

    def _repair(self, text: str, ex: yaml.YAMLError, name: str):
        """The exporter writes plain scalars unquoted even when YAML gives them syntax meaning (e.g. '-').
        Quote the offending value (as YamlValue would for special strings) and parse again."""
        lines = text.split('\n')
        for _ in range(50):
            mark = getattr(ex, 'problem_mark', None) or getattr(ex, 'context_mark', None)
            m = self._LINE.match(lines[mark.line]) if mark is not None and mark.line < len(lines) else None
            if m is None:
                raise TemplateLoadError(f'Templates/{name}: invalid YAML ({ex})')
            val = m.group(2).replace('\\', '\\\\').replace('"', '\\"')
            self.warnings.append(f'source: Templates/{name} line {mark.line + 1} is not valid YAML - '
                                 f'value {m.group(2)!r} read as string')
            lines[mark.line] = f'{m.group(1)}: "{val}"'
            try:
                return yaml.load('\n'.join(lines), Loader=_Loader)
            except yaml.YAMLError as ex2:
                ex = ex2
        raise TemplateLoadError(f'Templates/{name}: invalid YAML ({ex})')


class BundleTemplateSource(TemplateSource):
    kind, label = 'bundle', 'foundry_main_bundle'

    def __init__(self, gp: GamePaths, warnings: list[str] | None = None, bundle: UnityFSBundle | None = None,
                 game_version: str | None = None):
        super().__init__(warnings)
        from .bundle_templates import BundleTemplates
        self.bundle = bundle or UnityFSBundle(str(gp.main_bundle))
        self.reader = BundleTemplates(self.bundle, managed_dir=gp.data / 'Managed', warnings=self.warnings,
                                      game_version=game_version)

    def type_names(self) -> list[str]:
        return self.reader.type_names()

    def _load(self, type_name: str) -> dict[str, dict]:
        try:
            return self.reader.load(type_name)
        except KeyError as ex:
            raise TemplateLoadError(str(ex.args[0]))


_GUID_REF = re.compile(r'^(.*\|)[0-9a-f]{32}$')


def _norm(v):
    """Representation differences between dump and bundle that carry no information: references have no guid in the
    bundle ('path|guid' -> 'path|'), and strings that are null in the dump can be '' in the bundle."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if v is None:
        return ''
    if isinstance(v, str):
        m = _GUID_REF.match(v)
        return m.group(1) if m else v
    return v


def _short(v, n: int = 60) -> str:
    r = repr(v)
    return r if len(r) <= n else r[:n - 3] + '...'


def compare_sources(dump: TemplateSource, bundle: TemplateSource, type_names, examples: int = 3) -> list[str]:
    """The Templates dump is a developer artifact the game never reads (it loads foundry_main_bundle), so it can go
    stale in a patch. Compare it with the bundle for the given types -> 'source-mismatch: ...' warnings."""
    out = []
    for t in type_names:
        try:
            a, b = dump.load(t), bundle.load(t)
        except Exception as ex:  # noqa: BLE001 - must not break the export
            out.append(f'source-mismatch: {t}: comparison failed ({str(ex).splitlines()[0] if str(ex) else type(ex).__name__})')
            continue
        for label, ids in (('only in Templates dump', sorted(set(a) - set(b))), ('only in foundry_main_bundle', sorted(set(b) - set(a)))):
            if ids:
                more = f' (+{len(ids) - examples} more)' if len(ids) > examples else ''
                out.append(f'source-mismatch: {t}: {len(ids)} {label}: {", ".join(ids[:examples])}{more}')
        differing, detail = [], ''
        for ident in sorted(set(a) & set(b)):
            na, nb = _norm(a[ident]), _norm(b[ident])
            if na != nb:
                fields = sorted(k for k in set(na) | set(nb) if na.get(k, '<missing>') != nb.get(k, '<missing>'))
                differing.append(f'{ident}.{"/".join(fields[:3])}')
                if not detail:
                    f0 = fields[0]
                    detail = (f'; e.g. {ident}.{f0}: dump {_short(na.get(f0, "<missing>"))} vs '
                              f'bundle {_short(nb.get(f0, "<missing>"))}')
        if differing:
            more = f' (+{len(differing) - examples} more)' if len(differing) > examples else ''
            out.append(f'source-mismatch: {t}: {len(differing)} templates differ between Templates dump and '
                       f'foundry_main_bundle: {", ".join(differing[:examples])}{more}{detail}')
    return out


def _dump_problem(gp: GamePaths, types) -> str | None:
    """Why the Templates dump cannot be used (missing, or no files for an exported type), else None."""
    if not gp.templates.is_dir():
        return 'StreamingAssets/Templates missing'
    empty = [t for t in types if not any((gp.templates / t).glob('*.yaml'))]
    if empty:
        return f'StreamingAssets/Templates incomplete (no files for {", ".join(empty)})'
    return None


def open_template_source(gp: GamePaths, warnings: list[str], bundle: UnityFSBundle | None = None,
                         mode: str = 'auto', types=()) -> TemplateSource:
    """mode 'yaml' / 'bundle' forces a source. 'auto': the bundle if the dump is missing or has no files for one of
    `types`; otherwise the dump is compared with the bundle for `types` and the bundle wins on any difference
    (the game loads the bundle) unless the bundle reader reported problems."""
    if mode not in SOURCE_MODES:
        raise ValueError(f'unknown template source mode {mode!r}')
    version_file = gp.root / 'version.txt'
    version = version_file.read_text(encoding='utf-8').strip() if version_file.exists() else None

    def from_bundle(w: list[str]) -> BundleTemplateSource:
        return BundleTemplateSource(gp, w, bundle=bundle, game_version=version)

    if mode == 'bundle':
        warnings.append('source: templates read from foundry_main_bundle (--source bundle)')
        return from_bundle(warnings)
    problem = _dump_problem(gp, types)
    if mode == 'yaml':
        if problem:
            raise TemplateLoadError(problem)
        return YamlTemplateSource(gp.templates, warnings)
    if problem:
        warnings.append(f'source: {problem} - templates read from foundry_main_bundle (fallback)')
        return from_bundle(warnings)
    dump = YamlTemplateSource(gp.templates, warnings)
    if not types:
        return dump
    bundle_warnings: list[str] = []
    try:
        bsrc = from_bundle(bundle_warnings)
        mismatch = compare_sources(dump, bsrc, types)
    except Exception as ex:  # noqa: BLE001 - the dump still works
        warnings.append(f'source-mismatch: bundle comparison failed ({ex!r}) - data taken from the Templates dump')
        return dump
    warnings += bundle_warnings + mismatch
    if not mismatch:
        return dump
    if any(w.startswith('bundle:') for w in bundle_warnings) or any('comparison failed' in m for m in mismatch):
        warnings.append('source: Templates dump differs from foundry_main_bundle, but the bundle reader reported problems - '
                        'data taken from the Templates dump; check by hand (UPDATE.md step d)')
        return dump
    warnings.append('source: Templates dump differs from foundry_main_bundle (see source-mismatch) - data taken from '
                    'foundry_main_bundle, which is what the game loads')
    return bsrc
