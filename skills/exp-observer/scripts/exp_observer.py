#!/usr/bin/env python3
"""Standalone ExpObserver client with durable, nonblocking experiment capture."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen
from uuid import uuid4

CLIENT_VERSION = '0.1.12'
MAX_WRITE_BODY = 2 * 1024 * 1024
MAX_BATCH_BODY = 8 * 1024 * 1024


class ClientError(Exception):
    def __init__(self, message, *, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        response.close()
        raise ClientError('Automatic recovery does not follow HTTP redirects.', code='redirect_not_allowed', status=code)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def emit(value, stream=sys.stdout):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), file=stream)


class Client:
    def __init__(self, url, timeout=30, transport_url=None, local_only=False, queue_root=None):
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.transport_url = (transport_url or self.url).rstrip('/')
        self.queue_root = Path(queue_root).resolve() if queue_root is not None else None
        if local_only and loopback_origin(self.transport_url) is None:
            raise ClientError('Automatic recovery requires a loopback HTTP origin.')
        self.opener = build_opener(ProxyHandler({}), NoRedirect()) if local_only else None

    def request(self, route, body=None, raw=False):
        if getattr(self, 'startup_unavailable', None):
            raise ClientError(self.startup_unavailable, code='unavailable')
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        # Reject before opening a connection: otherwise an early server 413 can
        # surface as a broken pipe while a large frozen receipt is uploading.
        batch_route = re.fullmatch(r'/api/projects/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/batch', urlsplit(route).path)
        limit = MAX_BATCH_BODY if batch_route else MAX_WRITE_BODY
        if data is not None and len(data) > limit:
            raise ClientError(f'Request is too large (limit {limit // (1024 * 1024)} MiB; encoded body {len(data)} bytes).',
                              code='body_too_large', status=413)
        request = Request(self.transport_url + route, data=data, headers={'Content-Type': 'application/json'})
        try:
            with (self.opener.open(request, timeout=self.timeout) if self.opener else urlopen(request, timeout=self.timeout)) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read())
                if not isinstance(detail, dict):
                    raise ValueError('Invalid error response')
                code = detail.get('code', str(exc.code))
                raise ClientError(f'{code}: {detail.get("error", exc.reason)}', code=code, status=exc.code) from exc
            except (ValueError, UnicodeError):
                raise ClientError(f'HTTP {exc.code}: {exc.reason}', code='http_error', status=exc.code) from exc
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f'Cannot reach ExpObserver at {self.url}: {exc.reason if isinstance(exc, URLError) else exc}', code='unavailable') from exc

    def project_route(self, project):
        return '/api/projects/' + quote(project, safe='')

    def project(self, project):
        return self.request(self.project_route(project))

    def apply(self, project, operations, revision=None, request_id=None):
        body = {'operations': operations, 'requestId': request_id or 'req-' + uuid4().hex}
        if revision is not None:
            body['expectedRevision'] = revision
        return self.request(self.project_route(project) + '/batch', body)


def parser():
    root = argparse.ArgumentParser(description='Maintain independent ExpObserver experiment records.')
    root.add_argument('--url', default=os.environ.get('EXP_OBSERVER_URL') or 'http://127.0.0.1:4317')
    root.add_argument('--no-autostart', action='store_true', help='Keep recording offline without attempting local platform startup')
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('projects', help='List experiments')
    init = commands.add_parser('init', help='Create an experiment')
    init.add_argument('--name', required=True)
    init.add_argument('--id')
    init.add_argument('--description', default='')
    init.add_argument('--source-root', action='append', default=[])
    record = commands.add_parser('record', help='Record work; generate IDs, references and a durable retry automatically')
    record.add_argument('--project', required=True)
    record.add_argument('--title', help='Required for a new record; omit on --node updates to preserve its title')
    record.add_argument('--summary')
    record.add_argument('--conclusion', help='The substantive finding displayed directly on the node')
    record.add_argument('--importance', choices=('normal', 'critical'), help='Legacy importance metadata (retained for compatibility)')
    record.add_argument('--importance-reason', help='Legacy importance explanation')
    record.add_argument('--kind', help='Natural research type, e.g. question, experiment, finding or decision; omitted updates preserve the type')
    notes = record.add_mutually_exclusive_group()
    notes.add_argument('--notes', help='Full analysis retained in the node notes')
    notes.add_argument('--notes-file', help='UTF-8 analysis loaded verbatim into node notes; - reads stdin without creating a report file')
    record.add_argument('--node', help='Update this node; omit to create a node')
    record.add_argument('--after', help='Related node ID or exact locally recorded title')
    record.add_argument('--relation', default='leads_to', help='Meaning of an explicit --after relationship')
    record.add_argument('--independent', action='store_true', help='Omit the automatic record-order connection')
    record.add_argument('--parent', help='Exact retained parent title/ID; promotes the parent to a container')
    record.add_argument('--container', action='store_true', help='Allow this node to contain nested research')
    record.add_argument('--status', default=None, help='Node status (default for new nodes: active)')
    record.add_argument('--metrics-file', help='UTF-8 JSON; nested objects are preserved and other root values use a result key')
    record.add_argument('--artifact', action='append', default=[])
    record.add_argument('--request-id', help='Stable identifier for retries of this record')
    event = commands.add_parser('event', help='Retain a question, finding, correction or change of direction; manage identities automatically')
    event.add_argument('--project', required=True)
    event.add_argument('--question', required=True, help='Natural question, or an exact retained question title/ID; the same wording reuses its identity')
    event.add_argument('--container', action='store_true', help='Keep this question and its findings in a research container')
    event.add_argument('--parent', help='Exact retained parent title/ID for this question')
    event.add_argument('--reason', help='Why pursue this question or retain this change')
    change = event.add_mutually_exclusive_group()
    change.add_argument('--finding', help='A substantive finding, retained as its own event')
    change.add_argument('--correction', help='A corrected judgment, retained separately from the earlier finding')
    change.add_argument('--direction', help='A change in research direction, retained as its own event')
    event.add_argument('--importance', choices=('normal', 'critical'), help='Legacy importance of the finding, or otherwise the question')
    event.add_argument('--importance-reason', help='Legacy importance explanation')
    event.add_argument('--after', help='Earlier node title or ID; a new question branches from it')
    event.add_argument('--relation', help='Meaning of --after (default: revises for correction, leads_to for direction, related_to for finding)')
    event.add_argument('--evidence', action='append', default=[], help='Execution/evidence node title or ID supporting this event; repeat as needed')
    event.add_argument('--summarizes', action='append', default=[], help='Earlier finding title/ID incorporated into this answer; repeat without inventing scientific support')
    analysis = event.add_mutually_exclusive_group()
    analysis.add_argument('--notes', help='Full native analysis for this event, or for the question when no event is supplied')
    analysis.add_argument('--notes-file', help='UTF-8 native analysis; - reads stdin')
    event.add_argument('--status', help='Actual question status; omitted status preserves an existing question')
    event.add_argument('--next-action', help='Next action for this question; omitted value preserves it')
    event.add_argument('--pause-reason', help='Why this question is paused; omitted value preserves it')
    event.add_argument('--resume-when', help='Condition for resuming this question; omitted value preserves it')
    event.add_argument('--metrics-file', help='Existing measurement JSON; retain its values without rerunning work')
    event.add_argument('--artifact', action='append', default=[])
    event.add_argument('--request-id', help='Stable retry identity; reuse for delivery retries of this same event')
    event.set_defaults(node=None)
    for origin_command in (record, event):
        origin_command.add_argument('--origin-type', help='Why this question was raised: goal, finding, literature, user, independent or a custom type')
        origin_command.add_argument('--origin-node', action='append', help='Exact source node ID/title; repeat for several sources')
        origin_command.add_argument('--origin-artifact', action='append', help='Retained source artifact ID; repeat as needed')
        origin_command.add_argument('--origin-url', help='Original http(s) source URL')
        origin_command.add_argument('--origin-reason', help='Brief reason for raising the question')
        origin_command.add_argument('--origin-retrospective', action='store_true', help='Declare that this origin was reconstructed later')
    sync = commands.add_parser('sync', help='Retry local pending records without executing experiments')
    sync.add_argument('--project', help='Only sync this project')
    status_command = commands.add_parser('status', help='Read local delivery receipts and research-review hints, without HTTP or polling')
    status_command.add_argument('--project', required=True)
    for command in ('focus', 'unfocus'):
        focus_cmd = commands.add_parser(command, help='Maintain this conversation’s nonexclusive experiment focus')
        focus_cmd.add_argument('--project', required=True)
        focus_cmd.add_argument('--owner', help='Conversation marker; defaults to CODEX_THREAD_ID or a retained local marker')
        if command == 'focus':
            focus_cmd.add_argument('--node', action='append', help='Exact node ID/title; repeat for simultaneous focus')
            focus_cmd.add_argument('--label', help='Readable conversation label')
            focus_cmd.add_argument('--ttl-seconds', type=int, default=None, help='Liveness window, 60–3600 seconds (default 900)')
    remote = commands.add_parser('task', help='Retain the lifecycle of an existing remote job; never execute or poll it')
    remote_actions = remote.add_subparsers(dest='task_action', required=True)
    for action in ('start', 'update'):
        remote_cmd = remote_actions.add_parser(action)
        remote_cmd.add_argument('--project', required=True)
        remote_cmd.add_argument('--request-id')
        remote_cmd.add_argument('--status', choices=('queued', 'running', 'paused', 'completed', 'failed', 'cancelled'),
                                default='running' if action == 'start' else None)
        remote_cmd.add_argument('--finished-at')
        remote_cmd.add_argument('--duration-ms', type=float)
        remote_cmd.add_argument('--metrics-file')
        if action == 'start':
            remote_cmd.add_argument('--node', required=True)
            remote_cmd.add_argument('--title', required=True)
            remote_cmd.add_argument('--task-ref', required=True)
            remote_cmd.add_argument('--remote-identity', required=True)
            remote_cmd.add_argument('--started-at', required=True, help='Actual original job start, including timezone')
        else:
            remote_cmd.add_argument('--run', required=True, help='Retained run ID returned by task start')
    observe = commands.add_parser('observe', help='Record a node step duration and explicit runtime token counters')
    observation_actions = observe.add_subparsers(dest='observation_action', required=True)
    for action in ('start', 'finish'):
        observation = observation_actions.add_parser(action)
        observation.add_argument('--project', required=True)
        observation.add_argument('--request-id', help='Stable retry identifier')
        if action == 'start':
            observation.add_argument('--node', required=True)
            observation.add_argument('--title', default='')
        else:
            observation.add_argument('--id', required=True, help='Observation ID returned by start')
            observation.add_argument('--input-tokens', type=int)
            observation.add_argument('--output-tokens', type=int)
            observation.add_argument('--usage-source', help='Runtime or provider counter source; required for supplied token counts')
            observation.add_argument('--usage-ref', help='Unique usage record reference within this source')
    for command in ('context', 'apply', 'artifact', 'export', 'check', 'execute', 'read'):
        options = {'help': 'Read a verified artifact byte range', 'description': 'Read a verified artifact byte range. Defaults: offset 0, limit 262144 bytes; maximum limit 1048576. Text goes to stdout; --output saves the original range bytes.'} if command == 'read' else {}
        cmd = commands.add_parser(command, **options)
        cmd.add_argument('--project', required=True)
        if command in ('context', 'artifact', 'execute'):
            cmd.add_argument('--node', help='Existing node; execute creates a node when omitted')
        if command == 'apply':
            cmd.add_argument('--file')
            cmd.add_argument('--expected-revision', type=int)
            cmd.add_argument('--request-id')
        if command == 'artifact':
            cmd.add_argument('--path', required=True, nargs='+')
            cmd.add_argument('--title')
            cmd.add_argument('--run')
        if command == 'export':
            cmd.add_argument('--output')
        if command == 'read':
            cmd.add_argument('--artifact', required=True)
            cmd.add_argument('--offset', type=int, default=0, help='Starting byte offset (default: 0)')
            cmd.add_argument('--limit', type=int, default=262144, help='Maximum bytes to read, up to 1048576 (default: 262144)')
            cmd.add_argument('--output', help='Save original range bytes to this file instead of printing text')
        if command == 'execute':
            cmd.add_argument('--title', required=True)
            cmd.add_argument('--parent', help='Exact retained parent title/ID for the execution node')
            cmd.add_argument('--question', help='Exact research question title/ID; retain a run of that question without creating a finding')
            cmd.add_argument('--after', help='Related node ID or exact locally recorded title')
            cmd.add_argument('--relation', default='leads_to')
            cmd.add_argument('--independent', action='store_true', help='Omit the automatic record-order connection')
            cmd.add_argument('--request-id', help='Stable identifier; retries never rerun this command')
            cmd.add_argument('--artifact', action='append', default=[], help='Capture a result file after execution; repeat for multiple files')
            cmd.add_argument('argv', nargs=argparse.REMAINDER)
    return root


def capture_root(project_id):
    directory = project_id
    stem = directory.split('.')[0].upper()
    if directory != directory.lower() or directory.endswith('.') or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} or re.fullmatch(r'(COM|LPT)[1-9]', stem):
        directory = '~' + hashlib.sha256(directory.encode('utf-8')).hexdigest()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', directory):
        directory = '~' + hashlib.sha256(project_id.encode('utf-8')).hexdigest()
    return (Path.cwd() / '.exp-observer-runs' / directory).resolve()


def sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def ensure_directory(path):
    missing, ancestor = [], path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        sync_directory(created.parent)


def save_task(path, task):
    """Atomic replacement keeps a timeout or interrupted sync safely retryable."""
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(task, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def task_lock(path):
    """An OS lock is released on process death, including on Windows."""
    ensure_directory(path.parent)
    with path.with_suffix('.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if not lock.tell():
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ClientError('This local record is already being processed.', code='busy') from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ClientError('This local record is already being processed.', code='busy') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def state_directory():
    """Only the small directory registry is shared between workspaces."""
    override = os.environ.get('EXP_OBSERVER_STATE_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Local')
        return base / 'ExpObserver'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ExpObserver'
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'exp-observer'


def loopback_origin(url):
    """Automatic recovery accepts only an explicit local HTTP origin."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else 80
        hostname = '127.0.0.1' if parsed.hostname == 'localhost' else parsed.hostname
        return (hostname, port) if 1 <= port <= 65535 else None
    except ValueError:
        return None


