"""Transactional SQLite records with incremental, reconstructable history."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .layout import layout_nodes, legacy_column_candidate


class StoreError(Exception):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def uid(prefix):
    return f'{prefix}-{uuid4().hex[:12]}'


def canonical(data):
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StoreError('Record must contain finite JSON values.') from exc


def object_value(value, name):
    if not isinstance(value, dict):
        raise StoreError(f'{name} must be an object.')
    return value


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise StoreError('IDs must use 1–128 letters, numbers, dots, underscores or hyphens.', 'invalid_id')
    return value


def identity(path):
    if not hasattr(path, 'read'):
        with open(path, 'rb') as source:
            return identity(source)
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: path.read(1024 * 1024), b''):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


COLLECTIONS = ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions', 'observations', 'usageRecords', 'activity')
CHECKPOINT_INTERVAL = 50


def changes(before, after, path=()):
    """Store resolved values, including generated IDs/times, rather than replaying commands."""
    if isinstance(before, dict) and isinstance(after, dict):
        result = [['remove', list(path + (key,))] for key in before if key not in after]
        for key, value in after.items():
            if key not in before:
                result.append(['set', list(path + (key,)), value])
            else:
                result.extend(changes(before[key], value, path + (key,)))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = []
        for index in range(min(len(before), len(after))):
            result.extend(changes(before[index], after[index], path + (index,)))
        if len(after) > len(before):
            result.append(['extend', list(path), after[len(before):]])
        elif len(after) < len(before):
            result.append(['truncate', list(path), len(after)])
        return result
    if type(before) is not type(after) or before != after:
        return [['set', list(path), after]]
    return []


def apply_changes(project, delta):
    for change in delta:
        action, path = change[:2]
        if not path and action == 'set':
            project = copy.deepcopy(change[2])
            continue
        target = project
        for key in path[:-1] if action in ('set', 'remove') else path:
            target = target[key]
        if action == 'set':
            target[path[-1]] = copy.deepcopy(change[2])
        elif action == 'remove':
            del target[path[-1]]
        elif action == 'extend':
            target.extend(copy.deepcopy(change[2]))
        elif action == 'truncate':
            del target[change[2]:]
        else:
            raise StoreError('Unknown history change.', 'storage_error', 500)
    return project


def disk_name(value):
    # Preserve ordinary names while avoiding Windows device names and trailing-dot aliases.
    stem = value.split('.')[0].upper()
    if value != value.lower() or value.endswith('.') or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} or re.fullmatch(r'(COM|LPT)[1-9]', stem):
        return '~' + hashlib.sha256(value.encode('utf-8')).hexdigest()
    return value


def evidence_names(artifact):
    basename = artifact.get('path', '').replace('\\', '/').rsplit('/', 1)[-1]
    encoded = disk_name(artifact['id'])
    match = re.fullmatch('(?:' + re.escape(artifact['id']) + '|' + re.escape(encoded) + r')(\.[A-Za-z0-9_-]{1,19})?', basename)
    if match:
        return basename, encoded + (match.group(1) or '').lower()
    return artifact['id'], encoded


def sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class Store:
    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'records.sqlite3'
        self._initialize()

    @contextmanager
    def _transaction(self, write=False):
        connection = None
        try:
            connection = sqlite3.connect(self.database, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA synchronous = FULL')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            code = 'storage_busy' if 'locked' in str(exc).lower() or 'busy' in str(exc).lower() else 'storage_error'
            raise StoreError('Experiment database is busy; retry the request.' if code == 'storage_busy'
                             else 'Experiment database could not complete the operation.', code, 503 if code == 'storage_busy' else 500) from exc
        finally:
            if connection is not None:
                connection.close()  # Rolls back an unfinished transaction, including validation failures.

    def _initialize(self):
        with self._transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise StoreError('This database requires a newer ExpObserver version.', 'storage_version', 500)
        if version == 0:
            with self._transaction(write=True) as db:
                for statement in (
                    'CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, '
                    'revision INTEGER NOT NULL, updated_at TEXT NOT NULL, node_count INTEGER NOT NULL, document TEXT NOT NULL, collections TEXT NOT NULL)',
                    'CREATE TABLE IF NOT EXISTS records (project_id TEXT NOT NULL REFERENCES projects(id), collection TEXT NOT NULL, '
                    'record_id TEXT NOT NULL, position INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY (project_id, collection, record_id))',
                    'CREATE INDEX IF NOT EXISTS record_order ON records(project_id, collection, position)',
                    'CREATE TABLE IF NOT EXISTS versions (project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL, '
                    'at TEXT NOT NULL, operations TEXT NOT NULL, delta TEXT NOT NULL, checkpoint TEXT, request_id TEXT, fingerprint TEXT, '
                    'PRIMARY KEY (project_id, revision), UNIQUE (project_id, request_id))',
                    'CREATE INDEX IF NOT EXISTS checkpoints ON versions(project_id, revision) WHERE checkpoint IS NOT NULL',
                    'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
                ):
                    db.execute(statement)
                db.execute('PRAGMA user_version = 1')
        from .work_sessions import initialize as initialize_work_sessions
        with self._transaction(write=True) as db:
            initialize_work_sessions(db)
        with self._transaction() as db:
            migrated = db.execute("SELECT 1 FROM settings WHERE key = 'json_migrated'").fetchone()
        if not migrated:
            self._migrate_json()

    def _migrate_json(self):
        """One transaction, once per data directory; leave original JSON backups untouched."""
        installed = []
        try:
            with self._transaction(write=True) as db:
                if db.execute("SELECT 1 FROM settings WHERE key = 'json_migrated'").fetchone():
                    return
                for path in sorted(self.root.glob('*/state.json')):
                    try:
                        bundle = json.loads(path.read_text(encoding='utf-8'))
                        project = bundle['project']
                        self._validate(project)
                        if db.execute('SELECT 1 FROM projects WHERE id = ?', (project['id'],)).fetchone():
                            raise StoreError('JSON migration would replace an existing experiment.', 'migration_conflict', 409)
                        self._sync_current(db, None, project)
                        previous = None
                        latest_revision = 0
                        for entry in bundle['history']:
                            snapshot = entry['snapshot']
                            if snapshot['id'] != project['id'] or type(snapshot['revision']) is not int or snapshot['revision'] <= latest_revision:
                                raise ValueError('History IDs and revisions must be consistent')
                            self._validate(snapshot)
                            self._migrate_evidence(path.parent, snapshot, installed)
                            self._insert_version(db, previous, snapshot, entry['operations'], entry.get('requestId'), entry.get('fingerprint'))
                            previous, latest_revision = snapshot, snapshot['revision']
                        if canonical(previous) != canonical(project):
                            raise ValueError('History must end at the current project')
                        for request_id, cached in bundle.get('requests', {}).items():
                            revision = cached.get('revision', cached.get('result', {}).get('revision'))
                            if not db.execute('SELECT 1 FROM versions WHERE project_id = ? AND revision = ?', (project['id'], revision)).fetchone():
                                raise ValueError('Request refers to a missing revision')
                            db.execute('UPDATE versions SET request_id = ?, fingerprint = ? WHERE project_id = ? AND revision = ?',
                                       (request_id, cached['fingerprint'], project['id'], revision))
                    except (KeyError, TypeError, ValueError, OSError) as exc:
                        raise StoreError(f'Could not migrate experiment file: {path.name}. Original files were preserved.', 'migration_error', 500) from exc
                db.execute("INSERT INTO settings VALUES ('json_migrated', '1')")
        except BaseException:
            for destination in installed:
                destination.unlink(missing_ok=True)
            raise

    def _workspaces(self, db):
        row = db.execute("SELECT value FROM settings WHERE key = 'workspaces'").fetchone()
        if row is None:
            return []
        try:
            entries = json.loads(row['value'])
            if not isinstance(entries, list) or any(not isinstance(entry, dict) or any(
                    not isinstance(entry.get(key), str) for key in ('id', 'path', 'addedAt')) for entry in entries):
                raise ValueError('Invalid workspace configuration')
            return entries
        except (ValueError, TypeError) as exc:
            raise StoreError('Application workspace configuration could not be read.', 'storage_error', 500) from exc

    def list_workspaces(self):
        with self._transaction() as db:
            return self._workspaces(db)

    def _disabled_workspace_roots(self, db):
        row = db.execute("SELECT value FROM settings WHERE key = 'disabled_workspaces'").fetchone()
        if row is None:
            return []
        try:
            roots = json.loads(row['value'])
            if not isinstance(roots, list) or any(not isinstance(root, str) for root in roots):
                raise ValueError('Invalid workspace configuration')
            return roots
        except (ValueError, TypeError) as exc:
            raise StoreError('Application workspace configuration could not be read.', 'storage_error', 500) from exc

    def recovery_workspaces(self):
        with self._transaction() as db:
            return {'workspaces': self._workspaces(db), 'disabledRoots': self._disabled_workspace_roots(db)}

    def add_workspace(self, body):
        object_value(body, 'Workspace')
        supplied = body.get('path')
        if not isinstance(supplied, str) or not supplied or not Path(supplied).is_absolute():
            raise StoreError('Workspace path must be an absolute existing directory.')
        try:
            path = Path(supplied).resolve(strict=True)
            if not path.is_dir():
                raise ValueError('Not a directory')
        except (OSError, ValueError, RuntimeError) as exc:
            raise StoreError('Workspace path must be an absolute existing directory.') from exc
        with self._transaction(write=True) as db:
            entries = self._workspaces(db)
            for entry in entries:
                try:
                    same = path.samefile(entry['path'])
                except OSError:
                    same = os.path.normcase(str(path)) == os.path.normcase(entry['path'])
                if same:
                    return entries
            key = hashlib.sha256(os.path.normcase(str(path)).encode('utf-8')).hexdigest()[:24]
            entries.append({'id': 'workspace-' + key, 'path': str(path), 'addedAt': now()})
            db.execute("INSERT OR REPLACE INTO settings VALUES ('workspaces', ?)", (canonical(entries),))
            disabled = [root for root in self._disabled_workspace_roots(db) if os.path.normcase(root) != os.path.normcase(str(path))]
            db.execute("INSERT OR REPLACE INTO settings VALUES ('disabled_workspaces', ?)", (canonical(disabled),))
            return entries

    def remove_workspace(self, body):
        object_value(body, 'Workspace')
        key = valid_id(body.get('id'))
        with self._transaction(write=True) as db:
            previous = self._workspaces(db)
            entries = [entry for entry in previous if entry['id'] != key]
            disabled = self._disabled_workspace_roots(db)
            disabled.extend(entry['path'] for entry in previous if entry['id'] == key and entry['path'] not in disabled)
            db.execute("INSERT OR REPLACE INTO settings VALUES ('workspaces', ?)", (canonical(entries),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('disabled_workspaces', ?)", (canonical(disabled),))
            return entries

    def _migrate_evidence(self, folder, project, installed):
        for artifact in project['artifacts']:
            if artifact.get('origin') != 'observed':
                continue
            original, encoded = evidence_names(artifact)
            source = folder / 'evidence' / original
            destination = self._dir(project['id']) / 'evidence' / encoded
            if source == destination or not source.is_file():
                continue
            if destination.exists():
                if identity(source) != identity(destination):
                    raise StoreError('Evidence migration would overwrite a retained file.', 'migration_conflict', 409)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=destination.parent)
            try:
                with os.fdopen(fd, 'wb') as target, source.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, destination)
                installed.append(destination)
                sync_directory(destination.parent)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _dir(self, project_id):
        return self.root / disk_name(valid_id(project_id))

    def _load(self, db, project_id):
        row = db.execute('SELECT document, collections FROM projects WHERE id = ?', (valid_id(project_id),)).fetchone()
        if row is None:
            raise StoreError('Experiment not found.', 'not_found', 404)
        project = json.loads(row['document'])
        project.update({name: [] for name in json.loads(row['collections'])})
        for record in db.execute('SELECT collection, document FROM records WHERE project_id = ? ORDER BY collection, position', (project_id,)):
            project[record['collection']].append(json.loads(record['document']))
        return project

    def _sync_current(self, db, previous, project):
        metadata = {key: value for key, value in project.items() if key not in COLLECTIONS}
        names = [name for name in COLLECTIONS if name in project]
        db.execute('INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
                   'name=excluded.name, description=excluded.description, revision=excluded.revision, '
                   'updated_at=excluded.updated_at, node_count=excluded.node_count, document=excluded.document, collections=excluded.collections',
                   (project['id'], project['name'], project.get('description', ''), project['revision'], project['updatedAt'],
                    len(project['nodes']), canonical(metadata), canonical(names)))
        for name in COLLECTIONS:
            before = {} if previous is None else {
                str(index) if name == 'activity' else item['id']: (index, item)
                for index, item in enumerate(previous.get(name, []))}
            after = {str(index) if name == 'activity' else item['id']: (index, item)
                     for index, item in enumerate(project.get(name, []))}
            for key in before.keys() - after.keys():
                db.execute('DELETE FROM records WHERE project_id = ? AND collection = ? AND record_id = ?', (project['id'], name, key))
            for key, (index, item) in after.items():
                encoded = canonical(item)
                if key not in before or before[key][0] != index or canonical(before[key][1]) != encoded:
                    db.execute('INSERT INTO records VALUES (?, ?, ?, ?, ?) ON CONFLICT(project_id, collection, record_id) '
                               'DO UPDATE SET position=excluded.position, document=excluded.document',
                               (project['id'], name, key, index, encoded))

    def _insert_version(self, db, previous, project, operations, request_id=None, fingerprint=None):
        checkpoint = canonical(project) if previous is None or project['revision'] % CHECKPOINT_INTERVAL == 0 else None
        delta = [] if previous is None else changes(previous, project)
        db.execute('INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                   (project['id'], project['revision'], project['updatedAt'], canonical(operations), canonical(delta), checkpoint, request_id, fingerprint))

    def _revision(self, db, project_id, revision):
        if not db.execute('SELECT 1 FROM versions WHERE project_id = ? AND revision = ?', (project_id, revision)).fetchone():
            raise StoreError('Revision not found.', 'not_found', 404)
        row = db.execute('SELECT revision, checkpoint FROM versions WHERE project_id = ? AND revision <= ? '
                         'AND checkpoint IS NOT NULL ORDER BY revision DESC LIMIT 1', (project_id, revision)).fetchone()
        project = json.loads(row['checkpoint'])
        for entry in db.execute('SELECT delta FROM versions WHERE project_id = ? AND revision > ? AND revision <= ? ORDER BY revision',
                                (project_id, row['revision'], revision)):
            project = apply_changes(project, json.loads(entry['delta']))
        return project

    def _operation_metadata(self, operations):
        result = []
        for operation in operations:
            data = operation.get('data', {})
            item = {'op': operation['op']}
            record_id = data.get('id') or data.get('runId')
            if record_id:
                item['recordId'] = record_id
            if operation['op'] == 'project.restore':
                item['restoredRevision'] = data['revision']
            result.append(item)
        return result

    def _record(self, db, previous, project, operations, request_id=None, fingerprint=None):
        project['revision'] = previous['revision'] + 1
        project['updatedAt'] = now()
        metadata = self._operation_metadata(operations)
        project['activity'] = previous.get('activity', []) + [
            {'id': uid('activity'), 'at': project['updatedAt'], 'revision': project['revision'], 'operations': metadata}]
        self._sync_current(db, previous, project)
        self._insert_version(db, previous, project, metadata, request_id, fingerprint)
        return project

    def list_projects(self):
        with self._transaction() as db:
            return [dict(row) for row in db.execute('SELECT id, name, description, revision, updated_at AS updatedAt, '
                                                    'node_count AS nodeCount FROM projects ORDER BY updated_at DESC, id')]

    def get_project(self, project_id):
        with self._transaction() as db:
            project = self._load(db, project_id)
        if not legacy_column_candidate(project['nodes'], project['edges']):
            return project
        # Recheck under the write lock: a concurrent manual edit wins. Historical
        # snapshots are left intact; the repair is a new, reconstructable version.
        with self._transaction(write=True) as db:
            previous = self._load(db, project_id)
            if not legacy_column_candidate(previous['nodes'], previous['edges']):
                return previous
            project = copy.deepcopy(previous)
            for node in project['nodes']:
                node['positionSource'] = 'auto'
            layout_nodes(project['nodes'], project['edges'])
            self._validate(project)
            self._record(db, previous, project, [{'op': 'layout.upgrade', 'data': {'strategy': 'semantic-branches-v1'}}])
            return project

    def create_project(self, data):
        object_value(data, 'Project')
        project_id = valid_id(data.get('id') or uid('study'))
        if not isinstance(data.get('name'), str) or not data['name'].strip():
            raise StoreError('Experiment name is required.')
        with self._transaction(write=True) as db:
            if db.execute('SELECT 1 FROM projects WHERE id = ?', (project_id,)).fetchone():
                raise StoreError('Experiment ID already exists.', 'conflict', 409)
            stamp = now()
            p = {'id': project_id, 'name': data['name'].strip(), 'description': data.get('description', ''),
                 'revision': 1, 'createdAt': stamp, 'updatedAt': stamp, 'sourceRoots': [],
                 **{key: [] for key in COLLECTIONS}}
            if 'sourceRoots' in data:
                p['sourceRoots'] = data['sourceRoots']
            self._validate(p)
            self._sync_current(db, None, p)
            self._insert_version(db, None, p, [{'op': 'project.create'}])
            return copy.deepcopy(p)

    def import_project(self, project):
        p = copy.deepcopy(object_value(project, 'Project'))
        self._validate(p)
        with self._transaction(write=True) as db:
            base = p['id']
            while db.execute('SELECT 1 FROM projects WHERE id = ?', (p['id'],)).fetchone():
                p['id'] = f'{base[:100]}-{uuid4().hex[:8]}'
            p['revision'] = 1
            p.setdefault('createdAt', now())
            p['updatedAt'] = now()
            p.setdefault('activity', [])
            self._sync_current(db, None, p)
            self._insert_version(db, None, p, [{'op': 'project.import'}])
            return copy.deepcopy(p)

    def _expected(self, p, body):
        if 'expectedRevision' in body and (type(body['expectedRevision']) is not int or body['expectedRevision'] < 1):
            raise StoreError('expectedRevision must be a positive integer.')
        if 'expectedRevision' in body and body['expectedRevision'] != p['revision']:
            raise StoreError(f'Experiment changed: expected revision {body["expectedRevision"]}, current {p["revision"]}. Read it again and reapply your changes.', 'revision_conflict', 409)

    def import_usage_records(self, project_id, records):
        """Internal adapter entry point: immutable source counters, replay-safe imports.

        Research batch commands cannot write this collection. Attribution may be
        revised when later frozen captures clarify an interval; counters cannot.
        """
        if not isinstance(records, list):
            raise StoreError('Usage records must be an array.')
        with self._transaction(write=True) as db:
            previous = self._load(db, project_id)
            p = copy.deepcopy(previous)
            current = p.setdefault('usageRecords', [])
            by_ref = {(r['source'], r['sourceRef']): index for index, r in enumerate(current)}
            imported = updated = 0
            for supplied in records:
                record = copy.deepcopy(object_value(supplied, 'Usage record'))
                self._validate_usage_record(record, {node['id'] for node in p['nodes']})
                key = record['source'], record['sourceRef']
                if key in by_ref:
                    index = by_ref[key]
                    old = current[index]
                    mutable = {'nodeId', 'attribution'}
                    if {k: v for k, v in old.items() if k not in mutable} != {k: v for k, v in record.items() if k not in mutable}:
                        raise StoreError('A host usage reference changed its measured counters or identity.', 'usage_conflict', 409)
                    if old != record:
                        current[index] = record
                        updated += 1
                    continue
                claimed = db.execute("SELECT project_id FROM records WHERE collection = 'usageRecords' "
                                     "AND json_extract(document, '$.source') = ? AND json_extract(document, '$.sourceRef') = ? LIMIT 1", key).fetchone()
                if claimed is not None and claimed['project_id'] != project_id:
                    raise StoreError('This host inference is already assigned to another project.', 'usage_conflict', 409)
                by_ref[key] = len(current)
                current.append(record)
                imported += 1
            if imported or updated:
                self._validate(p)
                self._record(db, previous, p, [{'op': 'usage.import', 'data': {'count': imported, 'updated': updated}}])
            return {'imported': imported, 'updated': updated}

    def _validate_usage_record(self, record, node_ids):
        valid_id(record.get('id'))
        if record.get('nodeId') is not None and record['nodeId'] not in node_ids:
            raise StoreError('Unknown usage node reference.', 'invalid_reference')
        for field in ('source', 'sourceRef', 'provider', 'model'):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise StoreError(f'Usage {field} is required.')
        for field in ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'):
            value = record.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise StoreError('Usage counters must be nonnegative integers or unknown.', 'invalid_token_counter')
        if record.get('startedAt') is None and record.get('finishedAt') is None and record.get('scope') == 'execution':
            return
        if self._observation_time(record.get('finishedAt')) < self._observation_time(record.get('startedAt')):
            raise StoreError('Usage finish must not precede its start.')

    def batch(self, project_id, body):
        object_value(body, 'Batch')
        operations = body.get('operations')
        if not isinstance(operations, list) or not operations:
            raise StoreError('operations must be a nonempty array.')
        request_id = body.get('requestId')
        if request_id is not None:
            valid_id(request_id)
        encoded_operations = canonical(operations)
        fingerprint = hashlib.sha256(encoded_operations.encode('utf-8')).hexdigest()
        with self._transaction(write=True) as db:
            project_id = valid_id(project_id)
            previous_request = db.execute('SELECT revision, fingerprint FROM versions WHERE project_id = ? AND request_id = ?',
                                          (project_id, request_id)).fetchone() if request_id else None
            if previous_request is not None:
                if previous_request['fingerprint'] not in (fingerprint, encoded_operations):
                    raise StoreError('requestId was already used for different operations.', 'idempotency_conflict', 409)
                return self._revision(db, project_id, previous_request['revision'])
            previous = self._load(db, project_id)
            self._expected(previous, body)
            p = copy.deepcopy(previous)
            unplaced = set()
            added_edges = set()
            geometry_changed = False
            for operation in operations:
                object_value(operation, 'Operation')
                data = copy.deepcopy(object_value(operation.get('data', {}), 'Operation data'))
                node_count = len(p['nodes'])
                self._apply(p, operation.get('op'), data)
                if operation.get('op') == 'edge.add':
                    added_edges.add(data['id'])
                if operation.get('op') in ('node.add', 'node.ensure') and len(p['nodes']) > node_count and 'position' not in data:
                    unplaced.add(p['nodes'][-1]['id'])
                op = operation.get('op')
                geometry_changed = geometry_changed or (
                    op in ('edge.add', 'edge.update', 'edge.delete', 'node.delete', 'node.merge') or
                    op in ('node.add', 'node.ensure') and len(p['nodes']) > node_count or
                    op == 'node.update' and any(key in data for key in ('parentId', 'kind', 'isContainer', 'collapsed', 'position', 'positionSource')))
            # Old frozen captures used exact execution IDs as relationship sources.
            # Resolve only new edges after the complete batch, so real
            # nodes (including aliases and nodes created later) take priority.
            # The incoming operations and request fingerprint remain unchanged.
            node_ids = {node['id'] for node in p['nodes']}
            runs = {run['id']: run for run in p['runs']}
            aliases = p.get('nodeAliases', {})
            for edge in p['edges']:
                if edge['id'] not in added_edges:
                    continue
                source = edge.get('source')
                if isinstance(source, str) and source not in node_ids and source not in aliases and source in runs:
                    run = runs[source]
                    edge['source'] = aliases.get(run.get('nodeId'), run.get('nodeId'))
                    run_ids = edge.get('runIds', [])
                    if edge.get('relation') == 'supports' and isinstance(run_ids, list):
                        edge['runIds'] = run_ids + ([run['id']] if run['id'] not in run_ids else [])
            self._validate(p)
            from .question_origins import validate_changed as validate_changed_origins
            validate_changed_origins(previous, p)
            if geometry_changed:
                self._place_nodes(p, unplaced)
                self._validate(p)
            self._record(db, previous, p, operations, request_id, fingerprint)
            return copy.deepcopy(p)

    def _place_nodes(self, p, unplaced=()):
        """Place automatic graph nodes while preserving manual coordinates."""
        layout_nodes(p['nodes'], p['edges'], unplaced)

    def _find(self, p, collection, key):
        if collection == 'nodes' and isinstance(key, str):
            key = p.get('nodeAliases', {}).get(key, key)
        for item in p.get(collection, []):
            if item['id'] == key:
                return item
        raise StoreError(f'{collection.rstrip("s").capitalize()} not found: {key}', 'not_found', 404)

    def _apply(self, p, op, d):
        stamp = now()
        aliases = p.get('nodeAliases', {})
        if op == 'node.ensure':
            reference_only = d.pop('referenceOnly', False)
            if type(reference_only) is not bool:
                raise StoreError('Node referenceOnly must be a boolean.')
            key = valid_id(d.get('id'))
            d['id'] = aliases.get(key, key)
            if any(node['id'] == d['id'] for node in p['nodes']):
                return
            if reference_only:
                raise StoreError('Retained node reference is not yet available: ' + key,
                                 'unresolved_reference', 409)
            op = 'node.add'
        if op in ('node.update', 'node.delete', 'node.merge') and isinstance(d.get('id'), str):
            d['id'] = aliases.get(d['id'], d['id'])
        if op == 'node.add' and isinstance(d.get('id'), str) and d['id'] in aliases:
            raise StoreError('This node was merged into existing work.', 'conflict', 409)
        if op in ('node.add', 'node.update') and 'questionOrigin' in d:
            from .question_origins import prepare as prepare_question_origin
            prepare_question_origin(d['questionOrigin'], aliases, stamp)
        prefix = op.split('.', 1)[0] if isinstance(op, str) else ''
        fields = {'node': ('parentId',), 'edge': ('source', 'target'), 'run': ('nodeId',),
                  'artifact': ('nodeId',), 'decision': ('nodeId',), 'observation': ('nodeId',)}.get(prefix, ())
        if op == 'node.merge':
            fields += ('target',)
        for field in fields:
            if isinstance(d.get(field), str):
                d[field] = aliases.get(d[field], d[field])
        if op == 'project.update':
            for key, value in d.items():
                if key not in {'id', 'revision', 'createdAt', 'updatedAt', *COLLECTIONS}:
                    p[key] = value
            return
        if op == 'node.merge':
            source = self._find(p, 'nodes', d.get('id'))
            target = self._find(p, 'nodes', d.get('target'))
            if source['id'] == target['id']:
                raise StoreError('Merge requires two different nodes.', 'invalid_merge')
            if any(node.get('parentId') == source['id'] for node in p['nodes']):
                raise StoreError('Only a leaf node can be merged.', 'invalid_merge')
            for collection in ('runs', 'artifacts', 'decisions', 'observations', 'usageRecords'):
                for record in p.get(collection, []):
                    if record.get('nodeId') == source['id']:
                        record['nodeId'] = target['id']
            for edge in p['edges']:
                for endpoint in ('source', 'target'):
                    if edge[endpoint] == source['id']:
                        edge[endpoint] = target['id']
            p['edges'] = [edge for edge in p['edges'] if edge['source'] != edge['target']]
            p['nodes'] = [node for node in p['nodes'] if node['id'] != source['id']]
            aliases = p.setdefault('nodeAliases', {})
            for key, value in list(aliases.items()):
                if value == source['id']:
                    aliases[key] = target['id']
            aliases[source['id']] = target['id']
            target['updatedAt'] = stamp
            return
        if op == 'node.delete':
            self._find(p, 'nodes', d.get('id'))
            remove = {d['id']}
            while True:
                more = {n['id'] for n in p['nodes'] if n.get('parentId') in remove}
                if more <= remove:
                    break
                remove.update(more)
            p['nodes'] = [n for n in p['nodes'] if n['id'] not in remove]
            if 'nodeAliases' in p:
                p['nodeAliases'] = {key: value for key, value in p['nodeAliases'].items() if value not in remove}
            p['edges'] = [e for e in p['edges'] if e['source'] not in remove and e['target'] not in remove]
            run_ids = {r['id'] for r in p['runs'] if r.get('nodeId') in remove}
            artifact_ids = {a['id'] for a in p['artifacts'] if a.get('nodeId') in remove or a.get('runId') in run_ids}
            p['runs'] = [r for r in p['runs'] if r['id'] not in run_ids]
            p['artifacts'] = [a for a in p['artifacts'] if a['id'] not in artifact_ids]
            p['assessments'] = [a for a in p['assessments'] if a['runId'] not in run_ids]
            p['decisions'] = [a for a in p['decisions'] if a.get('nodeId') not in remove]
            if 'observations' in p:
                p['observations'] = [o for o in p['observations'] if o.get('nodeId') not in remove]
            for record in p.get('usageRecords', []):
                if record.get('nodeId') in remove:
                    record.update(nodeId=None, attribution='project-unassigned')
            for item in p['runs'] + p['assessments'] + p['decisions']:
                if 'artifactIds' in item:
                    item['artifactIds'] = [key for key in item['artifactIds'] if key not in artifact_ids]
                if 'runIds' in item:
                    item['runIds'] = [key for key in item['runIds'] if key not in run_ids]
            return
        if op == 'run.event':
            run = self._find(p, 'runs', d.get('runId'))
            event = object_value(d.get('event'), 'Event')
            event.setdefault('id', uid('event'))
            event.setdefault('at', stamp)
            if any(e['id'] == event['id'] for e in run['events']):
                raise StoreError('Event ID already exists.', 'conflict', 409)
            run['events'].append(event)
            return
        if op == 'observation.start':
            observation_id = valid_id(d.get('id') or uid('observation'))
            observations = p.setdefault('observations', [])
            if any(o['id'] == observation_id for o in observations):
                raise StoreError('Observation ID already exists.', 'conflict', 409)
            observations.append({'id': observation_id, 'nodeId': d.get('nodeId'), 'title': d.get('title', ''),
                                 'status': 'running', 'startedAt': stamp, 'finishedAt': None, 'durationMs': None,
                                 'inputTokens': None, 'outputTokens': None, 'usageSource': '', 'usageRef': '', 'origin': 'observed'})
            return
        if op == 'observation.finish':
            observation = self._find(p, 'observations', d.get('id'))
            if observation['status'] != 'running':
                raise StoreError('Observation has already finished.', 'observation_finished', 409)
            for field in ('inputTokens', 'outputTokens'):
                if field in d:
                    if type(d[field]) is not int or d[field] < 0:
                        raise StoreError('Token counters must be nonnegative integers.', 'invalid_token_counter')
                    observation[field] = d[field]
            for field in ('usageSource', 'usageRef'):
                if field in d:
                    observation[field] = d[field]
            elapsed = (self._observation_time(stamp) - self._observation_time(observation['startedAt'])).total_seconds() * 1000
            if elapsed < 0:
                raise StoreError('System clock is earlier than the observation start; finish cannot record a negative interval.', 'invalid_observation_duration', 409)
            observation.update({'status': 'finished', 'finishedAt': stamp, 'durationMs': round(elapsed, 3)})
            return
        collection_map = {'node': 'nodes', 'edge': 'edges', 'run': 'runs', 'assessment': 'assessments',
                          'decision': 'decisions', 'artifact': 'artifacts'}
        if not isinstance(op, str) or '.' not in op:
            raise StoreError('Unknown operation.')
        kind, action = op.split('.', 1)
        collection = collection_map.get(kind)
        allowed = {'node': {'add', 'update'}, 'edge': {'add', 'update', 'delete'}, 'run': {'add', 'update'},
                   'assessment': {'add'}, 'decision': {'add'}, 'artifact': {'add'}}
        if collection is None or action not in allowed[kind]:
            raise StoreError(f'Unknown operation: {op}')
        if action == 'delete':
            self._find(p, collection, d.get('id'))
            p[collection] = [item for item in p[collection] if item['id'] != d['id']]
            return
        if action == 'update':
            existing = self._find(p, collection, d.get('id'))
            if kind == 'run':
                from .external_tasks import validate_update
                validate_update(existing, d)
            if kind == 'node' and 'position' in d:
                d.setdefault('positionSource', 'manual')
            existing.update(d)
            if kind == 'node':
                existing['updatedAt'] = stamp
            return
        d.setdefault('id', uid(kind))
        valid_id(d['id'])
        if any(item['id'] == d['id'] for item in p[collection]):
            raise StoreError(f'{kind} ID already exists.', 'conflict', 409)
        if kind == 'node':
            d.setdefault('positionSource', 'manual' if 'position' in d else 'auto')
        defaults = {
            'node': {'title': 'Untitled', 'kind': 'experiment', 'status': 'proposed', 'parentId': None,
                     'summary': '', 'conclusion': '', 'notes': '', 'nextAction': '', 'tags': [], 'position': {'x': 0, 'y': 0},
                     'importance': 'normal', 'importanceReason': '', 'pauseReason': '', 'resumeWhen': '',
                     'collapsed': False, 'createdAt': stamp, 'updatedAt': stamp},
            'edge': {'relation': 'leads_to', 'label': '', 'basis': 'unknown'},
            'run': {'title': 'Run', 'status': 'running', 'configuration': {}, 'metrics': {}, 'startedAt': stamp,
                    'finishedAt': None, 'events': [], 'artifactIds': [], 'origin': 'observed'},
            'assessment': {'metrics': {}, 'conclusion': '', 'limitations': '', 'artifactIds': [], 'supersedes': None, 'createdAt': stamp},
            'decision': {'title': 'Decision', 'conclusion': '', 'scope': '', 'nextAction': '', 'runIds': [], 'artifactIds': [], 'createdAt': stamp},
            'artifact': {'nodeId': None, 'runId': None, 'title': 'Evidence', 'path': '', 'sha256': '', 'bytes': 0,
                         'mime': 'text/plain', 'createdAt': stamp, 'origin': 'mock'},
        }
        if kind == 'artifact' and d.get('origin', 'mock') != 'mock':
            raise StoreError('Observed evidence must be registered from a real file.', 'registration_required')
        if kind == 'run' and isinstance(d.get('configuration'), dict) and d['configuration'].get('externalTask') is True and 'startedAt' not in d:
            raise StoreError('External tasks require the original reported startedAt.', 'invalid_external_task')
        p[collection].append(defaults[kind] | d)

    def _validate(self, p):
        object_value(p, 'Project')
        canonical(p)
        valid_id(p.get('id'))
        if not isinstance(p.get('name'), str) or not p['name'].strip():
            raise StoreError('Experiment name is required.')
        if not isinstance(p.get('description', ''), str) or not isinstance(p.get('activity', []), list):
            raise StoreError('Project description must be text and activity must be an array.')
        roots = p.get('sourceRoots', [])
        if not isinstance(roots, list) or any(not isinstance(r, str) or not (Path(r).is_absolute() or PureWindowsPath(r).is_absolute()) for r in roots):
            raise StoreError('sourceRoots must contain absolute directory paths.')
        groups = {}
        for collection in ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions', 'observations', 'usageRecords'):
            items = p.get(collection, [] if collection in ('observations', 'usageRecords') else None)
            if not isinstance(items, list):
                raise StoreError(f'{collection} must be an array.')
            group = {}
            for item in items:
                object_value(item, collection)
                key = valid_id(item.get('id'))
                if key in group:
                    raise StoreError(f'Duplicate {collection} ID: {key}')
                group[key] = item
            groups[collection] = group
        def ref(value, collection, optional=False):
            if optional and value is None:
                return
            if not isinstance(value, str) or value not in groups[collection]:
                raise StoreError(f'Unknown {collection} reference: {value}', 'invalid_reference')
        aliases = object_value(p.get('nodeAliases', {}), 'Node aliases')
        for source, target in aliases.items():
            valid_id(source)
            if source in groups['nodes']:
                raise StoreError('Merged node IDs cannot shadow current nodes.', 'invalid_merge')
            ref(target, 'nodes')
        def refs(values, collection):
            if not isinstance(values, list):
                raise StoreError(f'{collection} references must be an array.')
            for value in values:
                ref(value, collection)
        from .question_origins import validate_shape as validate_question_origin
        for node in p['nodes']:
            validate_question_origin(node.get('questionOrigin'))
            if 'positionSource' in node and node['positionSource'] not in ('auto', 'manual'):
                raise StoreError('Node positionSource must be auto or manual.')
            ref(node.get('parentId'), 'nodes', True)
        for node in p['nodes']:
            for field in ('title', 'kind', 'status', 'summary', 'conclusion', 'notes', 'nextAction', 'importanceReason', 'pauseReason', 'resumeWhen'):
                if not isinstance(node.get(field, ''), str):
                    raise StoreError(f'Node {field} must be text.')
            if node.get('importance', 'normal') not in ('normal', 'critical'):
                raise StoreError('Node importance must be normal or critical.')
            if not isinstance(node.get('tags', []), list) or any(not isinstance(tag, str) for tag in node.get('tags', [])):
                raise StoreError('Node tags must be an array of text values.')
            if 'isContainer' in node and type(node['isContainer']) is not bool:
                raise StoreError('Node isContainer must be a boolean.')
            if type(node.get('collapsed', False)) is not bool:
                raise StoreError('Node collapsed must be a boolean.')
            seen, current = {node['id']}, node.get('parentId')
            while current is not None:
                if current in seen:
                    raise StoreError('Node containment cannot contain a cycle.', 'containment_cycle')
                seen.add(current)
                current = groups['nodes'][current].get('parentId')
            pos = node.get('position', {})
            if not isinstance(pos, dict) or any(type(pos.get(axis)) not in (int, float) or not math.isfinite(pos[axis]) for axis in ('x', 'y')):
                raise StoreError('Node position requires finite x and y coordinates.')
        for edge in p['edges']:
            ref(edge.get('source'), 'nodes')
            ref(edge.get('target'), 'nodes')
            if 'runIds' in edge:
                refs(edge['runIds'], 'runs')
                if any(groups['runs'][key]['nodeId'] != edge['source'] for key in edge['runIds']):
                    raise StoreError('Edge execution evidence must belong to its source node.', 'invalid_reference')
            if edge['source'] == edge['target']:
                raise StoreError('A node cannot connect to itself.', 'self_edge')
            if edge.get('basis', 'unknown') not in ('observed', 'hypothesis', 'unknown'):
                raise StoreError('Unknown edge basis.')
        from .external_tasks import validate as validate_external_task
        for run in p['runs']:
            validate_external_task(run)
            ref(run.get('nodeId'), 'nodes')
            if not isinstance(run.get('title', ''), str) or not isinstance(run.get('status'), str):
                raise StoreError('Run title and status must be text.')
            self._metrics(run.get('metrics', {}))
            object_value(run.get('configuration', {}), 'Run configuration')
            refs(run.get('artifactIds', []), 'artifacts')
            if run.get('origin') not in ('mock', 'observed'):
                raise StoreError('Run origin must be mock or observed.')
            events = run.get('events', [])
            if not isinstance(events, list):
                raise StoreError('Run events must be an array.')
            event_ids = set()
            for event in events:
                object_value(event, 'Event')
                valid_id(event.get('id'))
                if event['id'] in event_ids:
                    raise StoreError('Duplicate event ID.')
                event_ids.add(event['id'])
        for artifact in p['artifacts']:
            ref(artifact.get('nodeId'), 'nodes', True)
            ref(artifact.get('runId'), 'runs', True)
            if artifact.get('origin') not in ('mock', 'observed'):
                raise StoreError('Artifact origin must be mock or observed.')
            if not isinstance(artifact.get('path', ''), str) or not isinstance(artifact.get('title', ''), str):
                raise StoreError('Artifact path and title must be text.')
            if artifact.get('origin') == 'observed':
                if not re.fullmatch(r'[a-f0-9]{64}', str(artifact.get('sha256', ''))) or type(artifact.get('bytes')) is not int or artifact['bytes'] < 0:
                    raise StoreError('Observed artifacts require a valid SHA-256 and byte count.')
        superseded = set()
        for assessment in p['assessments']:
            ref(assessment.get('runId'), 'runs')
            self._metrics(assessment.get('metrics', {}))
            refs(assessment.get('artifactIds', []), 'artifacts')
            if not isinstance(assessment.get('rubric'), str) or not assessment['rubric']:
                raise StoreError('Assessment rubric is required.')
            previous = assessment.get('supersedes')
            if previous:
                ref(previous, 'assessments')
                old = groups['assessments'][previous]
                if old['runId'] != assessment['runId'] or old['rubric'] != assessment['rubric']:
                    raise StoreError('A revised assessment must use the same run and rubric.', 'invalid_supersession')
                if previous in superseded:
                    raise StoreError('Assessment already has a revision; supersede its current revision.', 'revision_conflict', 409)
                superseded.add(previous)
                seen = {assessment['id']}
                while previous:
                    if previous in seen:
                        raise StoreError('Assessment revisions cannot contain a cycle.')
                    seen.add(previous)
                    previous = groups['assessments'][previous].get('supersedes')
        for decision in p['decisions']:
            ref(decision.get('nodeId'), 'nodes')
            refs(decision.get('runIds', []), 'runs')
            refs(decision.get('artifactIds', []), 'artifacts')
        usage_refs = set()
        for record in p.get('usageRecords', []):
            self._validate_usage_record(record, groups['nodes'])
            key = record['source'], record['sourceRef']
            if key in usage_refs:
                raise StoreError('Duplicate host usage source/reference.', 'duplicate_usage_ref', 409)
            usage_refs.add(key)
        for observation in p.get('observations', []):
            ref(observation.get('nodeId'), 'nodes')
            if observation.get('origin') not in ('observed', 'mock') or observation.get('status') not in ('running', 'finished'):
                raise StoreError('Observations require observed or mock origin and running or finished status.')
            if not isinstance(observation.get('title'), str):
                raise StoreError('Observation title must be text.')
            started = self._observation_time(observation.get('startedAt'))
            duration = observation.get('durationMs')
            if observation['status'] == 'running':
                if observation.get('finishedAt') is not None or duration is not None:
                    raise StoreError('Running observations cannot have finish time or duration.')
            else:
                finished = self._observation_time(observation.get('finishedAt'))
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                    raise StoreError('Finished observations require a nonnegative finite duration.')
                elapsed = (finished - started).total_seconds() * 1000
                if elapsed < 0 or abs(duration - elapsed) > 1:
                    raise StoreError('Observation duration must agree with a nonnegative start/finish interval within 1 ms.', 'invalid_observation_duration')
            source, usage_ref = observation.get('usageSource', ''), observation.get('usageRef', '')
            if not isinstance(source, str) or not isinstance(usage_ref, str):
                raise StoreError('Usage source and reference must be text.')
            for field in ('inputTokens', 'outputTokens'):
                value = observation.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise StoreError('Token counters must be nonnegative integers or unknown.', 'invalid_token_counter')
                if value is not None and not source.strip():
                    raise StoreError('Supplied token counters require a runtime or provider usage source.', 'usage_source_required')
            if usage_ref:
                if not source.strip():
                    raise StoreError('Usage references require a usage source.', 'usage_source_required')
                key = (source.strip(), usage_ref.strip())
                if key in usage_refs:
                    raise StoreError('This usage source and reference were already recorded on another observation.', 'duplicate_usage_ref', 409)
                usage_refs.add(key)

    def _observation_time(self, value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.utcoffset() is None:
                raise ValueError('Timezone required')
            return parsed
        except (AttributeError, TypeError, ValueError) as exc:
            raise StoreError('Observation times must be ISO timestamps with a timezone.') from exc

    def _metrics(self, metrics):
        object_value(metrics, 'Metrics')
        # Preserve native result structure. Flattening is a presentation concern.
        pending = [metrics]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise StoreError('Metric object keys must be strings.')
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif value is not None and type(value) not in (int, float, str, bool):
                raise StoreError('Metrics must contain JSON values.')
        canonical(metrics)

    def register_artifact(self, project_id, body):
        object_value(body, 'Artifact')
        if not isinstance(body.get('path'), str) or not body['path']:
            raise StoreError('Artifact path is required.')
        source = Path(body['path']).expanduser().resolve()
        destination = temporary = None
        installed = False
        try:
            with self._transaction(write=True) as db:
                previous = self._load(db, project_id)
                self._expected(previous, body)
                p = copy.deepcopy(previous)
                body = dict(body)
                if isinstance(body.get('nodeId'), str):
                    body['nodeId'] = p.get('nodeAliases', {}).get(body['nodeId'], body['nodeId'])
                allowed = [self._dir(project_id).resolve()] + [Path(root).resolve() for root in p.get('sourceRoots', []) if Path(root).is_absolute()]
                if not any(source.is_relative_to(root) for root in allowed):
                    raise StoreError('Source file is outside this experiment’s source roots.', 'path_not_allowed', 403)
                if not source.is_file():
                    raise StoreError('Source file does not exist.', 'not_found', 404)
                artifact_id = valid_id(body.get('id') or uid('artifact'))
                if any(a['id'] == artifact_id for a in p['artifacts']):
                    raise StoreError('Artifact ID already exists.', 'conflict', 409)
                destination_dir = self._dir(project_id) / 'evidence'
                destination_dir.mkdir(parents=True, exist_ok=True)
                suffix = source.suffix.lower() if re.fullmatch(r'\.[A-Za-z0-9_-]{1,19}', source.suffix) else ''
                destination = destination_dir / f'{disk_name(artifact_id)}{suffix}'
                if destination.exists():
                    raise StoreError('Artifact ID already has retained evidence; use a new ID.', 'conflict', 409)
                fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=destination_dir)
                digest, size = hashlib.sha256(), 0
                with os.fdopen(fd, 'wb') as target, open(source, 'rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if ('sha256' in body and body['sha256'] != digest.hexdigest()) or ('bytes' in body and body['bytes'] != size):
                    raise StoreError('Captured evidence changed before registration; the original snapshot is still required.',
                                     'evidence_changed', 409)
                artifact = {'id': artifact_id, 'nodeId': body.get('nodeId'), 'runId': body.get('runId'),
                            'title': body.get('title') or source.name, 'path': str(destination),
                            'sourcePath': str(source), 'sha256': digest.hexdigest(), 'bytes': size,
                            'mime': mimetypes.guess_type(source.name)[0] or 'application/octet-stream',
                            'createdAt': now(), 'origin': 'observed'}
                if 'capturedAt' in body:
                    self._observation_time(body['capturedAt'])
                    artifact['capturedAt'] = body['capturedAt']
                p['artifacts'].append(artifact)
                if artifact['runId']:
                    self._find(p, 'runs', artifact['runId']).setdefault('artifactIds', []).append(artifact_id)
                self._validate(p)
                os.replace(temporary, destination)
                installed = True
                sync_directory(destination_dir)
                self._record(db, previous, p, [{'op': 'artifact.register', 'data': {'id': artifact_id, 'title': artifact['title']}}])
            return copy.deepcopy(artifact)
        except BaseException:
            if installed:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def _artifact_location(self, project_id, project, artifact):
        evidence = (self._dir(project_id) / 'evidence').resolve()
        recorded = Path(artifact.get('path', ''))
        if artifact.get('origin') == 'observed':
            # The retained copy is addressed inside the current data directory.
            # An absolute path from an export is never followed outside it.
            _, basename = evidence_names(artifact)
            path = (evidence / basename).resolve()
            if not path.is_relative_to(evidence):
                raise StoreError('This evidence has no registered local copy.', 'evidence_unavailable', 404)
            return path
        path = recorded.resolve()
        allowed_mock = artifact.get('origin') == 'mock' and any(
            Path(root).is_absolute() and path.is_relative_to(Path(root).resolve()) for root in project.get('sourceRoots', []))
        if not path.is_relative_to(evidence) and not allowed_mock:
            raise StoreError('This evidence has no registered local copy.', 'evidence_unavailable', 404)
        return path

    def _verify_evidence(self, stream, artifact):
        sha256, size = identity(stream)
        if sha256 != artifact.get('sha256') or size != artifact.get('bytes'):
            raise StoreError('Evidence content changed after registration.', 'evidence_changed', 409)

    def artifact_metadata(self, project_id, artifact_id):
        with self._transaction() as db:
            p = self._load(db, project_id)
            artifact = self._find(p, 'artifacts', artifact_id)
            path = self._artifact_location(project_id, p, artifact)
            try:
                with path.open('rb') as stream:
                    self._verify_evidence(stream, artifact)
            except OSError as exc:
                raise StoreError('Evidence file is missing.', 'evidence_missing', 404) from exc
            return copy.deepcopy(artifact) | {'path': str(path), 'verified': True}

    def artifact_content(self, project_id, artifact_id, offset=None, limit=None):
        bounded = offset is not None or limit is not None
        if bounded:
            offset = 0 if offset is None else offset
            limit = 262144 if limit is None else limit
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1024 * 1024:
                raise StoreError('Preview offset must be nonnegative and limit must be 1–1048576 bytes.', 'invalid_preview_range')
        with self._transaction() as db:
            p = self._load(db, project_id)
            artifact = self._find(p, 'artifacts', artifact_id)
            path = self._artifact_location(project_id, p, artifact)
            try:
                with path.open('rb') as stream:
                    self._verify_evidence(stream, artifact)
                    stream.seek(offset if bounded else 0)
                    raw = stream.read(limit) if bounded else stream.read()
            except OSError as exc:
                raise StoreError('Evidence file is missing.', 'evidence_missing', 404) from exc
            return raw, copy.deepcopy(artifact)

    def history(self, project_id):
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM projects WHERE id = ?', (valid_id(project_id),)).fetchone():
                raise StoreError('Experiment not found.', 'not_found', 404)
            entries = []
            for row in db.execute('SELECT revision, at, operations, request_id, fingerprint FROM versions WHERE project_id = ? ORDER BY revision', (project_id,)):
                entry = {'revision': row['revision'], 'at': row['at'], 'operations': json.loads(row['operations'])}
                if row['request_id'] is not None:
                    entry.update({'requestId': row['request_id'], 'fingerprint': row['fingerprint']})
                entries.append(entry)
            return entries

    def restore(self, project_id, body):
        object_value(body, 'Restore')
        if 'expectedRevision' not in body:
            raise StoreError('expectedRevision is required for restore.')
        if type(body.get('revision')) is not int or body['revision'] < 1:
            raise StoreError('revision must be a positive integer.')
        with self._transaction(write=True) as db:
            previous = self._load(db, project_id)
            self._expected(previous, body)
            p = self._revision(db, project_id, body['revision'])
            if 'usageRecords' in previous:
                p['usageRecords'] = copy.deepcopy(previous['usageRecords'])
                present = {node['id'] for node in p['nodes']}
                for record in p['usageRecords']:
                    if record.get('nodeId') is not None and record['nodeId'] not in present:
                        record.update(nodeId=None, attribution='project-unassigned')
            self._validate(p)
            self._record(db, previous, p, [{'op': 'project.restore', 'data': {'revision': body['revision']}}])
            return copy.deepcopy(p)

    def context(self, project_id, node_id=None):
        p = self.get_project(project_id)
        nodes = p['nodes']
        if node_id:
            node_id = p.get('nodeAliases', {}).get(node_id, node_id)
            self._find(p, 'nodes', node_id)
            selected = {node_id}
            while True:
                more = {n['id'] for n in nodes if n.get('parentId') in selected}
                if more <= selected:
                    break
                selected.update(more)
            nodes = [n for n in nodes if n['id'] in selected]
        else:
            selected = {n['id'] for n in nodes}
        decisions = [d for d in p['decisions'] if d['nodeId'] in selected]
        edges = [e for e in p['edges'] if e['source'] in selected or e['target'] in selected]
        referenced_runs = {run_id for record in decisions + edges for run_id in record.get('runIds', [])}
        runs = [r for r in p['runs'] if r.get('nodeId') in selected or r['id'] in referenced_runs]
        superseded = {a.get('supersedes') for a in p['assessments'] if a.get('supersedes')}
        run_ids = {r['id'] for r in runs}
        assessments = [a for a in p['assessments'] if a['runId'] in run_ids and a['id'] not in superseded]
        artifact_ids = {artifact_id for record in runs + decisions + assessments for artifact_id in record.get('artifactIds', [])}
        for node in nodes:
            origin = node.get('questionOrigin')
            if isinstance(origin, dict):
                artifact_ids.update(origin.get('artifactIds', []))
        artifacts = [a for a in p['artifacts'] if a['id'] in artifact_ids or a.get('nodeId') in selected or a.get('runId') in run_ids]
        boundary_ids = ({r['nodeId'] for r in runs} | {e[endpoint] for e in edges for endpoint in ('source', 'target')}) - selected
        for node in nodes:
            origin = node.get('questionOrigin')
            if isinstance(origin, dict):
                boundary_ids.update(p.get('nodeAliases', {}).get(key, key) for key in origin.get('nodeIds', []))
        boundary_ids -= selected
        def compact(records, fields):
            return [{key: record.get(key) for key in fields} for record in records]
        return {'projectId': p['id'], 'name': p['name'], 'revision': p['revision'], 'description': p['description'],
                'nodes': [{**{k: n.get(k) for k in ('id', 'title', 'kind', 'status', 'parentId', 'isContainer', 'collapsed', 'summary', 'conclusion', 'nextAction', 'importance', 'importanceReason', 'pauseReason', 'resumeWhen', 'questionOrigin')},
                           'hasNotes': bool(n.get('notes')),
                           **({'notes': n.get('notes', '')} if node_id else {})} for n in nodes],
                'boundaryNodes': compact([n for n in p['nodes'] if n['id'] in boundary_ids], ('id', 'title', 'kind', 'status', 'parentId', 'isContainer', 'collapsed', 'importance')),
                'edges': edges,
                'runs': [{k: r.get(k) for k in ('id', 'nodeId', 'title', 'status', 'metrics', 'artifactIds', 'origin')} for r in runs],
                'assessments': compact(assessments, ('id', 'runId', 'rubric', 'metrics', 'conclusion', 'limitations', 'artifactIds', 'supersedes', 'createdAt')),
                'decisions': compact(decisions, ('id', 'nodeId', 'title', 'conclusion', 'scope', 'nextAction', 'runIds', 'artifactIds', 'createdAt')),
                'artifacts': compact(artifacts, ('id', 'nodeId', 'runId', 'title', 'path', 'sha256', 'bytes', 'mime', 'createdAt', 'origin')),
                'observations': compact([o for o in p.get('observations', []) if o['nodeId'] in selected],
                                        ('id', 'nodeId', 'title', 'status', 'startedAt', 'finishedAt', 'durationMs', 'inputTokens', 'outputTokens', 'usageSource', 'usageRef', 'origin')),
                'usageRecords': [r for r in p.get('usageRecords', []) if not node_id or r.get('nodeId') in selected],
                'counts': {key: len(p.get(key, [])) for key in ('nodes', 'runs', 'artifacts', 'assessments', 'observations')},
                'warnings': [f'Run {r["id"]} is {r["status"]}.' for r in runs if r['status'] in ('running', 'failed', 'invalid')]}
