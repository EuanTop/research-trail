"""Explicit question provenance; absence never implies independent exploration."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from .store import StoreError, valid_id


def validate_shape(origin):
    if origin is None:
        return
    if not isinstance(origin, dict):
        raise StoreError('Question origin must be an object or null.', 'invalid_question_origin')
    if not isinstance(origin.get('type'), str) or not origin['type'].strip():
        raise StoreError('Question origin requires a nonblank type.', 'invalid_question_origin')
    for field in ('nodeIds', 'artifactIds'):
        values = origin.get(field, [])
        if not isinstance(values, list):
            raise StoreError('Question origin references must be arrays of IDs.', 'invalid_question_origin')
        for value in values:
            valid_id(value)
    if origin['type'] == 'independent' and origin.get('nodeIds'):
        raise StoreError('Independent exploration cannot name a source node.', 'invalid_question_origin')
    if 'reason' in origin and not isinstance(origin['reason'], str):
        raise StoreError('Question origin reason must be text.', 'invalid_question_origin')
    if 'retrospective' in origin and type(origin['retrospective']) is not bool:
        raise StoreError('Question origin retrospective must be a boolean.', 'invalid_question_origin')
    if 'url' in origin:
        try:
            parsed = urlsplit(origin['url']) if isinstance(origin['url'], str) else None
            valid_url = parsed is not None and parsed.scheme in ('http', 'https') and bool(parsed.netloc)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise StoreError('Question origin URL must be an HTTP or HTTPS address.', 'invalid_question_origin')
    if 'recordedAt' in origin:
        try:
            value = datetime.fromisoformat(origin['recordedAt'].replace('Z', '+00:00'))
            if value.utcoffset() is None:
                raise ValueError('Timezone required')
        except (AttributeError, TypeError, ValueError) as exc:
            raise StoreError('Question origin recordedAt requires an ISO timestamp with timezone.', 'invalid_question_origin') from exc


def prepare(origin, aliases, stamp):
    """Normalize a submitted declaration without touching historical imports."""
    validate_shape(origin)
    if origin is not None:
        if 'nodeIds' in origin:
            origin['nodeIds'] = list(dict.fromkeys(aliases.get(key, key) for key in origin['nodeIds']))
        if 'artifactIds' in origin:
            origin['artifactIds'] = list(dict.fromkeys(origin['artifactIds']))
        origin.setdefault('recordedAt', stamp)


def validate_changed(previous, project):
    """New declarations need resolvable sources; retained history may outlive them.

    Deleting a referenced source does not erase or block old provenance. Editing
    that provenance is an explicit new declaration and validates its sources.
    """
    before = {node['id']: node.get('questionOrigin') for node in previous['nodes']}
    nodes = {node['id'] for node in project['nodes']}
    artifacts = {artifact['id'] for artifact in project['artifacts']}
    aliases = project.get('nodeAliases', {})
    for node in project['nodes']:
        origin = node.get('questionOrigin')
        if origin is None or before.get(node['id']) == origin:
            continue
        for key in origin.get('nodeIds', []):
            source = aliases.get(key, key)
            if source not in nodes:
                raise StoreError('Unknown question origin node reference: ' + key, 'invalid_reference')
            if source == node['id']:
                raise StoreError('A question cannot be its own origin.', 'invalid_question_origin')
        for key in origin.get('artifactIds', []):
            if key not in artifacts:
                raise StoreError('Unknown question origin artifact reference: ' + key, 'invalid_reference')