def register_outbox(outbox, url):
    if loopback_origin(url) is None:
        return 'Automatic recovery requires a loopback HTTP URL; this outbox remains available to manual sync.'
    outbox = str(Path(outbox).resolve())
    key = hashlib.sha256(json.dumps([url, outbox], ensure_ascii=False).encode('utf-8')).hexdigest()
    registration = state_directory() / 'outboxes' / (key + '.json')
    try:
        with task_lock(registration):
            if not registration.exists():
                save_task(registration, {'version': 1, 'url': url, 'outbox': outbox, 'registeredAt': stamp()})
    except (ClientError, OSError, ValueError) as exc:
        return f'Automatic recovery registration is unavailable; the durable outbox is retained: {exc}'
    return None


def persist_task(path, task):
    # Research clients write only inside their working directory. The application
    # discovers queues in enrolled workspaces, including future experiment folders.
    save_task(path, task)
    if task.get('kind') not in ('project', 'focus'):
        heartbeat_association(task['url'], task['projectId'], Path(path).parent)


def project_plan_path(outbox, url, project_id):
    key = hashlib.sha256(json.dumps([url, project_id], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
    return Path(outbox) / ('project-' + key + '.json')


def remember_project(outbox, url, project):
    """Retain only readable catalog metadata, never a second research report."""
    project_id = project.get('id') or project.get('projectId')
    name = project.get('name')
    if not isinstance(name, str) or not name.strip() or name in (project_id, '未命名研究'):
        return
    path = Path(outbox).parent / 'context' / ('project-' + hashlib.sha256(
        json.dumps([url, project_id], ensure_ascii=False).encode('utf-8')).hexdigest() + '.json')
    if path.parent.is_symlink():
        return
    ensure_directory(path.parent)
    save_task(path, {'version': 1, 'url': url, 'cachedAt': stamp(),
                     'project': {'id': project_id, 'name': name, 'description': project.get('description', '')}})


def retained_project_metadata(outbox, url, project_id, queue_root=None):
    candidates = []
    for directory in ancestor_outboxes(outbox, queue_root):
        context_dir = directory.parent / 'context'
        for path in context_dir.glob('*.json'):
            try:
                if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                    continue
                if queue_root is not None and not path.resolve().is_relative_to(queue_root):
                    continue
                cached = json.loads(path.read_text(encoding='utf-8'))
                at = local_timestamp(cached.get('cachedAt'))
                context = cached.get('context')
                if isinstance(context, dict):
                    expected = hashlib.sha256(json.dumps([url, project_id, cached.get('nodeId')], ensure_ascii=False).encode('utf-8')).hexdigest() + '.json'
                    if path.name != expected or context.get('projectId') != project_id:
                        continue
                    metadata = {'id': project_id, 'name': context.get('name'), 'description': context.get('description', '')}
                else:
                    metadata = cached.get('project', {})
                    if cached.get('url') != url or metadata.get('id') != project_id:
                        continue
                name = metadata.get('name')
                if at is not None and isinstance(name, str) and name.strip() and name not in (project_id, '未命名研究'):
                    candidates.append((at, str(path), metadata))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return max(candidates, key=lambda candidate: candidate[:2]) if candidates else None


def prepare_project(outbox, url, metadata, implicit=False):
    """First writer freezes a creation plan; later captures never edit it."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', metadata['id']):
        raise ClientError('Project IDs must use 1–128 letters, numbers, dots, underscores or hyphens.')
    path = project_plan_path(outbox, url, metadata['id'])
    with task_lock(path):
        if path.exists():
            plan = json.loads(path.read_text(encoding='utf-8'))
            if plan.get('implicit') and not implicit:
                plan.update(project=metadata, implicit=False, preparedAt=stamp(), state='ready', repairPlaceholder=True)
                persist_task(path, plan)
            return path, plan
        plan = {'version': 1, 'clientVersion': CLIENT_VERSION, 'kind': 'project', 'url': url, 'projectId': metadata['id'],
                'project': metadata, 'implicit': implicit, 'preparedAt': stamp(), 'state': 'ready',
                'recordingWarnings': []}
        persist_task(path, plan)
        return path, plan


def ensure_project(client, path, plan):
    """Recover metadata after not_found; explicit init may repair only a placeholder."""
    try:
        project = client.project(plan['projectId'])
    except ClientError as exc:
        if not str(exc).startswith('not_found:'):
            raise
        try:
            metadata = dict(plan['project'])
            retained = retained_project_metadata(path.parent, client.url, plan['projectId'], client.queue_root)
            if retained and (plan.get('implicit') or retained[0] > (local_timestamp(plan.get('preparedAt')) or 0)):
                metadata.update(retained[2])
            project = client.request('/api/projects', metadata)
        except ClientError as creation_error:
            if not str(creation_error).startswith('conflict:'):
                raise
            # A concurrent creator may have won after our GET.
            project = client.project(plan['projectId'])
    if plan.get('repairPlaceholder') and project.get('name') in (plan['projectId'], '未命名研究'):
        for attempt in range(3):
            try:
                project = client.apply(plan['projectId'], [{'op': 'project.update', 'data': {
                    'name': plan['project']['name'], 'description': plan['project'].get('description', '')}}],
                    project['revision'], 'restore-name-' + uuid4().hex)
                break
            except ClientError as exc:
                if exc.code != 'revision_conflict' or attempt == 2:
                    raise
                project = client.project(plan['projectId'])
                if project.get('name') not in (plan['projectId'], '未命名研究'):
                    break
    try:
        remember_project(path.parent, client.url, project)
    except OSError:
        pass
    if plan['state'] != 'synced':
        plan['state'] = 'synced'
        save_task(path, plan)
    return project


def sync_project(client, path, plan):
    warnings = list(plan['recordingWarnings'])
    project = None
    try:
        delivery_attempt(path, plan)
        project = ensure_project(client, path, plan)
        delivery_succeeded(path, plan)
    except (ClientError, OSError, ValueError) as exc:
        delivery_failed(path, plan, exc, warnings)
        warnings.append(str(exc))
    source = project if project is not None else plan['project']
    result = {key: source[key] for key in ('id', 'name', 'description', 'revision') if key in source}
    result.update({'projectId': plan['projectId'], 'pending': project is None, 'preparedAt': plan['preparedAt'],
                   'availability': 'available' if project is not None else 'unavailable'})
    if plan.get('delivery'):
        result['delivery'] = plan['delivery']
    if warnings:
        result['recordingWarnings'] = warnings
    return result


def pending_project_receipt(project_id, plan=None):
    result = {'id': project_id, 'projectId': project_id, 'pending': plan is not None,
              'availability': 'pending' if plan is not None else 'unavailable'}
    warnings = []
    if plan is not None:
        result.update({key: plan['project'][key] for key in ('name', 'description') if key in plan['project']})
        if isinstance(plan.get('preparedAt'), str):
            result['preparedAt'] = plan['preparedAt']
        warnings.extend(plan.get('recordingWarnings', []))
    warnings.append('Project initialization is already being processed.' if plan is not None else
                    'Project initialization is already being processed, but a durable project plan could not be confirmed.')
    result['recordingWarnings'] = warnings
    return result


def init(client, args):
    if not args.name.strip():
        raise ClientError('Experiment name is required.')
    project_id = args.id or 'study-' + hashlib.sha256(json.dumps(
        [client.url, str(Path.cwd().resolve()), args.name.strip()], ensure_ascii=False).encode('utf-8')).hexdigest()[:24]
    metadata = {'id': project_id, 'name': args.name.strip(), 'description': args.description,
                'sourceRoots': [str(Path(root).expanduser().resolve()) for root in args.source_root]}
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    path, plan = project_plan_path(outbox, client.url, project_id), None
    try:
        path, plan = prepare_project(outbox, client.url, metadata)
        with task_lock(path):
            plan = json.loads(path.read_text(encoding='utf-8'))
            result = sync_project(client, path, plan)
    except ClientError as exc:
        if exc.code != 'busy':
            raise
        if plan is None:
            # A readable atomic snapshot can confirm frozen metadata. Windows may
            # refuse this read during replacement; then report only the known ID.
            try:
                candidate = read_queue_task(path)
                if (candidate.get('kind') == 'project' and candidate['url'] == client.url
                        and candidate['projectId'] == project_id and isinstance(candidate.get('project'), dict)
                        and candidate['project'].get('id') == project_id
                        and isinstance(candidate['project'].get('name'), str) and isinstance(candidate.get('preparedAt'), str)):
                    plan = candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass
        # When preparation already returned a plan, use that snapshot directly:
        # no further reads, writes or HTTP requests while recovery owns its lock.
        result = pending_project_receipt(project_id, plan)
    if plan is not None and plan['project'] != metadata:
        result.setdefault('recordingWarnings', []).append('Creation metadata was already prepared; the original plan is retained.')
    emit(result)
    return 0


def read_queue_task(path):
    task = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(task, dict) or any(not isinstance(task.get(key), str) for key in ('url', 'projectId', 'state')):
        raise ValueError('Queued records require an object with url, projectId and state text fields.')
    if task.get('kind') == 'focus':
        body = task.get('focus')
        if (not isinstance(body, dict) or body.get('action') not in ('start', 'heartbeat', 'end')
                or any(not isinstance(body.get(key), str) for key in ('ownerId', 'leaseId', 'observedAt'))
                or type(body.get('sequence')) is not int or body['sequence'] < 0
                or ('nodeIds' in body and (not isinstance(body['nodeIds'], list)
                    or any(not isinstance(key, str) for key in body['nodeIds'])))):
            raise ValueError('Queued focus requires a frozen action, owner, lease, observation and sequence.')
    return task


def local_context(outbox, client, project_id, node_id=None):
    project, records = None, []
    node_updates = []
    for path in Path(outbox).glob('*.json'):
        try:
            task = read_queue_task(path)
            if task['url'] != client.url or task['projectId'] != project_id:
                continue
            if task.get('kind') == 'project':
                project = {'metadata': task['project'], 'preparedAt': task['preparedAt'], 'state': task['state']}
            else:
                record = {key: task[key] for key in
                          ('requestId', 'nodeId', 'questionId', 'eventType', 'runId', 'state', 'capturedAt', 'startedAt', 'finishedAt') if key in task}
                record['localTaskPath'] = str(path.resolve())
                record['operations'] = []
                for index, operation in enumerate(task.get('operations', [])):
                    data = operation.get('data', {})
                    detail = {'op': operation['op'], **{key: data[key] for key in
                              ('id', 'title', 'kind', 'status', 'nodeId', 'source', 'target', 'parentId', 'isContainer', 'collapsed', 'nextAction', 'pauseReason', 'resumeWhen', 'questionOrigin') if key in data}}
                    for field, limit in (('summary', 512), ('conclusion', 512)):
                        if isinstance(data.get(field), str):
                            detail[field] = data[field][:limit]
                            if len(data[field]) > limit:
                                detail[field + 'Truncated'] = True
                    if isinstance(data.get('notes'), str):
                        detail.update({'notes': data['notes'], 'hasNotes': bool(data['notes'])})
                    if operation['op'] in ('node.add', 'node.update', 'node.ensure') and isinstance(data.get('id'), str):
                        if operation['op'] == 'node.ensure' and data.get('referenceOnly'):
                            continue
                        fields = ('id', 'title', 'kind', 'status', 'parentId', 'isContainer', 'collapsed', 'summary', 'conclusion', 'notes', 'importance', 'importanceReason', 'nextAction', 'pauseReason', 'resumeWhen', 'questionOrigin')
                        node_updates.append(((task.get('capturedAt') or task.get('startedAt') or '', path.name, index),
                                             operation['op'], {key: data[key] for key in fields if key in data}))
                    record['operations'].append(detail)
                record['artifactCount'] = len(task.get('artifacts', []))
                records.append(record)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    records.sort(key=lambda record: record.get('capturedAt') or record.get('startedAt') or '')
    # Fold all local updates before applying the receipt window: an old notes
    # operation can remain current after many later summary-only revisions.
    nodes = {}
    for _, operation, update in sorted(node_updates, key=lambda entry: entry[0]):
        if operation == 'node.ensure':
            nodes.setdefault(update['id'], update)
        else:
            nodes.setdefault(update['id'], {}).update(update)
    scoped = {node_id} if node_id else set()
    if node_id:
        changed = True
        while changed:
            children = {key for key, node in nodes.items() if node.get('parentId') in scoped}
            changed = bool(children - scoped)
            scoped.update(children)
    for record in records:
        for detail in record['operations']:
            if detail.get('id') not in scoped:
                detail.pop('notes', None)
    local_nodes = []
    for key, node in nodes.items():
        if node_id and key not in scoped:
            continue
        detail = {field: node[field] for field in ('id', 'title', 'kind', 'status', 'parentId', 'isContainer', 'collapsed', 'nextAction', 'pauseReason', 'resumeWhen', 'questionOrigin') if field in node}
        for field in ('summary', 'conclusion'):
            if isinstance(node.get(field), str):
                detail[field] = node[field][:512]
                if len(node[field]) > 512:
                    detail[field + 'Truncated'] = True
        detail['hasNotes'] = isinstance(node.get('notes'), str) and bool(node['notes'])
        if node_id and isinstance(node.get('notes'), str):
            detail['notes'] = node['notes']
        local_nodes.append(detail)
    pending = [record for record in records if record['state'] != 'synced']
    return project, records, pending, local_nodes


def context(client, args):
    workspace = Path.cwd() / '.exp-observer-runs'
    key = hashlib.sha256(json.dumps([client.url, args.project, args.node], ensure_ascii=False).encode('utf-8')).hexdigest()
    cache_path = workspace / 'context' / (key + '.json')
    project, records, pending, local_nodes = local_context(workspace / 'outbox', client, args.project, args.node)
    try:
        route = client.project_route(args.project) + '/context'
        if args.node:
            route += '?' + urlencode({'node': args.node})
        result = client.request(route)
    except (ClientError, OSError, ValueError) as exc:
        cached = None
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        has_pending = bool(pending or (project and project['state'] != 'synced'))
        rejected = isinstance(exc, ClientError) and exc.status is not None
        pending_project = rejected and exc.code == 'not_found' and 'Experiment not found.' in str(exc) and has_pending
        result = {'projectId': args.project, 'availability': 'pending' if pending_project else ('error' if rejected else 'unavailable'),
                  'pending': has_pending,
                  'cachedRemote': cached, 'localProject': project, 'localNodes': local_nodes, 'localRecords': records[-20:],
                  'localPending': pending[-20:], 'localRecordCount': len(records), 'localPendingCount': len(pending),
                  'recordingWarnings': [str(exc)]}
        if rejected:
            result['remoteError'] = {'code': exc.code, 'status': exc.status, 'message': str(exc)}
            if not pending_project:
                result['error'] = str(exc)
        emit(result)
        return 1 if rejected and not pending_project else 0
    fetched_at = stamp()
    try:
        ensure_directory(cache_path.parent)
        save_task(cache_path, {'cachedAt': fetched_at, 'nodeId': args.node, 'context': result})
        remember_project(workspace / 'outbox', client.url, result)
    except OSError as exc:
        result.setdefault('recordingWarnings', []).append(f'Context cache unavailable: {exc}')
    result.update({'availability': 'available', 'pending': bool(pending), 'fetchedAt': fetched_at})
    if pending:
        result['localPending'] = pending[-20:]
        result['localPendingCount'] = len(pending)
        pending_ids = {record.get('nodeId') for record in pending}
        pending_ids.update(record['questionId'] for record in pending if record.get('questionId'))
        result['localPendingNodes'] = [node for node in local_nodes if node['id'] in pending_ids]
    emit(result)
    return 0


def task_identity(client, args, intent):
    request_id = getattr(args, 'request_id', None) or 'capture-' + uuid4().hex
    key = hashlib.sha256(json.dumps([client.url, args.project, request_id], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
    path = Path.cwd() / '.exp-observer-runs' / 'outbox' / (key + '.json')
    task = {'version': 1, 'clientVersion': CLIENT_VERSION, 'taskId': key, 'requestId': request_id, 'url': client.url,
            'projectId': args.project, 'intent': intent, 'state': 'preparing',
            'nodeId': args.node or 'node-' + key, 'runId': 'run-' + key,
            'captureRoot': str(capture_root(args.project)), 'artifacts': [], 'recordingWarnings': []}
    thread_id = os.environ.get('CODEX_THREAD_ID', '')
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', thread_id):
        task['hostUsage'] = {'host': 'codex', 'threadId': thread_id}
    return path, task


def load_existing(path, task, *, frozen_notes=False):
    if not path.exists():
        return None
    existing = json.loads(path.read_text(encoding='utf-8'))
    defaults = {'conclusion': None, 'independent': False, 'relation': 'leads_to', 'after': None,
                'kind': None, 'notes': None, 'notesFile': None,
                'next_action': None, 'pause_reason': None, 'resume_when': None}
    expected = defaults | task['intent']
    if frozen_notes:
        retained_notes = existing.get('intent', {}).get('notes')
        if not isinstance(retained_notes, str):
            raise ClientError('The durable capture has no frozen analysis for this retry.', code='queue_identity_conflict')
        expected['notes'] = retained_notes
    if (defaults | existing.get('intent', {})) != expected:
        raise ClientError('request-id was already used for different work; use a new request-id.')
    return existing


def ancestor_outboxes(outbox, queue_root=None):
    """Only the current folder and its ancestors; never inspect sibling research."""
    directory = Path(outbox).parent.parent.resolve()
    boundary = Path(queue_root).resolve() if queue_root is not None else None
    if boundary is not None and directory != boundary and boundary not in directory.parents:
        return
    for ancestor in (directory, *directory.parents):
        yield ancestor / '.exp-observer-runs' / 'outbox'
        if ancestor == boundary:
            break


def local_timestamp(value):
    """Compare dated local facts without consulting file mtimes or the network."""
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def local_node_view(client, outbox, project_id, exclude=None, include_cache=False):
    """Fold patches, not replacement summaries; caches are dated local evidence."""
    updates, caches, warnings = [], [], []
    for directory in ancestor_outboxes(outbox, client.queue_root):
        try:
            paths = sorted(directory.glob('*.json'))
        except OSError as exc:
            warnings.append(f'{directory}: {exc}')
            continue
        for path in paths:
            if exclude is not None and path.resolve() == Path(exclude).resolve():
                continue
            try:
                task = read_queue_task(path)
                if (task['url'] != client.url or task['projectId'] != project_id
                        or task['state'] not in ('ready', 'synced') or task.get('kind') == 'project'):
                    continue
                at = task.get('capturedAt') or task.get('finishedAt') or task.get('startedAt') or ''
                for index, operation in enumerate(task.get('operations', [])):
                    if operation.get('op') not in ('node.add', 'node.update', 'node.ensure'):
                        continue
                    data = operation['data']
                    if not isinstance(data.get('id'), str):
                        continue
                    # Pending intents overlay snapshots until acknowledged; within
                    # each layer, preserve captured order and operation order.
                    order = (include_cache and task['state'] != 'synced', local_timestamp(at) or 0, str(path), index)
                    updates.append((order, operation['op'], dict(data), at))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                warnings.append(f'{path}: {exc}')
        if not include_cache:
            continue
        context_directory = directory.parent / 'context'
        try:
            cache_paths = sorted(context_directory.glob('*.json'))
        except OSError as exc:
            warnings.append(f'{context_directory}: {exc}')
            continue
        for path in cache_paths:
            full_key = hashlib.sha256(json.dumps([client.url, project_id, None], ensure_ascii=False).encode('utf-8')).hexdigest()
            matching = path.name == full_key + '.json'
            try:
                cached = json.loads(path.read_text(encoding='utf-8'))
                scope = cached.get('nodeId')
                key = hashlib.sha256(json.dumps([client.url, project_id, scope], ensure_ascii=False).encode('utf-8')).hexdigest()
                matching = path.name == key + '.json'
                if not matching:
                    continue
                at = cached.get('cachedAt')
                when = local_timestamp(at)
                context = cached['context']
                if when is None or context.get('projectId') != project_id or not isinstance(context.get('nodes'), list):
                    raise ValueError('Context cache has no valid date or matching project snapshot.')
                caches.append({'cachedAt': at, 'nodeId': scope, 'localCachePath': str(path.resolve())})
                if scope is None:
                    # A full dated snapshot also records removals. Pending local
                    # intents are replayed afterward, not lost with old receipts.
                    updates.append(((False, when, str(path), -1), 'nodes.snapshot', {}, at))
                for index, node in enumerate(context['nodes']):
                    if isinstance(node.get('id'), str) and isinstance(node.get('title'), str):
                        updates.append(((False, when, str(path), index), 'node.snapshot', dict(node), at))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                # Only matching cache names can describe this project/URL.
                if matching:
                    warnings.append(f'{path}: {exc}')
    nodes = {}
    for _, operation, update, at in sorted(updates, key=lambda entry: entry[0]):
        if operation == 'nodes.snapshot':
            nodes.clear()
            continue
        if operation == 'node.ensure' and update['id'] in nodes:
            continue
        if operation == 'node.ensure' and update.get('referenceOnly'):
            continue
        nodes.setdefault(update['id'], {}).update(update)
        nodes[update['id']]['at'] = at
    return sorted(nodes.values(), key=lambda node: (local_timestamp(node.get('at')) or 0, node['id'])), caches, warnings


def local_nodes(client, outbox, project_id, exclude=None):
    nodes, _, _ = local_node_view(client, outbox, project_id, exclude=exclude)
    return nodes


def capture_project_plan(outbox, url, project_id, queue_root=None):
    plans = []
    for directory in ancestor_outboxes(outbox, queue_root):
        path = project_plan_path(directory, url, project_id)
        try:
            if queue_root is not None and not path.resolve().is_relative_to(queue_root):
                continue
            plan = read_queue_task(path)
            if (plan.get('kind') == 'project' and plan['url'] == url and plan['projectId'] == project_id
                    and isinstance(plan.get('project'), dict) and plan['project'].get('id') == project_id):
                plans.append((bool(plan.get('implicit')), plan.get('preparedAt', ''), str(path), path, plan))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if plans:
        _, _, _, path, plan = min(plans, key=lambda entry: entry[:3])
        return path, plan
    retained = retained_project_metadata(outbox, url, project_id, queue_root)
    metadata = {'id': project_id, 'name': '未命名研究', 'description': '', 'sourceRoots': []}
    if retained:
        metadata.update(retained[2])
    path, plan = prepare_project(outbox, url, metadata, implicit=True)
    if not retained:
        warning = 'Readable project metadata is unavailable; use init --id ' + project_id + ' --name NAME once to restore its name.'
        if warning not in plan['recordingWarnings']:
            with task_lock(path):
                plan = read_queue_task(path)
                plan['recordingWarnings'].append(warning)
                persist_task(path, plan)
    return path, plan


def capture_relationship(client, args, path, task):
    """Record order is observed chronology, never an invented scientific cause."""
    if not args.after and (args.node or args.independent):
        return
    nodes = semantic_nodes(client, path.parent, task['projectId'], exclude=path)
    source = args.after
    run_ids = []
    if source:
        try:
            referenced = exact_reference(nodes, source)
            if referenced is None:
                referenced = execution_reference(client, path.parent, task['projectId'], source, exclude=path)
        except ClientError as exc:
            task['recordingWarnings'].append(str(exc) + '; the finding is retained without that relationship.')
            return
        if referenced:
            source = referenced['id']
            if args.relation == 'supports':
                run_ids = referenced.get('runIds', [])
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', source):
            task['recordingWarnings'].append('Relationship title was not found locally; the finding is retained without that relationship.')
            return
        relation, label = args.relation, ''
    else:
        candidates = [node for node in nodes if node['id'] != task['nodeId']]
        if not candidates:
            return
        source = candidates[-1]['id']
        relation, label = 'recorded_after', '记录顺序'
    if source == task['nodeId']:
        return
    task['operations'].append({'op': 'edge.add', 'data': {
        'id': 'edge-' + task['taskId'], 'source': source, 'target': task['nodeId'],
        'relation': relation, 'label': label, 'basis': 'observed',
        **({'runIds': run_ids} if run_ids else {})}})


def file_digest(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def stage_artifact(task, source, title, target):
    source = Path(source)
    try:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise OSError('Evidence is missing or is not a regular file')
        if source != target:
            shutil.copyfile(source, target)
        # Flush snapshots before persisting the task that refers to them.
        with target.open('r+b') as stream:
            os.fsync(stream.fileno())
        sync_directory(target.parent)
        sha256, size = file_digest(target)
        index = len(task['artifacts'])
        task['artifacts'].append({'id': f'artifact-{task["taskId"]}-{index}', 'path': str(target),
                                  'title': title, 'nodeId': task['nodeId'], 'runId': task['runId'],
                                  'sha256': sha256, 'bytes': size, 'capturedAt': stamp()})
    except (OSError, ValueError, RuntimeError) as exc:
        task['recordingWarnings'].append(f'Evidence {source}: {exc}')


def merge_source_root(client, task):
    """CAS merge avoids losing roots added concurrently by another agent."""
    for attempt in range(4):
        project = client.project(task['projectId'])
        roots = project.get('sourceRoots', [])
        if task['captureRoot'] in roots:
            return
        operations = [{'op': 'project.update', 'data': {'sourceRoots': roots + [task['captureRoot']]}}]
        fingerprint = hashlib.sha256(json.dumps(operations, sort_keys=True).encode()).hexdigest()[:24]
        try:
            client.apply(task['projectId'], operations, project['revision'], f'roots-{fingerprint}-{project["revision"]}')
            return
        except ClientError as exc:
            if 'revision_conflict:' not in str(exc) or attempt == 3:
                raise


def delivery_attempt(path, task):
    previous = task.get('delivery') if isinstance(task.get('delivery'), dict) else {}
    attempts = previous.get('attempts', 0)
    task['delivery'] = {**previous, 'attempts': (attempts if isinstance(attempts, int) and attempts >= 0 else 0) + 1,
                        'lastAttemptAt': stamp()}
    save_task(path, task)


def delivery_succeeded(path, task):
    task['delivery'] = {**task.get('delivery', {}), 'lastError': None, 'nextAttemptAt': None, 'retryable': True, 'syncedAt': stamp()}
    save_task(path, task)


def delivery_retryable(code):
    if code in ('invalid_reference', 'unresolved_reference', 'not_found'):
        return True
    return not (code.startswith('invalid_') or code in (
        'external_task_conflict', 'body_too_large', 'queue_identity_conflict',
        'path_not_allowed', 'registration_required', 'conflict', 'self_edge',
        'duplicate_usage_ref', 'duplicate_id'))


def delivery_failed(path, task, exc, warnings):
    # Delivery metadata is mutable; capture identity, operations and evidence are not.
    delivery = task.setdefault('delivery', {})
    delivery['lastError'] = {'code': getattr(exc, 'code', None) or ('io_error' if isinstance(exc, OSError) else 'delivery_error'),
                             'message': str(exc)}
    delivery['lastFailureAt'] = stamp()
    delivery['retryable'] = delivery_retryable(delivery['lastError']['code'])
    # Permit one immediate transport recovery after recording offline; every
    # repeated failure backs off, including missing nodes and rejected updates.
    attempts = delivery.get('attempts', 1)
    first_transport = attempts == 1 and delivery['lastError']['code'] in ('unavailable', 'delivery_error', 'io_error')
    delay = 0 if first_transport else min(60, 2 ** min(attempts, 6))
    delivery['nextAttemptAt'] = ((datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                                  if delivery['retryable'] else None)
    try:
        save_task(path, task)
    except OSError as save_error:
        warnings.append('Delivery diagnostics could not be saved: ' + str(save_error))


def sync_task(client, path, task):
    # A background worker may have acknowledged the frozen task since this
    # caller read it. The atomic on-disk receipt is authoritative, even offline.
    if task.get('kind') == 'focus':
        return sync_focus(client, path, task)
    current = read_queue_task(path)
    identity = ('url', 'projectId', 'taskId', 'requestId', 'nodeId', 'runId', 'intent')
    if current['url'] != client.url or any(current.get(key) != task.get(key) for key in identity):
        raise ClientError('The durable queue identity differs from this capture; refusing to submit or overwrite it.', code='queue_identity_conflict')
    task = current
    if task['state'] == 'synced':
        return task_result(task)
    if task['state'] != 'ready':
        return task_result(task, ['Capture was interrupted before its outcome was saved; sync never reruns commands.'])
    warnings = []
    try:
        delivery_attempt(path, task)
        if client.queue_root is not None:
            local_plan = project_plan_path(path.parent, client.url, task['projectId'])
            for staged in [task['captureRoot'], local_plan, local_plan.with_suffix('.lock'),
                           *[artifact['path'] for artifact in task['artifacts']]]:
                resolved = Path(staged).resolve()
                if resolved != client.queue_root and client.queue_root not in resolved.parents:
                    raise ClientError('Queued evidence is outside the connected research directory.', code='path_not_allowed')
        plan_path, plan = capture_project_plan(path.parent, client.url, task['projectId'], client.queue_root)
        if client.queue_root is not None:
            for candidate in (plan_path, plan_path.with_suffix('.lock')):
                resolved = candidate.resolve()
                if resolved != client.queue_root and client.queue_root not in resolved.parents:
                    raise ClientError('Project preparation is outside the connected research directory.', code='path_not_allowed')
        with task_lock(plan_path):
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            catalog = ensure_project(client, plan_path, plan)
            if catalog.get('name') in (task['projectId'], '未命名研究'):
                warnings.append('Project name metadata is unavailable; restore it once with init --id ' + task['projectId'] + ' --name NAME.')
        # All operations (including timestamps) are frozen before the first send.
        client.apply(task['projectId'], task['operations'], request_id='capture-' + task['taskId'])
        if task['artifacts']:
            merge_source_root(client, task)
            project = client.project(task['projectId'])
            registered = {a['id']: a for a in project['artifacts']}
            for artifact in task['artifacts']:
                expected = dict(artifact)
                expected['nodeId'] = project.get('nodeAliases', {}).get(artifact['nodeId'], artifact['nodeId'])
                existing = registered.get(artifact['id'])
                if existing:
                    if any(existing.get(key) != expected[key] for key in ('sha256', 'bytes', 'nodeId', 'runId')):
                        raise ClientError('Registered evidence differs from this capture: ' + artifact['id'])
                    continue
                snapshot = Path(artifact['path'])
                if file_digest(snapshot) != (artifact['sha256'], artifact['bytes']):
                    raise ClientError('Staged evidence changed; original files will not be reread: ' + str(snapshot))
                retained = client.request(client.project_route(task['projectId']) + '/artifacts', artifact)
                if any(retained.get(key) != expected[key] for key in ('id', 'sha256', 'bytes', 'nodeId', 'runId')):
                    raise ClientError('Retained evidence differs from this capture: ' + artifact['id'])
        task['state'] = 'synced'
        delivery_succeeded(path, task)
    except (ClientError, OSError, ValueError) as exc:
        task['state'] = 'ready'
        delivery_failed(path, task, exc, warnings)
        warnings.append(str(exc))
    deliver_focus_updates(client, path.parent, task['projectId'])
    return task_result(task, warnings)


def task_result(task, warnings=()):
    if task.get('kind') == 'focus':
        return {'projectId': task['projectId'], 'kind': 'focus', 'requestId': task['requestId'],
                **task['focus'], 'pending': task['state'] != 'synced',
                'focusState': task.get('focusState'), 'superseded': task.get('superseded', False),
                'delivery': task.get('delivery', {}), 'recordingWarnings': list(warnings)}
    result = {'projectId': task['projectId'], 'nodeId': task['nodeId'], 'runId': task['runId'],
              'requestId': task['requestId'], 'status': task.get('status', 'pending'),
              'pending': task['state'] != 'synced', 'artifactIds': [a['id'] for a in task['artifacts']] if task['state'] == 'synced' else []}
    for field in ('exitCode', 'wallTimeMs', 'startedAt', 'finishedAt', 'capturedAt'):
        if field in task:
            result[field] = task[field]
    for field in ('questionId', 'eventType'):
        if field in task:
            result[field] = task[field]
    if task.get('delivery'):
        result['delivery'] = task['delivery']
    if task['intent']['command'] == 'execute' and task.get('captureAvailable', True):
        directory = Path(task['captureRoot']) / task['taskId']
        result['stdoutPath'] = str(directory / 'stdout.txt')
        result['stderrPath'] = str(directory / 'stderr.txt')
    combined = task['recordingWarnings'] + list(warnings)
    if combined:
        result['recordingWarnings'] = combined
    return result


def capture_inputs(args):
    notes = args.notes
    notes_error = None
    if args.notes_file is not None:
        if args.notes_file == '-':
            notes = sys.stdin.read()
        else:
            try:
                with Path(args.notes_file).open('r', encoding='utf-8-sig', newline='') as stream:
                    notes = stream.read()
            except OSError as exc:
                notes_error = exc
    metrics, metrics_warning = {}, None
    if args.metrics_file:
        try:
            metrics = json.loads(Path(args.metrics_file).read_text(encoding='utf-8-sig'))
            if not isinstance(metrics, dict):
                metrics = {'result': metrics}
            json.dumps(metrics, allow_nan=False)
        except (OSError, ValueError) as exc:
            metrics = {}
            metrics_warning = f'Metrics could not be decoded; retaining the original file as evidence when available: {exc}'
    return notes, notes_error, metrics, metrics_warning


def origin_intent(args):
    """Absent options do not change historical retry fingerprints."""
    result = {name: getattr(args, name) for name in
              ('origin_type', 'origin_node', 'origin_artifact', 'origin_url', 'origin_reason', 'origin_retrospective')
              if getattr(args, name, None) not in (None, False)}
    if result:
        if not isinstance(result.get('origin_type'), str) or not result['origin_type'].strip():
            raise ClientError('Origin details require a nonempty --origin-type.')
        if result['origin_type'].strip() == 'independent' and result.get('origin_node'):
            raise ClientError('Independent exploration cannot declare source nodes.')
        if result.get('origin_url') and urlsplit(result['origin_url']).scheme not in ('http', 'https'):
            raise ClientError('Origin URL must use http or https.')
    return result


def question_origin(client, outbox, project_id, supplied, observed_at, *, exclude=None, default_reason=None):
    if not supplied:
        return None
    result = {'type': supplied['origin_type'].strip(), 'recordedAt': observed_at}
    if 'origin_reason' in supplied or default_reason is not None:
        result['reason'] = supplied.get('origin_reason', default_reason)
    if supplied.get('origin_artifact'):
        result['artifactIds'] = list(dict.fromkeys(supplied['origin_artifact']))
    if supplied.get('origin_url'):
        result['url'] = supplied['origin_url']
    if supplied.get('origin_retrospective'):
        result['retrospective'] = True
    if supplied.get('origin_node'):
        known = semantic_nodes(client, outbox, project_id, exclude=exclude)
        remote = None
        resolved = []
        for value in supplied['origin_node']:
            reference = exact_reference(known, value)
            if reference is None:
                if remote is None:
                    try:
                        remote = client.project(project_id)['nodes']
                    except ClientError:
                        remote = []
                reference = exact_reference(remote, value)
            if reference is None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
                raise ClientError('Origin source title was not found; use a retained node ID: ' + value)
            resolved.append(reference['id'] if reference else value)
        result['nodeIds'] = list(dict.fromkeys(resolved))
    return result


def record(client, args):
    if args.title is None and not args.node:
        raise ClientError('Creating a record requires a nonempty --title; --node updates may omit it.')
    if args.title is not None and not args.title.strip():
        raise ClientError('--title must be nonempty when supplied.')
    notes, notes_error, metrics, metrics_warning = capture_inputs(args)
    intent = {'command': 'record', **{key: getattr(args, key) for key in
              ('title', 'summary', 'conclusion', 'kind', 'node', 'after', 'relation', 'independent', 'parent', 'status', 'artifact', 'importance', 'importance_reason')},
              'notes': notes, 'notesFile': args.notes_file,
              'metrics': metrics, 'hasMetrics': args.metrics_file is not None and metrics_warning is None,
              'metricsFile': args.metrics_file}
    if args.container:
        intent['container'] = True
    supplied_origin = origin_intent(args)
    intent.update(supplied_origin)
    path, task = task_identity(client, args, intent)
    # Missing/unreadable source text must not prevent a stable request from
    # returning or delivering its existing frozen analysis. New work still fails.
    if notes_error is not None and (not args.request_id or not path.is_file()):
        raise notes_error
    if not intent['hasMetrics']:
        task['runId'] = None
    with task_lock(path):
        existing = load_existing(path, task, frozen_notes=notes_error is not None)
        if existing:
            emit(sync_task(client, path, existing))
            return 0
        if notes_error is not None:
            raise notes_error
        directory = Path(task['captureRoot']) / task['taskId']
        ensure_directory(directory)
        at = stamp()
        task.update({'capturedAt': at, 'status': 'recorded'})
        if metrics_warning:
            task['recordingWarnings'].append(metrics_warning)
        node = {'id': task['nodeId']}
        origin = question_origin(client, path.parent, args.project, supplied_origin, at, exclude=path)
        if origin is not None:
            node['questionOrigin'] = origin
        if args.title is not None:
            node['title'] = args.title
        if args.conclusion is not None:
            node['conclusion'] = args.conclusion
        if notes is not None:
            node['notes'] = notes
        if args.kind is not None:
            node['kind'] = args.kind
        for option, field in (('summary', 'summary'), ('status', 'status'), ('importance', 'importance'), ('importance_reason', 'importanceReason')):
            if getattr(args, option) is not None:
                node[field] = getattr(args, option)
        if not args.node:
            node.setdefault('status', 'active')
            node.setdefault('kind', 'finding')
            node['createdAt'] = at
        parent = parent_reference(client, path.parent, args.project, args.parent, exclude=path, child_id=node['id'])
        if parent and parent['id'] == node['id']:
            raise ClientError('A research node cannot contain itself.')
        if parent:
            node['parentId'] = parent['id']
        if args.container:
            node['isContainer'] = True
        task['operations'] = parent_operations(parent) + [{'op': 'node.update' if args.node else 'node.add', 'data': node}]
        capture_relationship(client, args, path, task)
        if intent['hasMetrics']:
            task['operations'].append({'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
                'title': args.title or '', 'status': 'completed', 'startedAt': None, 'finishedAt': None, 'capturedAt': at,
                'metrics': metrics, 'origin': 'observed', 'configuration': {'capturedExternalResult': True}}})
        persist_task(path, task)
        artifacts = list(args.artifact)
        if metrics_warning and args.metrics_file not in artifacts:
            artifacts.append(args.metrics_file)
        for index, requested in enumerate(artifacts):
            stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
        task['state'] = 'ready'
        persist_task(path, task)
        emit(sync_task(client, path, task))
    return 0


def semantic_nodes(client, outbox, project_id, exclude=None):
    """Resolve exact references from dated context and ancestor queues only."""
    nodes, _, _ = local_node_view(client, outbox, project_id, exclude=exclude, include_cache=True)
    return nodes


def execution_reference(client, outbox, project_id, value, exclude=None):
    """An execute title can identify a run on an existing question, not a new node."""
    runs = {}
    _, caches, _ = local_node_view(client, outbox, project_id, exclude=exclude, include_cache=True)
    for cache in caches:
        try:
            context = json.loads(Path(cache['localCachePath']).read_text(encoding='utf-8'))['context']
            for run in context.get('runs', []):
                if isinstance(run.get('id'), str):
                    runs[run['id']] = run
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for directory in ancestor_outboxes(outbox, client.queue_root):
        for path in directory.glob('*.json'):
            if exclude is not None and path.resolve() == Path(exclude).resolve():
                continue
            try:
                task = read_queue_task(path)
                if (task['url'] != client.url or task['projectId'] != project_id or
                        task['state'] not in ('ready','synced')):
                    continue
                for operation in task.get('operations', []):
                    if operation.get('op') == 'run.add':
                        run = operation['data']
                        runs[run['id']] = run
            except (OSError, ValueError, KeyError, TypeError):
                continue
    matches = [r for r in runs.values() if r.get('id') == value]
    if not matches:
        matches = [r for r in runs.values() if r.get('title') == value]
    if len(matches) > 1:
        raise ClientError('Execution title is ambiguous; use its retained run ID: ' + value)
    if matches:
        return {'id': matches[0]['nodeId'], 'runIds': [matches[0]['id']]}
    return None


def exact_reference(nodes, value):
    by_id = [node for node in nodes if node['id'] == value]
    if by_id:
        return by_id[0]
    matches = [node for node in nodes if node.get('title') == value]
    if len(matches) > 1:
        raise ClientError('Reference title is ambiguous; use an existing ID: ' + value)
    return matches[0] if matches else None


def parent_reference(client, outbox, project_id, value, exclude=None, child_id=None):
    if value is None:
        return None
    nodes = semantic_nodes(client, outbox, project_id, exclude=exclude)
    parent = exact_reference(nodes, value)
    if parent is None and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        # Explicit identifiers retain the established offline reference contract:
        # validation at delivery may find a node absent from this local snapshot.
        return {'id': value}
    if parent is None:
        raise ClientError('Parent was not found in retained local records or dated context: ' + value
                          + '. Read context or record the parent before nesting work.')
    by_id = {node['id']: node for node in nodes}
    ancestor, seen = parent['id'], set()
    while ancestor and ancestor not in seen:
        if ancestor == child_id:
            raise ClientError('Containment would create a cycle; choose another parent.')
        seen.add(ancestor)
        ancestor = by_id.get(ancestor, {}).get('parentId')
    return parent


def parent_operations(parent):
    return ([{'op': 'node.update', 'data': {'id': parent['id'], 'isContainer': True}}]
            if parent and not parent.get('isContainer') else [])


def is_reference_id(value):
    return bool(re.fullmatch(r'(?:node|question|run|artifact|capture|study|edge)-[A-Za-z0-9_.-]+', value)
                or re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value))


def semantic_question(client, outbox, project_id, text, exclude=None):
    title = text.strip()
    if not title:
        raise ClientError('A research question must be nonempty.')
    nodes = semantic_nodes(client, outbox, project_id, exclude=exclude)
    existing = exact_reference(nodes, title)
    reference_only = False
    if existing is None and is_reference_id(title):
        # A retained ID is an identity, never new question prose. The frozen
        # reference can wait offline and resolve later without losing findings.
        try:
            remote = client.project(project_id)
            key = remote.get('nodeAliases', {}).get(title, title)
            existing = next((node for node in remote.get('nodes', []) if node['id'] == key), None)
            if existing:
                nodes = [*nodes, existing]
        except ClientError:
            pass
        if existing is None:
            existing = {'id': title, 'title': ''}
            reference_only = True
    if existing is None:
        key = hashlib.sha256(json.dumps([client.url, project_id, title], ensure_ascii=False).encode('utf-8')).hexdigest()[:32]
        existing = {'id': 'question-' + key, 'title': title}
    question = {'id': existing['id'], 'title': existing.get('title') or ('' if is_reference_id(title) else title)}
    if reference_only or not question['title']:
        question['referenceOnly'] = True
    question.update({field: existing[field] for field in ('nextAction', 'pauseReason', 'resumeWhen', 'parentId', 'isContainer', 'collapsed')
                     if field in existing and (existing[field] is not None or field == 'parentId')})
    # Containment is structural: existing children establish ownership even
    # when an older record has a stale false flag. Legacy groups default to
    # containers unless deliberately disabled and without any children.
    owns_children = any(node.get('parentId') == existing['id'] for node in nodes)
    legacy_container = existing.get('kind') in ('group', 'container') and existing.get('isContainer') is not False
    if existing.get('isContainer') or owns_children or legacy_container:
        question['isContainer'] = True
    return question | {'kind': existing.get('kind') or 'question', 'status': existing.get('status') or 'active'}, nodes


def event(client, args):
    question_text = args.question.strip()
    if not question_text:
        raise ClientError('event requires a nonempty research question.')
    event_type = next((kind for kind in ('finding', 'correction', 'direction') if getattr(args, kind) is not None), None)
    change = getattr(args, event_type) if event_type else None
    if change is not None and not change.strip():
        raise ClientError('A research change must contain its actual finding, correction or direction.')
    if args.relation and not args.after:
        raise ClientError('--relation requires an explicit --after reference.')
    if args.summarizes and event_type is None:
        raise ClientError('--summarizes requires a finding, correction or direction to retain the resulting answer.')
    notes, notes_error, metrics, metrics_warning = capture_inputs(args)
    intent = {'command': 'event', **{key: getattr(args, key) for key in
              ('question', 'reason', 'finding', 'correction', 'direction', 'after', 'relation', 'evidence', 'status', 'next_action', 'pause_reason', 'resume_when', 'artifact', 'importance', 'importance_reason')},
              'notes': notes, 'notesFile': args.notes_file,
              'metrics': metrics, 'hasMetrics': args.metrics_file is not None and metrics_warning is None,
              'metricsFile': args.metrics_file}
    if args.summarizes:
        intent['summarizes'] = args.summarizes
    if args.container:
        intent['container'] = True
    if args.parent is not None:
        intent['parent'] = args.parent
    supplied_origin = origin_intent(args)
    intent.update(supplied_origin)
    path, task = task_identity(client, args, intent)
    if notes_error is not None and (not args.request_id or not path.is_file()):
        raise notes_error
    if not intent['hasMetrics']:
        task['runId'] = None
    with task_lock(path):
        existing = load_existing(path, task, frozen_notes=notes_error is not None)
        if existing:
            emit(sync_task(client, path, existing))
            return 0
        if notes_error is not None:
            raise notes_error
        question, nodes = semantic_question(client, path.parent, args.project, question_text, exclude=path)
        parent = parent_reference(client, path.parent, args.project, args.parent, exclude=path, child_id=question['id'])
        if parent and parent['id'] == question['id']:
            raise ClientError('A research question cannot contain itself.')
        if parent:
            question['parentId'] = parent['id']
        if args.container or parent:
            question['isContainer'] = True
        if args.reason is not None:
            question['summary'] = args.reason
        task.update(questionId=question['id'], eventType=event_type or 'question', capturedAt=stamp(), status='recorded')
        origin = question_origin(client, path.parent, args.project, supplied_origin, task['capturedAt'], exclude=path, default_reason=args.reason)
        if origin is not None:
            question['questionOrigin'] = origin
        if metrics_warning:
            task['recordingWarnings'].append(metrics_warning)
        task['operations'] = parent_operations(parent) + [{'op': 'node.ensure', 'data': question}]
        if event_type:
            node = {'id': task['nodeId'], 'title': change, 'kind': event_type, 'status': 'completed',
                    'conclusion': change, 'createdAt': task['capturedAt']}
            if question.get('isContainer'):
                node['parentId'] = question['id']
            if args.reason is not None:
                node['summary'] = args.reason
            if notes is not None:
                node['notes'] = notes
            task['operations'].append({'op': 'node.add', 'data': node})
            task['operations'].append({'op': 'edge.add', 'data': {
                'id': 'edge-' + task['taskId'] + '-question', 'source': question['id'], 'target': task['nodeId'],
                'relation': 'has_' + event_type, 'label': {'finding': '发现', 'correction': '纠正', 'direction': '转向'}[event_type],
                'basis': 'observed'}})
        else:
            task['nodeId'] = question['id']
        importance = {field: getattr(args, option) for option, field in
                      (('importance', 'importance'), ('importance_reason', 'importanceReason'))
                      if getattr(args, option) is not None}
        if event_type:
            node.update(importance)
        update = {'id': question['id'], **(importance if not event_type else {})}
        if origin is not None:
            update['questionOrigin'] = origin
        if args.container or parent:
            update['isContainer'] = True
        if parent:
            update['parentId'] = parent['id']
        if args.reason is not None and question.get('isContainer'):
            update['summary'] = args.reason
        for option, field in (('status', 'status'), ('next_action', 'nextAction'),
                              ('pause_reason', 'pauseReason'), ('resume_when', 'resumeWhen')):
            value = getattr(args, option)
            if value is not None:
                update[field] = value
        if not event_type and notes is not None:
            update['notes'] = notes
        if len(update) > 1:
            task['operations'].append({'op': 'node.update', 'data': update})
        links = [(value, 'supports', 'evidence-' + str(index)) for index, value in enumerate(args.evidence)]
        links.extend((value, 'summarizes', 'summary-' + str(index)) for index, value in enumerate(args.summarizes))
        if args.after:
            relation = args.relation or {'finding': 'related_to', 'correction': 'revises', 'direction': 'leads_to', None: 'branches'}[event_type]
            links.append((args.after, relation, 'after'))
        for value, relation, suffix in links:
            try:
                referenced = exact_reference(nodes, value)
                if referenced is None:
                    referenced = execution_reference(client, path.parent, args.project, value, exclude=path)
            except ClientError as exc:
                task['recordingWarnings'].append(str(exc) + '; the finding is retained without that relationship.')
                continue
            source = referenced['id'] if referenced else value
            if not referenced and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
                task['recordingWarnings'].append('Reference title was not found locally or in retained context: ' + value
                                                 + '; the finding is retained without that relationship.')
                continue
            if source == task['nodeId']:
                continue
            task['operations'].append({'op': 'edge.add', 'data': {
                'id': 'edge-' + task['taskId'] + '-' + suffix, 'source': source, 'target': task['nodeId'],
                'relation': relation, 'basis': 'observed',
                **({'runIds': referenced['runIds']} if relation == 'supports' and referenced and referenced.get('runIds') else {})}})
        if intent['hasMetrics']:
            task['operations'].append({'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
                'title': change or question['title'], 'status': 'completed', 'startedAt': None, 'finishedAt': None,
                'capturedAt': task['capturedAt'], 'metrics': metrics, 'origin': 'observed',
                'configuration': {'capturedExternalResult': True}}})
        directory = Path(task['captureRoot']) / task['taskId']
        ensure_directory(directory)
        persist_task(path, task)
        artifacts = list(args.artifact)
        if metrics_warning and args.metrics_file not in artifacts:
            artifacts.append(args.metrics_file)
        for index, requested in enumerate(artifacts):
            stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
        task['state'] = 'ready'
        persist_task(path, task)
        emit(sync_task(client, path, task))
    return 0


def file_signature(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def queue_dependency_map(items):
    """Exact same-project queued producers only; chronology is not dependency."""
    producers, references = {}, {}
    for path, _root, receipt in items:
        scope = (receipt['url'], receipt['projectId'])
        refs, created = set(), set()
        operations = receipt.get('operations')
        for op in operations if isinstance(operations, list) else []:
            if not isinstance(op, dict) or not isinstance(op.get('data'), dict):
                continue
            data = op['data']
            if op.get('op') in ('node.add', 'run.add', 'artifact.add') or (op.get('op') == 'node.ensure' and not data.get('referenceOnly')):
                if isinstance(data.get('id'), str):
                    created.add(data['id'])
            if op.get('op') in ('node.update', 'run.update') or (op.get('op') == 'node.ensure' and data.get('referenceOnly')):
                if isinstance(data.get('id'), str):
                    refs.add(data['id'])
            for key in ('nodeId', 'parentId', 'source', 'target', 'runId', 'supersedes'):
                if isinstance(data.get(key), str):
                    refs.add(data[key])
            for key in ('runIds', 'artifactIds'):
                if isinstance(data.get(key), list):
                    refs.update(value for value in data[key] if isinstance(value, str))
            origin = data.get('questionOrigin')
            if isinstance(origin, dict):
                for key in ('nodeIds', 'artifactIds'):
                    if isinstance(origin.get(key), list):
                        refs.update(value for value in origin[key] if isinstance(value, str))
        artifacts = receipt.get('artifacts')
        for artifact in artifacts if isinstance(artifacts, list) else []:
            if isinstance(artifact, dict) and isinstance(artifact.get('id'), str):
                created.add(artifact['id'])
        focus_body = receipt.get('focus')
        if receipt.get('kind') == 'focus' and isinstance(focus_body, dict) and focus_body.get('action') != 'end':
            node_ids = focus_body.get('nodeIds')
            if isinstance(node_ids, list):
                refs.update(key for key in node_ids if isinstance(key, str))
        references[path] = (scope, refs - created)
        for identifier in created:
            producers.setdefault((scope, identifier), []).append(path)
    result = {}
    for path, (scope, refs) in references.items():
        # Ambiguous producers are not guessed. The backend remains authoritative.
        result[path] = {producers[(scope, identifier)][0] for identifier in refs
                        if len(producers.get((scope, identifier), [])) == 1 and producers[(scope, identifier)][0] != path}
    return result


def queue_delivery_order(items):
    dependencies = queue_dependency_map(items)
    by_path = {item[0]: item for item in items}
    ordered, visited, visiting = [], set(), set()
    def visit(path):
        if path in visited or path in visiting:
            return
        visiting.add(path)
        for dependency in sorted(dependencies.get(path, ())):
            if dependency in by_path:
                visit(dependency)
        visiting.remove(path)
        visited.add(path)
        ordered.append(by_path[path])
    def priority(item):
        receipt = item[2]
        ending = isinstance(receipt.get('focus'), dict) and receipt['focus'].get('action') == 'end'
        return (receipt.get('kind') != 'project', not ending, receipt.get('capturedAt') or receipt.get('startedAt') or receipt.get('preparedAt') or '',
                receipt['focus'].get('sequence', -1) if isinstance(receipt.get('focus'), dict) else -1, str(item[0]))
    for item in sorted(items, key=priority):
        visit(item[0])
    return ordered


def drain_outbox(client, outbox, project_id=None, stop_event=None, acknowledged=None):
    """Submit frozen tasks only. This function never starts a subprocess."""
    results = []
    candidates = []
    for path in Path(outbox).glob('*.json'):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            signature = file_signature(path)
            if acknowledged is not None and acknowledged.get(str(path)) == signature:
                continue
            task = read_queue_task(path)
            if task['url'] != client.url or (project_id and task['projectId'] != project_id):
                continue
            if task['state'] == 'synced':
                if acknowledged is not None:
                    acknowledged[str(path)] = signature
                continue
            candidates.append((path, None, task))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
    for path, _root, _previous in queue_delivery_order(candidates):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            with task_lock(path):
                task = read_queue_task(path)
                if task['url'] != client.url or (project_id and task['projectId'] != project_id):
                    continue
                if task['state'] == 'synced':
                    continue
                result = sync_project(client, path, task) if task.get('kind') == 'project' else sync_task(client, path, task)
                results.append(result)
                if not result['pending'] and acknowledged is not None:
                    acknowledged[str(path)] = file_signature(path)
        except (ClientError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
    return results


def sync(client, args):
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    results = drain_outbox(client, outbox, args.project)
    pending = sum(bool(result['pending']) for result in results)
    emit({'records': results, 'pending': pending})
    return 1 if pending else 0


def research_review(client, outbox, project_id):
    nodes, caches, warnings = local_node_view(client, outbox, project_id, include_cache=True)
    questions = [node for node in nodes if node.get('kind') == 'question']
    open_questions = [{field: node.get(field) for field in
                       ('id', 'title', 'status', 'nextAction', 'pauseReason', 'resumeWhen')}
                      for node in questions if node.get('status') in ('active', 'running')]
    known = bool(questions or caches)
    incomplete = bool(warnings or any(not isinstance(node.get('status'), str) for node in questions))
    return {'source': 'local_queue_and_dated_context', 'scope': 'current_directory_and_ancestors',
            'coverage': 'local_snapshot_only',
            'availability': 'partial' if incomplete else ('available' if known else 'unknown'),
            'openQuestions': open_questions,
            'needsReview': True if open_questions else (None if incomplete or not known else False),
            'cachedContexts': sorted(caches, key=lambda cache: local_timestamp(cache['cachedAt'])),
            'note': 'Review questions actually worked on; local receipts and dated caches do not prove global research state or scientific success.',
            **({'localReadWarnings': warnings[:20]} if warnings else {})}


def status(client, args):
    """Read atomic local receipts only; never contact the server or advance work."""
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    records, plans, warnings = [], [], []
    seen = set()
    for directory in ancestor_outboxes(outbox, client.queue_root):
        try:
            paths = sorted(directory.glob('*.json'))
        except OSError as exc:
            warnings.append(f'{directory}: {exc}')
            continue
        for path in paths:
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                task = read_queue_task(path)
                if task['url'] != client.url or task['projectId'] != args.project:
                    continue
                if task.get('kind') == 'project':
                    plans.append({'state': task['state'], 'preparedAt': task.get('preparedAt'), 'delivery': task.get('delivery', {})})
                else:
                    records.append({**task_result(task), 'state': task['state']})
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                warnings.append(f'{path}: {exc}')
    records.sort(key=lambda record: str(record.get('capturedAt') or record.get('finishedAt') or record.get('startedAt') or ''))
    pending_records = [record for record in records if record['pending']]
    has_records = bool(records or plans)
    pending = bool(pending_records or any(plan['state'] != 'synced' for plan in plans))
    result = {'projectId': args.project, 'source': 'local', 'checkedAt': stamp(),
              'scope': 'current_directory_and_ancestors', 'transportChecked': False,
              'deliveryState': 'partial' if warnings else ('pending' if pending else ('synced' if has_records else 'unknown')),
              'pending': True if pending else (None if warnings or not has_records else False),
              'recordCount': len(records), 'syncedCount': len(records) - len(pending_records),
              'pendingCount': len(pending_records),
              'blockedCount': sum(bool(record.get('delivery', {}).get('lastError')) for record in pending_records),
              'incompleteCount': sum(record['state'] not in ('ready', 'synced') for record in records),
              'records': records[-20:], 'pendingRecords': pending_records[-20:], 'projectPlans': plans,
              'researchReview': research_review(client, outbox, args.project)}
    if len(records) > 20:
        result['recordsTruncated'] = True
    if len(pending_records) > 20:
        result['pendingRecordsTruncated'] = True
    if warnings:
        result.update({'localReadWarnings': warnings[:20], 'warningCount': len(warnings)})
    emit(result)
    return 0


def run_command(command, stdout, stderr):
    started = time.monotonic()
    process, error, cancelled = None, None, False
    try:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, shell=False)
        exit_code = process.wait()
    except KeyboardInterrupt:
        cancelled = True
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        exit_code = 130
    except OSError as exc:
        error, exit_code = str(exc), 127
        if stderr:
            try:
                stderr.write((error + '\n').encode('utf-8'))
            except TypeError:
                stderr.write(error + '\n')
    # Python uses negative return codes for signals; expose the conventional shell code.
    exit_code = 128 - exit_code if exit_code < 0 else exit_code
    return {'exitCode': exit_code, 'wallTimeMs': round((time.monotonic() - started) * 1000, 3),
            'status': 'cancelled' if cancelled else ('completed' if exit_code == 0 else 'failed')}, error


def execute(client, args):
    command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not command:
        raise ClientError('execute requires -- COMMAND [ARG ...].')
    if args.node is not None and args.question is not None:
        raise ClientError('Use either --question or --node for an existing research unit.')
    intent = {'command': 'execute', 'argv': command, 'cwd': str(Path.cwd()), 'node': args.node,
              'title': args.title, 'artifact': args.artifact, 'after': args.after,
              'relation': args.relation, 'independent': args.independent}
    if args.question is not None:
        intent['question'] = args.question
    if args.parent is not None:
        intent['parent'] = args.parent
    path, task = task_identity(client, args, intent)
    with ExitStack() as stack:
        durable = True
        # A lock/reuse conflict must never execute the same stable request twice.
        try:
            stack.enter_context(task_lock(path))
        except OSError as exc:
            durable = False
            task['recordingWarnings'].append('Local outbox unavailable: ' + str(exc))
        existing = load_existing(path, task)
        if existing:
            emit(sync_task(client, path, existing))
            return existing.get('exitCode', 1)
        question = None
        if args.question is not None:
            question, _ = semantic_question(client, path.parent, args.project, args.question, exclude=path)
            task['nodeId'] = task['questionId'] = question['id']
        parent = parent_reference(client, path.parent, args.project, args.parent, exclude=path, child_id=task['nodeId'])
        if parent and parent['id'] == task['nodeId']:
            raise ClientError('A research node cannot contain itself.')
        directory = Path(task['captureRoot']) / task['taskId']
        stdout = stderr = None
        try:
            ensure_directory(directory)
            stdout = stack.enter_context((directory / 'stdout.txt').open('wb'))
            stderr = stack.enter_context((directory / 'stderr.txt').open('wb'))
        except OSError as exc:
            durable = False
            task['captureAvailable'] = False
            task['recordingWarnings'].append('Local capture unavailable: ' + str(exc))
            if stdout:
                stdout.close()
            stdout = stderr = None
        task.update({'state': 'running', 'startedAt': stamp()})
        if durable:
            try:
                persist_task(path, task)
            except OSError as exc:
                durable = False
                task['recordingWarnings'].append('Local outbox unavailable: ' + str(exc))
        # If recording storage fails, send command output to stderr and still run it once.
        outcome, error = run_command(command, stdout or sys.stderr, stderr or sys.stderr)
        if stdout:
            stdout.close()
        if stderr:
            stderr.close()
        task.update(outcome, finishedAt=stamp())
        task['operations'] = [{'op': 'run.add', 'data': {'id': task['runId'], 'nodeId': task['nodeId'],
            'title': args.title, 'status': task['status'], 'startedAt': task['startedAt'], 'finishedAt': task['finishedAt'],
            'metrics': {key: task[key] for key in ('exitCode', 'wallTimeMs')}, 'origin': 'observed',
            'configuration': {'command': command, 'cwd': str(Path.cwd()), 'artifactPaths': args.artifact},
            'events': [{'id': 'start-' + task['taskId'], 'type': 'started', 'message': 'Command started', 'at': task['startedAt']},
                       {'id': 'finish-' + task['taskId'], 'type': 'finished', 'message': error or f'Process exited with code {task["exitCode"]}',
                        'at': task['finishedAt'], 'exitCode': task['exitCode'], 'elapsedMs': task['wallTimeMs']}]}}]
        if question:
            task['operations'].insert(0, {'op': 'node.ensure', 'data': question})
        elif args.node is None:
            node = {'id': task['nodeId'], 'title': args.title, 'createdAt': task['startedAt'],
                    'status': 'paused' if task['status'] == 'cancelled' else task['status']}
            if task['status'] == 'cancelled':
                node['pauseReason'] = 'Command interrupted'
            task['operations'].insert(0, {'op': 'node.add', 'data': node})
        if parent:
            task['operations'] = parent_operations(parent) + task['operations']
            task['operations'].append({'op': 'node.update', 'data': {'id': task['nodeId'], 'parentId': parent['id']}})
        if question is None or args.after:
            capture_relationship(client, args, path, task)
        if durable:
            for filename, title in (('stdout.txt', 'Standard output'), ('stderr.txt', 'Standard error')):
                stage_artifact(task, directory / filename, title, directory / filename)
            for index, requested in enumerate(args.artifact):
                stage_artifact(task, requested, Path(requested).name, directory / (str(index) + '-' + Path(requested).name))
            task['state'] = 'ready'
            try:
                persist_task(path, task)
                result = sync_task(client, path, task)
            except OSError as exc:
                result = task_result(task, ['Could not persist command outcome: ' + str(exc)])
        else:
            result = task_result(task, ['No durable record is available for sync.'])
        emit(result)
        return task['exitCode']


def focus_owner(outbox, explicit=None, create=True):
    owner = explicit or os.environ.get('EXP_OBSERVER_OWNER_ID') or os.environ.get('CODEX_THREAD_ID')
    if owner:
        if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', owner):
            raise ClientError('Conversation owner must be an opaque ID using 1–128 letters, numbers, dots, underscores or hyphens.')
        return owner
    for directory in ancestor_outboxes(outbox):
        path = directory.parent / 'focus-owner.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))['ownerId']
    if not create:
        return None
    path = Path(outbox).parent / 'focus-owner.json'
    with task_lock(path):
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))['ownerId']
        owner = 'conversation-' + uuid4().hex
        save_task(path, {'ownerId': owner})
    return owner


def focus_location(outbox, url, project_id, owner):
    key = hashlib.sha256(json.dumps([url, project_id, owner], ensure_ascii=False).encode()).hexdigest()
    for directory in ancestor_outboxes(outbox):
        path = directory.parent / 'focus' / (key + '.json')
        if path.exists():
            return path
    return Path(outbox).parent / 'focus' / (key + '.json')


def queue_focus(outbox, url, project_id, association, action, *, retain_selection=True):
    body = {key: association[key] for key in ('ownerId', 'leaseId', 'nodeIds', 'label', 'ttlSeconds', 'sequence', 'observedAt')}
    body['action'] = action
    if not retain_selection:
        body.pop('nodeIds')
    key = hashlib.sha256(json.dumps([url, project_id, body['leaseId'], body['sequence']], ensure_ascii=False).encode()).hexdigest()[:32]
    path = Path(outbox) / ('focus-' + key + '.json')
    task = {'version': 1, 'clientVersion': CLIENT_VERSION, 'kind': 'focus', 'taskId': key, 'requestId': 'focus-' + key,
            'url': url, 'projectId': project_id, 'state': 'ready', 'focus': body,
            'capturedAt': body['observedAt'], 'intent': {'command': 'focus', 'title': body['label'] or 'Conversation focus'}}
    with task_lock(path):
        if path.exists():
            existing = read_queue_task(path)
            if existing.get('focus') != body:
                raise ClientError('Focus sequence already identifies another update.', code='queue_identity_conflict')
            return path, existing
        save_task(path, task)
    return path, task


def heartbeat_association(url, project_id, outbox):
    """A write refreshes an explicitly joined conversation, without choosing its science."""
    try:
        owner = focus_owner(outbox, create=False)
        if not owner:
            return
        location = focus_location(outbox, url, project_id, owner)
        if not location.exists():
            return
        with task_lock(location):
            association = json.loads(location.read_text(encoding='utf-8'))
            if association.get('ended'):
                return
            last = local_timestamp(association.get('observedAt'))
            if last is not None and time.time() - last < 45:
                return
            association.update(sequence=association['sequence'] + 1, observedAt=stamp())
            queue_focus(location.parent.parent / 'outbox', url, project_id, association, 'heartbeat', retain_selection=False)
            save_task(location, association)
    except (ClientError, OSError, ValueError, KeyError, TypeError):
        # The scientific receipt remains durable even if optional liveness fails.
        return


def sync_focus(client, path, task):
    current = read_queue_task(path)
    if any(current.get(key) != task.get(key) for key in ('kind', 'url', 'projectId', 'taskId', 'requestId', 'focus')):
        raise ClientError('Focus queue identity changed.', code='queue_identity_conflict')
    if current['state'] == 'synced':
        return task_result(current)
    warnings = []
    try:
        delivery_attempt(path, current)
        response = client.request(client.project_route(current['projectId']) + '/focus', current['focus'])
        current['focusState'] = response.get('session', {}).get('state')
        current['state'] = 'synced'
        delivery_succeeded(path, current)
    except (ClientError, OSError, ValueError) as exc:
        # A superseded/ended lease is obsolete, not a reason to revive work forever.
        if getattr(exc, 'code', None) in ('focus_ended', 'stale_focus'):
            current['state'] = 'synced'
            current['superseded'] = True
            if exc.code == 'focus_ended' or current['focus']['action'] == 'start':
                current['focusState'] = 'ended'
                # Background recovery owns only the enrolled receipt, not an
                # ancestor conversation association (which may be outside its
                # workspace or symlinked). A foreground owner can reconcile its
                # own local association on the next explicit focus call.
                if client.queue_root is None:
                    location = focus_location(path.parent, client.url, current['projectId'], current['focus']['ownerId'])
                    try:
                        with task_lock(location):
                            association = json.loads(location.read_text(encoding='utf-8'))
                            if association.get('leaseId') == current['focus']['leaseId']:
                                association['ended'] = True
                                save_task(location, association)
                    except (ClientError, OSError, ValueError):
                        pass
            delivery_succeeded(path, current)
        else:
            current['state'] = 'ready'
            delivery_failed(path, current, exc, warnings)
            warnings.append(str(exc))
    return task_result(current, warnings)


def deliver_focus_updates(client, outbox, project_id):
    pending = []
    for directory in ancestor_outboxes(outbox, client.queue_root):
        for path in directory.glob('focus-*.json'):
            try:
                task = read_queue_task(path)
                if task.get('kind') == 'focus' and task['url'] == client.url and task['projectId'] == project_id and task['state'] == 'ready':
                    pending.append((task['capturedAt'], task['focus']['sequence'], path, task))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    blocked_leases = set()
    for _, _, path, task in sorted(pending, key=lambda item: (item[3]['focus']['action'] != 'end', item[:2])):
        lease_key = (task['focus']['ownerId'], task['focus']['leaseId'])
        if lease_key in blocked_leases:
            continue
        try:
            with task_lock(path):
                result = sync_focus(client, path, task)
                if result['pending']:
                    blocked_leases.add(lease_key)
        except (ClientError, OSError, ValueError):
            blocked_leases.add(lease_key)


def next_focus_stamp(previous=None):
    current = datetime.now(timezone.utc)
    earlier = local_timestamp(previous)
    if earlier is not None and current.timestamp() <= earlier:
        current = datetime.fromtimestamp(earlier, timezone.utc) + timedelta(milliseconds=1)
    return current.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def maintain_focus(client, args, ending=False):
    outbox = Path.cwd() / '.exp-observer-runs' / 'outbox'
    owner = focus_owner(outbox, args.owner)
    location = focus_location(outbox, client.url, args.project, owner)
    with task_lock(location):
        association = json.loads(location.read_text(encoding='utf-8')) if location.exists() else None
        if ending and association is None:
            emit({'projectId': args.project, 'ownerId': owner, 'state': 'ended', 'pending': False})
            return 0
        if ending and association.get('ended'):
            path, _receipt = queue_focus(location.parent.parent / 'outbox', client.url, args.project, association, 'end')
            deliver_focus_updates(client, path.parent, args.project)
            emit(task_result(read_queue_task(path)))
            return 0
        starting = association is None or association.get('ended')
        nodes = getattr(args, 'node', None)
        if nodes is not None:
            retained = semantic_nodes(client, outbox, args.project)
            resolved = []
            for value in nodes:
                node = exact_reference(retained, value)
                if node is None:
                    try:
                        node = exact_reference(client.project(args.project)['nodes'], value)
                    except ClientError:
                        pass
                    if node is None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
                        raise ClientError('Focus title was not found; use the retained node ID: ' + value)
                resolved.append(node['id'] if node else value)
            nodes = list(dict.fromkeys(resolved))
        ttl = getattr(args, 'ttl_seconds', None)
        if ttl is not None and not 60 <= ttl <= 3600:
            raise ClientError('Focus TTL must be 60–3600 seconds.')
        association = {**(association or {}), 'ownerId': owner,
                       'leaseId': 'lease-' + uuid4().hex if starting else association['leaseId'],
                       'nodeIds': nodes if nodes is not None else ([] if starting else association['nodeIds']),
                       'label': getattr(args, 'label', None) if getattr(args, 'label', None) is not None else (association or {}).get('label', ''),
                       'ttlSeconds': ttl or (association or {}).get('ttlSeconds', 900),
                       'sequence': 0 if starting else association['sequence'] + 1,
                       'observedAt': next_focus_stamp((association or {}).get('observedAt')), 'ended': ending}
        path, receipt = queue_focus(location.parent.parent / 'outbox', client.url, args.project, association,
                                    'end' if ending else ('start' if starting else 'heartbeat'))
        save_task(location, association)
    deliver_focus_updates(client, path.parent, args.project)
    emit(task_result(read_queue_task(path)))
    return 0


def focus(client, args):
    return maintain_focus(client, args)


def unfocus(client, args):
    return maintain_focus(client, args, ending=True)


def task(client, args):
    """Record explicit remote lifecycle facts; no command is run or inferred."""
    status_value = args.status
    if args.task_action == 'update' and status_value is None and not args.metrics_file:
        raise ClientError('task update requires --status or --metrics-file.')
    if status_value in ('completed', 'failed', 'cancelled') and not args.finished_at:
        raise ClientError('A terminal remote task requires its actual --finished-at timestamp.')
    if args.finished_at is not None and local_timestamp(args.finished_at) is None:
        raise ClientError('finished-at requires an explicit timezone timestamp.')
    if args.task_action == 'start' and local_timestamp(args.started_at) is None:
        raise ClientError('started-at requires an explicit original timezone timestamp.')
    intent = {key: value for key, value in vars(args).items() if key not in ('url', 'no_autostart')}
    # Store metrics verbatim at first capture; retries use the retained payload.
    args.node = getattr(args, 'node', None)
    path, receipt = task_identity(client, args, intent)
    with task_lock(path):
        existing = load_existing(path, receipt)
        if existing:
            emit(sync_task(client, path, existing))
            return 0
        metrics = None
        if args.metrics_file:
            metrics = json.loads(Path(args.metrics_file).read_text(encoding='utf-8-sig'))
            if not isinstance(metrics, dict):
                raise ClientError('Remote metrics must be a JSON object.')
        at = stamp()
        if args.task_action == 'start':
            nodes = semantic_nodes(client, path.parent, args.project)
            node = exact_reference(nodes, args.node)
            if node is None:
                try:
                    node = exact_reference(client.project(args.project)['nodes'], args.node)
                except ClientError:
                    pass
            if node:
                receipt['nodeId'] = node['id']
            elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', args.node):
                raise ClientError('Remote task node title was not found; use its retained node ID.')
            run = {'id': receipt['runId'], 'nodeId': receipt['nodeId'], 'title': args.title, 'startedAt': args.started_at,
                   'configuration': {'externalTask': True, 'captureOrigin': 'external-task',
                                     'taskRef': args.task_ref, 'remoteIdentity': args.remote_identity}, 'origin': 'observed'}
        else:
            receipt['runId'] = args.run
            retained_run = execution_reference(client, path.parent, args.project, args.run)
            if retained_run is None:
                try:
                    remote = next((run for run in client.project(args.project)['runs'] if run['id'] == args.run), None)
                    if remote:
                        retained_run = {'id': remote['nodeId']}
                except ClientError:
                    pass
            receipt['nodeId'] = retained_run['id'] if retained_run else None
            run = {'id': args.run}
        if status_value is not None:
            run['status'] = status_value
        if args.finished_at is not None:
            run['finishedAt'] = args.finished_at
        if args.duration_ms is not None:
            run['durationMs'] = args.duration_ms
        if metrics is not None:
            run['metrics'] = metrics
        receipt.update(state='ready', capturedAt=at, status=status_value or 'recorded',
                       operations=[{'op': 'run.add' if args.task_action == 'start' else 'run.update', 'data': run}])
        persist_task(path, receipt)
        emit(sync_task(client, path, receipt))
    return 0


def check(client, project_id):
    p = client.project(project_id)
    errors, warnings = [], []
    for artifact in p['artifacts']:
        if artifact.get('origin') == 'observed':
            try:
                metadata = client.request(client.project_route(project_id) + '/artifacts/' + quote(artifact['id'], safe='') + '/metadata')
                if not metadata.get('verified') or metadata.get('sha256') != artifact['sha256'] or metadata.get('bytes') != artifact['bytes']:
                    errors.append(f'Evidence mismatch: {artifact["id"]}')
            except ClientError as exc:
                errors.append(f'{artifact["id"]}: {exc}')
    for run in p['runs']:
        if run['status'] == 'running':
            warnings.append(f'Run still marked running: {run["id"]}')
        if run.get('origin') == 'observed' and run['status'] in ('completed', 'failed') and not run.get('artifactIds'):
            warnings.append(f'Run has no registered evidence: {run["id"]}')
    emit({'ok': not errors, 'projectId': project_id, 'revision': p['revision'], 'errors': errors, 'warnings': warnings,
          'counts': {key: len(p[key]) for key in ('nodes', 'runs', 'artifacts', 'assessments', 'decisions')}})
    return 1 if errors else 0


def main(argv=None):
    # JSON and evidence text use UTF-8 even when Windows pipes use a legacy code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8-sig' if stream is sys.stdin else 'utf-8',
                               errors='backslashreplace' if stream is sys.stderr else 'strict')
    args = parser().parse_args(argv)
    client = Client(args.url, timeout=2 if args.command in ('init', 'context', 'record', 'event', 'execute', 'sync', 'focus', 'unfocus', 'task') else 30)
    try:
        if args.command != 'status' and not args.no_autostart:
            try:
                from bootstrap import ensure_platform
                startup = ensure_platform(args.url, Path.cwd().resolve(), state_directory())
                if startup.get('state') in ('occupied', 'unavailable'):
                    client.startup_unavailable = 'Local platform startup is unavailable; retain research in the local queue.'
                elif startup.get('state') == 'ready' and args.command in ('init', 'context', 'record', 'event', 'execute', 'sync', 'focus', 'unfocus', 'task'):
                    try:
                        client.request('/api/workspaces', {'path': str(Path.cwd().resolve())})
                    except ClientError:
                        pass  # Directory discovery cannot block the actual research record.
            except (ImportError, OSError, ValueError):
                # Older partial Skill copies still retain local records.
                pass
        if args.command == 'projects':
            result = client.request('/api/projects')
        elif args.command == 'init':
            return init(client, args)
        elif args.command == 'context':
            return context(client, args)
        elif args.command in ('focus', 'unfocus', 'task'):
            return globals()[args.command](client, args)
        elif args.command == 'observe':
            if args.observation_action == 'start':
                observation_id = 'observation-' + (hashlib.sha256(args.request_id.encode()).hexdigest()[:24] if args.request_id else uuid4().hex[:16])
                data = {'id': observation_id, 'nodeId': args.node, 'title': args.title}
            else:
                observation_id = args.id
                data = {'id': observation_id}
                for option, field in (('input_tokens', 'inputTokens'), ('output_tokens', 'outputTokens'), ('usage_source', 'usageSource'), ('usage_ref', 'usageRef')):
                    value = getattr(args, option)
                    if value is not None:
                        data[field] = value
            project = client.apply(args.project, [{'op': 'observation.' + args.observation_action, 'data': data}], request_id=args.request_id)
            observation = next(o for o in project['observations'] if o['id'] == observation_id)
            result = {'projectId': project['id'], 'observationId': observation_id, 'revision': project['revision'],
                      **{field: observation.get(field) for field in ('nodeId', 'status', 'startedAt', 'finishedAt', 'durationMs', 'inputTokens', 'outputTokens', 'usageSource', 'usageRef')}}
        elif args.command == 'apply':
            content = Path(args.file).read_text(encoding='utf-8-sig') if args.file else sys.stdin.read()
            value = json.loads(content)
            body = {'operations': value} if isinstance(value, list) else value
            if not isinstance(body, dict):
                raise ClientError('apply requires an operations array or batch object.')
            if args.expected_revision is not None:
                body['expectedRevision'] = args.expected_revision
            if args.request_id:
                body['requestId'] = args.request_id
            body.setdefault('requestId', 'req-' + uuid4().hex)
            result = client.request(client.project_route(args.project) + '/batch', body)
            # Incremental writes return a small acknowledgement; export is available for the complete graph.
            result = {'projectId': result['id'], 'revision': result['revision'], 'requestId': body['requestId'],
                      'counts': {key: len(result[key]) for key in ('nodes', 'edges', 'runs', 'artifacts', 'assessments', 'decisions')}}
        elif args.command == 'artifact':
            artifacts = [client.request(client.project_route(args.project) + '/artifacts', {'path': str(Path(path).expanduser().resolve()), 'title': args.title,
                                                                                           'nodeId': args.node, 'runId': args.run}) for path in args.path]
            result = artifacts[0] if len(artifacts) == 1 else {'artifacts': artifacts}
        elif args.command == 'export':
            result = client.project(args.project)
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                result = {'projectId': args.project, 'output': str(output), 'revision': result['revision']}
        elif args.command == 'read':
            if args.offset < 0 or not 1 <= args.limit <= 1048576:
                raise ClientError('Read offset must be nonnegative and limit must be 1–1048576 bytes.')
            route = client.project_route(args.project) + '/artifacts/' + quote(args.artifact, safe='') + '/content?'
            content = client.request(route + urlencode({'offset': args.offset, 'limit': args.limit}), raw=True)
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                result = {'projectId': args.project, 'artifactId': args.artifact, 'output': str(output),
                          'offset': args.offset, 'bytes': len(content)}
            else:
                sys.stdout.write(content.decode('utf-8', errors='replace'))
                return 0
        elif args.command == 'check':
            return check(client, args.project)
        elif args.command == 'execute':
            return execute(client, args)
        elif args.command == 'record':
            return record(client, args)
        elif args.command == 'event':
            return event(client, args)
        elif args.command == 'sync':
            return sync(client, args)
        elif args.command == 'status':
            return status(client, args)
        emit(result)
        return 0
    except (ClientError, ValueError, OSError) as exc:
        emit({'error': str(exc)}, sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
