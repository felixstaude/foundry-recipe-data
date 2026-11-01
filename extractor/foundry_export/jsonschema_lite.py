"""Tiny JSON-Schema validator (subset of Draft 2020-12 used by our schemas):
type, enum, const, required, properties, additionalProperties, items, $ref (local #/$defs/...), anyOf, minimum."""
from __future__ import annotations

_TYPES = {
    'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None),
    'integer': int, 'number': (int, float),
}


def _is(v, t):
    if t in ('integer', 'number') and isinstance(v, bool):
        return False
    return isinstance(v, _TYPES[t])


def validate(instance, schema, root=None, path='$', errors=None, limit=50):
    root = root or schema
    errors = [] if errors is None else errors
    if len(errors) >= limit:
        return errors
    if '$ref' in schema:
        ref = schema['$ref']
        assert ref.startswith('#/$defs/'), ref
        return validate(instance, root['$defs'][ref[len('#/$defs/'):]], root, path, errors, limit)
    if 'anyOf' in schema:
        if not any(not validate(instance, s, root, path, [], 1) for s in schema['anyOf']):
            errors.append(f'{path}: matches none of anyOf')
        return errors
    t = schema.get('type')
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_is(instance, x) for x in ts):
            errors.append(f'{path}: expected {t}, got {type(instance).__name__}')
            return errors
    if 'enum' in schema and instance not in schema['enum']:
        errors.append(f'{path}: {instance!r} not in {schema["enum"]}')
    if 'const' in schema and instance != schema['const']:
        errors.append(f'{path}: expected {schema["const"]!r}')
    if 'minimum' in schema and isinstance(instance, (int, float)) and instance < schema['minimum']:
        errors.append(f'{path}: {instance} < {schema["minimum"]}')
    if isinstance(instance, dict):
        for k in schema.get('required', []):
            if k not in instance:
                errors.append(f'{path}: missing required {k!r}')
        props = schema.get('properties', {})
        addl = schema.get('additionalProperties', True)
        for k, v in instance.items():
            if k in props:
                validate(v, props[k], root, f'{path}.{k}', errors, limit)
            elif addl is False:
                errors.append(f'{path}: unexpected property {k!r}')
            elif isinstance(addl, dict):
                validate(v, addl, root, f'{path}.{k}', errors, limit)
    if isinstance(instance, list) and 'items' in schema:
        for i, v in enumerate(instance):
            validate(v, schema['items'], root, f'{path}[{i}]', errors, limit)
            if len(errors) >= limit:
                break
    return errors
