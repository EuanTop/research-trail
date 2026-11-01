"""Recover registered local capture queues without executing research commands."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from collections import defaultdict, deque
import stat
import threading
import time

SKIP_DIRECTORIES = {'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '__pycache__', '.mypy_cache',
                    '.pytest_cache', '.cache', '.tox', '.nox', '.next', '.nuxt', '.turbo', 'dist', 'build',
                    'target', 'vendor', 'site-packages', 'coverage', '.exp-observer', '.exp-observer-runs'}


def scoped_path(path, root, allow_missing=False):
    """Check components without following a child symlink or Windows junction."""
    path, root = Path(path), Path(root)
    if not path.is_absolute():
        return False
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        return False
    try:
        if root.resolve() != root:
            return False
        current = root
        for part in (None, *path.relative_to(root).parts):
            if part is not None:
                current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return allow_missing
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def capture_lock_held(path):
    """Probe an existing executor lock without creating files or changing records."""
    try:
        with path.open('r+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if not stream.tell():
                    return False
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return True
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    return False


class WorkspaceDiscovery:
    """Budget root/experiment change probes without losing ordinary tree progress."""
    def __init__(self, root, rescan_interval):
        self.root = root
        self.rescan_interval = rescan_interval
        self.queue = deque([root])
        self.cursor = None
        self.priority_cursor = None
        self.priority_directory = None
        self.priority_queue = deque()
        self.priority_pending = set()
        self.priority_dirty = set()
        self.priority_turn = False
        self.watched = deque()
        self.directory_mtimes = {}
        self.watch_turn = 0
        self.root_mtime = None
        self.root_dirty = False
        self.next_scan = 0
        self.outboxes = set()

    def probe(self, directory, *, watch=False):
        outbox = directory / '.exp-observer-runs' / 'outbox'
        found = scoped_path(outbox, self.root) and outbox.is_dir()
        new_outbox = found and outbox not in self.outboxes
        if found:
            self.outboxes.add(outbox)
        if directory != self.root and (watch or found) and directory not in self.directory_mtimes:
            try:
                if not scoped_path(directory, self.root):
                    return
                self.directory_mtimes[directory] = directory.stat().st_mtime_ns
            except OSError:
                return
            self.watched.append(directory)
        if new_outbox and directory != self.root:
            # Children may already exist when this owner is first discovered.
            self._prioritize(directory)

    def _prioritize(self, directory):
        if directory in self.priority_pending:
            self.priority_dirty.add(directory)
        else:
            self.priority_pending.add(directory)
            self.priority_queue.append(directory)

    def _watch_directory(self):
        directory = self.watched.popleft()
        try:
            if not scoped_path(directory, self.root):
                raise FileNotFoundError
            modified = directory.stat().st_mtime_ns
        except OSError:
            self.directory_mtimes.pop(directory, None)
            return True
        if modified != self.directory_mtimes[directory]:
            known_outbox = directory / '.exp-observer-runs' / 'outbox' in self.outboxes
            self.directory_mtimes[directory] = modified
            self.probe(directory)
            if known_outbox:
                self._prioritize(directory)
        self.watched.append(directory)
        return True

    def refresh_root(self):
        try:
            if not scoped_path(self.root, self.root):
                return
            modified = self.root.stat().st_mtime_ns
        except OSError:
            return
        if modified != self.root_mtime:
            self.root_dirty = True
        self.root_mtime = modified

    def _child(self, entry):
        if entry.name.lower() not in SKIP_DIRECTORIES and entry.is_dir(follow_symlinks=False):
            info = entry.stat(follow_symlinks=False)
            if not getattr(info, 'st_file_attributes', 0) & 0x400:
                return Path(entry.path)
        return None

    def step(self):
        if self.root_dirty:
            self.root_dirty = False
            self._prioritize(self.root)
        self.watch_turn = (self.watch_turn + 1) % 4
        if self.watched and self.watch_turn == 0:
            return self._watch_directory()
        if self.priority_cursor is None and self.priority_queue:
            directory = self.priority_queue.popleft()
            if scoped_path(directory, self.root):
                try:
                    self.priority_cursor = os.scandir(directory)
                    self.priority_directory = directory
                    self.priority_turn = False
                except OSError:
                    pass
            if self.priority_cursor is None:
                self.priority_pending.discard(directory)
                self.priority_dirty.discard(directory)
            return True  # Opening a priority scan consumes the same budget as a tree scan.
        if self.priority_cursor is not None and self.priority_turn:
            self.priority_turn = False
            return self._priority_step()
        self.priority_turn = True
        progressed = self._tree_step()
        if not progressed and self.priority_cursor is not None:
            self.priority_turn = False
            return self._priority_step()
        # Keep spending the fixed budget on watch rotation even when the tree
        # is idle; otherwise the first idle step would defer all remaining watches.
        return progressed or bool(self.watched)

    def _priority_step(self):
        try:
            directory = self._child(next(self.priority_cursor))
            if directory is not None:
                self.probe(directory, watch=True)
        except (StopIteration, OSError):
            self.priority_cursor.close()
            self.priority_cursor = None
            directory, self.priority_directory = self.priority_directory, None
            self.priority_pending.discard(directory)
            if directory in self.priority_dirty:
                self.priority_dirty.discard(directory)
                self._prioritize(directory)
        return True

    def _tree_step(self):
        if self.cursor is None:
            if not self.queue:
                if time.monotonic() < self.next_scan:
                    return False
                self.queue.append(self.root)
            directory = self.queue.popleft()
            if not scoped_path(directory, self.root):
                return True
            self.probe(directory, watch=directory.parent == self.root)
            try:
                self.cursor = os.scandir(directory)
            except OSError:
                return True
            return True
        try:
            directory = self._child(next(self.cursor))
            if directory is not None:
                self.queue.append(directory)
        except StopIteration:
            self.cursor.close()
            self.cursor = None
            if not self.queue:
                self.next_scan = time.monotonic() + self.rescan_interval
        except OSError:
            pass
        return True

    def close(self):
        if self.cursor is not None:
            self.cursor.close()
            self.cursor = None
        if self.priority_cursor is not None:
            self.priority_cursor.close()
            self.priority_cursor = None


def load_client():
    # Load the application's own portable client, never a script from a registry entry.
    path = Path(__file__).resolve().parents[1] / 'skills' / 'exp-observer' / 'scripts' / 'exp_observer.py'
    spec = importlib.util.spec_from_file_location('_exp_observer_recovery_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recovery:
    def __init__(self, url, state_dir=None, interval=2, *, store=None, discovery_budget=128, discovery_interval=None):
        self.cli = load_client()
        self.url = url.rstrip('/')
        self.origin = self.cli.loopback_origin(self.url)
        try:
            self.state_dir = Path(state_dir) if state_dir is not None else self.cli.state_directory()
        except (OSError, ValueError, RuntimeError):
            self.state_dir = None
        self.store = store
        self.interval = interval
        self.discovery_budget = discovery_budget
        self.discovery_interval = discovery_interval if discovery_interval is not None else max(interval * 5, 0.2)
        self.discovery = {}
        self.discovery_cursor = 0
        self.stopped = threading.Event()
        self.thread = None
        self.last_results = []
        self.acknowledged = {}
        self.project_plans = {}
        self.runtime_candidates = (0, ())
        self.delivery_lock = threading.Lock()
        self.discovery_lock = threading.RLock()
        from .host_usage import HostUsageImporter
        self.host_usage = HostUsageImporter(store, url=self.url) if store is not None else None

    def _targets(self, results):
        with self.discovery_lock:
            return self._scan_targets(results)

    def _scan_targets(self, results):
        targets, active, disabled = {}, [], []
        if self.store is not None:
            try:
                configuration = self.store.recovery_workspaces()
                active = [Path(entry['path']) for entry in configuration['workspaces']]
                disabled = [Path(root) for root in configuration['disabledRoots']]
            except Exception as exc:
                results.append({'pending': True, 'recordingWarnings': [str(exc)]})
        for root in set(self.discovery) - set(active):
            self.discovery.pop(root).close()
        for root in active:
            scanner = self.discovery.setdefault(root, WorkspaceDiscovery(root, self.discovery_interval))
            scanner.refresh_root()
            scanner.probe(root)  # A root init plan must be visible before any descendant's implicit plan.
        scanners = list(self.discovery.values())
        idle = 0
        for _ in range(self.discovery_budget):
            if not scanners or self.stopped.is_set():
                break
            scanner = scanners[self.discovery_cursor % len(scanners)]
            self.discovery_cursor += 1
            idle = 0 if scanner.step() else idle + 1
            if idle >= len(scanners):
                break
        for scanner in scanners:
            for outbox in list(scanner.outboxes):
                if scoped_path(outbox, scanner.root) and outbox.is_dir():
                    previous = targets.get(outbox)
                    targets[outbox] = scanner.root if previous is None else min((previous, scanner.root), key=lambda path: len(path.parts))
                else:
                    scanner.outboxes.discard(outbox)
        registrations = []
        if self.state_dir is not None:
            try:
                registrations = sorted((self.state_dir / 'outboxes').glob('*.json'))
            except OSError as exc:
                results.append({'pending': True, 'recordingWarnings': [str(exc)]})
        for registration in registrations:
            try:
                if registration.is_symlink():
                    continue
                entry = json.loads(registration.read_text(encoding='utf-8'))
                if not isinstance(entry, dict):
                    raise ValueError('Recovery registration must be an object.')
                if entry.get('version') != 1 or self.cli.loopback_origin(entry['url']) != self.origin:
                    continue
                outbox = Path(entry['outbox'])
                covered = [root for root in active if outbox.is_relative_to(root)]
                if not covered and any(outbox.is_relative_to(root) for root in disabled):
                    continue
                root = min(covered, key=lambda path: len(path.parts)) if covered else outbox.parent.parent
                if scoped_path(outbox, root) and outbox.is_dir():
                    targets.setdefault(outbox, root)
                    # Legacy registrations can reveal a child before its ancestor
                    # has been visited by incremental discovery. Probe only that chain.
                    if covered:
                        owner = outbox.parent.parent
                        for directory in (owner, *owner.parents):
                            if not directory.is_relative_to(root):
                                break
                            ancestor = directory / '.exp-observer-runs' / 'outbox'
                            if scoped_path(ancestor, root) and ancestor.is_dir():
                                targets.setdefault(ancestor, root)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                results.append({'registryEntry': registration.name, 'pending': True, 'recordingWarnings': [str(exc)]})
        return targets

    def _read_candidates(self, targets, results):
        candidates, seen = [], set()
        for outbox, root in sorted(targets.items(), key=lambda item: (len(item[0].parts), str(item[0]))):
            try:
                paths = outbox.glob('*.json')
                for path in paths:
                    if self.stopped.is_set():
                        break
                    try:
                        info = path.lstat()
                        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                            continue
                        seen.add(str(path))
                        signature = (info.st_mtime_ns, info.st_size, info.st_ino)
                        if self.acknowledged.get(str(path)) == signature:
                            continue
                        if not scoped_path(path, root):
                            continue
                        self.project_plans.pop(str(path), None)
                        task = self.cli.read_queue_task(path)
                        if self.cli.loopback_origin(task['url']) != self.origin:
                            continue
                        item = (path, root, task)
                        if task.get('kind') == 'project':
                            self.project_plans[str(path)] = item
                        if task['state'] == 'synced':
                            self.acknowledged[str(path)] = signature
                        else:
                            delivery = task.get('delivery') if isinstance(task.get('delivery'), dict) else {}
                            if task['state'] == 'ready' and delivery.get('retryable') is False:
                                continue
                            after = self.cli.local_timestamp(delivery.get('nextAttemptAt'))
                            if task['state'] == 'ready' and after is not None and after > time.time():
                                continue
                            candidates.append(item)
                    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                        results.append({'task': path.name, 'pending': True, 'recordingWarnings': [str(exc)]})
            except OSError as exc:
                results.append({'outbox': str(outbox), 'pending': True, 'recordingWarnings': [str(exc)]})
        for key in set(self.project_plans) - seen:
            self.project_plans.pop(key, None)
        return candidates

    def _validate_capture(self, path, root, task):
        if task.get('kind') in ('project', 'focus'):
            return
        capture = Path(task['captureRoot'])
        if not capture.is_relative_to(path.parent.parent) or not scoped_path(capture, root, allow_missing=True):
            raise ValueError('Capture directory is outside the enrolled or registered outbox scope.')
        plan_path = self.cli.project_plan_path(path.parent, task['url'], task['projectId'])
        if not all(scoped_path(candidate, root, allow_missing=True) for candidate in (plan_path, plan_path.with_suffix('.lock'))):
            raise ValueError('Project plan follows a symlink or leaves the workspace scope.')
        for artifact in task['artifacts']:
            evidence = Path(artifact['path'])
            if not evidence.is_relative_to(capture) or not scoped_path(evidence, root, allow_missing=True):
                raise ValueError('Staged evidence follows a symlink or leaves the workspace scope.')

    def _submit(self, item):
        path, root, previous = item
        try:
            if not scoped_path(path, root) or not scoped_path(path.with_suffix('.lock'), root, allow_missing=True):
                raise ValueError('Queued record follows a symlink or leaves the workspace scope.')
            with self.cli.task_lock(path):
                task = self.cli.read_queue_task(path)
                if (self.cli.loopback_origin(task['url']) != self.origin or task['projectId'] != previous['projectId']
                        or any(task.get(key) != previous.get(key) for key in ('kind', 'taskId', 'requestId'))):
                    raise ValueError('Queued record identity changed while recovery was processing it.')
                try:
                    self._validate_capture(path, root, task)
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    warnings = [str(exc)]
                    if task['state'] == 'ready':
                        # Only the scoped receipt is mutable. Unsafe evidence is
                        # never opened, rewritten or imported by this recovery.
                        self.cli.delivery_attempt(path, task)
                        self.cli.delivery_failed(path, task, exc, warnings)
                    return {'task': path.name, 'projectId': task['projectId'], 'pending': True,
                            'recordingWarnings': warnings}
                client = self.cli.Client(task['url'], timeout=5, transport_url=self.url, local_only=True, queue_root=root)
                # The application already resolves authoritative parent plans. The
                # standalone client's optional ancestor lookup must stay in this scope.
                result = self.cli.sync_project(client, path, task) if task.get('kind') == 'project' else self.cli.sync_task(client, path, task)
                if not result['pending']:
                    self.acknowledged[str(path)] = self.cli.file_signature(path)
                    if task.get('kind') == 'project':
                        self.project_plans[str(path)] = (path, root, task)
                return result
        except (self.cli.ClientError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return {'task': path.name, 'projectId': previous['projectId'], 'pending': True, 'recordingWarnings': [str(exc)]}

    def _authoritative_plan(self, project_id):
        plans = [item for item in self.project_plans.values() if item[2]['projectId'] == project_id]
        explicit = [item for item in plans if not item[2].get('implicit')]
        plans = explicit or plans
        ancestors = [item for item in plans if not any(other[0].parent.parent.parent != item[0].parent.parent.parent
            and item[0].parent.parent.parent.is_relative_to(other[0].parent.parent.parent) for other in plans)]
        return min(ancestors, key=lambda item: (item[2].get('preparedAt', ''), str(item[0]))) if ancestors else None

    def drain_once(self):
        with self.delivery_lock:
            return self._drain_once()

    def _drain_once(self):
        results = []
        if self.origin is None:
            return results
        targets = self._targets(results)
        candidates = self._read_candidates(targets, results)
        # A candidate is only a location hint. Runtime reads recheck the current
        # record and OS lock; a crashed executor's stale `running` is not liveness.
        self.runtime_candidates = (time.monotonic(), tuple(
            item for item in candidates if item[2].get('state') == 'running'
            and item[2].get('intent', {}).get('command') == 'execute'))
        groups = defaultdict(list)
        for item in candidates:
            groups[item[2]['projectId']].append(item)
        for project_id, items in groups.items():
            if self.stopped.is_set():
                break
            authoritative = self._authoritative_plan(project_id)
            if authoritative is not None:
                result = self._submit(authoritative)
                results.append(result)
                if result['pending']:
                    continue
            for item in self.cli.queue_delivery_order(items):
                if self.stopped.is_set():
                    break
                if authoritative is not None and item[0] == authoritative[0]:
                    continue
                results.append(self._submit(item))
        if self.host_usage is not None and not self.stopped.is_set():
            results.extend(self.host_usage.drain_once(targets))
        self.last_results = results
        return results

    def _delivery_receipts(self, project_id):
        warnings = []
        with self.discovery_lock:
            targets = self._targets(warnings)
            complete = all(not scanner.queue and scanner.cursor is None
                and scanner.priority_cursor is None and not scanner.priority_queue
                for scanner in self.discovery.values())
        receipts = []
        for outbox, root in sorted(targets.items(), key=lambda item: str(item[0])):
            try:
                for path in outbox.glob('*.json'):
                    if not scoped_path(path, root) or not path.is_file():
                        continue
                    try:
                        task = self.cli.read_queue_task(path)
                        if task['projectId'] == project_id and self.cli.loopback_origin(task['url']) == self.origin:
                            receipts.append((path, root, task))
                    except (OSError, ValueError, KeyError, TypeError):
                        # An unreadable receipt cannot establish complete delivery.
                        warnings.append(True)
            except OSError:
                warnings.append(True)
        return receipts, bool(targets), complete and not warnings

    def delivery_status(self, project_id):
        """Read durable receipts; never acknowledge, repair or submit from a GET."""
        result = {'projectId': project_id, 'available': False, 'checkedAt': self.cli.stamp(),
                  'state': 'unknown', 'scope': 'connected-workspaces', 'discoveryComplete': False,
                  'pendingCount': 0, 'blockedCount': 0, 'interruptedCount': 0, 'syncedCount': 0, 'items': []}
        if self.origin is None or self.stopped.is_set():
            return result
        receipts, available, complete = self._delivery_receipts(project_id)
        result.update(available=available, discoveryComplete=complete)
        dependencies = self.cli.queue_dependency_map(receipts)
        by_path = {item[0]: item[2] for item in receipts}
        node_titles = {}
        if self.store is not None:
            from .store import StoreError
            try:
                node_titles.update({node['id']: node['title'] for node in self.store.get_project(project_id)['nodes']
                                    if isinstance(node.get('title'), str) and node['title'].strip()})
            except (StoreError, OSError, KeyError, TypeError):
                pass
        def receipt_operations(receipt):
            operations = receipt.get('operations')
            return [operation for operation in operations
                    if isinstance(operation, dict) and isinstance(operation.get('data'), dict)] if isinstance(operations, list) else []
        for _, _, receipt in sorted(receipts, key=lambda item: item[2].get('capturedAt') or ''):
            for operation in receipt_operations(receipt):
                data = operation['data']
                if operation.get('op') in ('node.add', 'node.ensure', 'node.update') and isinstance(data.get('title'), str) and data['title'].strip():
                    node_titles[data.get('id')] = data['title']
        def readable_title(receipt):
            intent = receipt.get('intent') if isinstance(receipt.get('intent'), dict) else {}
            metadata = receipt.get('project') if isinstance(receipt.get('project'), dict) else {}
            node_id = receipt.get('questionId') or receipt.get('nodeId')
            values = [intent.get(key) for key in ('title', 'finding', 'correction', 'direction')]
            values.extend((node_titles.get(node_id), metadata.get('name')))
            question = intent.get('question')
            if isinstance(question, str) and question not in (node_id, receipt.get('nodeId')):
                values.append(question)
            values.extend(operation['data'].get('title') for operation in receipt_operations(receipt)
                          if operation.get('op') == 'run.add')
            return next((value for value in values if isinstance(value, str) and value.strip()), 'Research record')
        for path, root, task in receipts:
            if task['state'] == 'synced':
                result['syncedCount'] += 1
                continue
            delivery = task.get('delivery') if isinstance(task.get('delivery'), dict) else {}
            error = delivery.get('lastError')
            error = ({'code': str(error.get('code') or 'delivery_failed')[:128],
                      'message': str(error.get('message') or '')[:4096]}
                     if isinstance(error, dict) else None)
            lock = path.with_suffix('.lock')
            live = scoped_path(lock, root) and capture_lock_held(lock)
            state = ('pending' if live else 'interrupted') if task['state'] != 'ready' else ('blocked' if error else 'pending')
            attempts = delivery.get('attempts', 0)
            title = readable_title(task)
            result[state + 'Count'] += 1
            result['items'].append({'taskId': task.get('taskId') if isinstance(task.get('taskId'), str) and task['taskId'] else path.stem,
                'requestId': task.get('requestId') if isinstance(task.get('requestId'), str) else None,
                'nodeId': task.get('nodeId') if isinstance(task.get('nodeId'), str) else None,
                'title': title[:500],
                'state': state, 'attempts': attempts if isinstance(attempts, int) and attempts >= 0 else 0,
                'lastAttemptAt': delivery.get('lastAttemptAt') if isinstance(delivery.get('lastAttemptAt'), str) else None,
                'lastError': error,
                'nextAttemptAt': delivery.get('nextAttemptAt'),
                'retryable': delivery.get('retryable'),
                'waitingFor': [{'taskId': by_path[dependency].get('taskId', dependency.stem),
                                'nodeId': by_path[dependency].get('nodeId'),
                                'title': readable_title(by_path[dependency])}
                               for dependency in sorted(dependencies.get(path, ())) if by_path[dependency]['state'] != 'synced']})
        if result['blockedCount'] or result['interruptedCount']:
            result['state'] = 'blocked'
        elif result['pendingCount']:
            result['state'] = 'pending'
        elif receipts and complete:
            result['state'] = 'synced'
        return result

    def retry_delivery(self, project_id, task_id=None):
        """Resubmit frozen records only; executable intent is never run here."""
        from .store import StoreError
        if self.origin is None or self.stopped.is_set():
            raise StoreError('Queue recovery is unavailable.', 'recovery_unavailable', 409)
        if not self.delivery_lock.acquire(blocking=False):
            raise StoreError('Queue recovery is already processing records. Try again shortly.', 'recovery_busy', 409)
        try:
            receipts, _, _ = self._delivery_receipts(project_id)
            known = [item for item in receipts if task_id is None or (item[2].get('taskId') or item[0].stem) == task_id]
            if task_id is not None and not known:
                raise StoreError('Queued record was not found in connected workspaces.', 'not_found', 404)
            dependencies = self.cli.queue_dependency_map(receipts)
            selected = {item[0] for item in known}
            pending = list(selected)
            while pending:
                for dependency in dependencies.get(pending.pop(), ()):
                    if dependency not in selected:
                        selected.add(dependency)
                        pending.append(dependency)
            known = [item for item in receipts if item[0] in selected]
            results = []
            for item in self.cli.queue_delivery_order(known):
                path, root, task = item
                lock = path.with_suffix('.lock')
                if task['state'] != 'ready' or (scoped_path(lock, root) and capture_lock_held(lock)):
                    continue
                results.append(self._submit(item))
            return {'retriedCount': len(results), 'deliveryStatus': self.delivery_status(project_id)}
        finally:
            self.delivery_lock.release()

    def runtime(self, project_id):
        checked_at, candidates = self.runtime_candidates
        active = []
        result = {'projectId': project_id, 'checkedAt': self.cli.stamp(),
                  'source': 'connected_local_executors', 'active': active}
        if self.stopped.is_set() or time.monotonic() - checked_at > max(10, self.interval * 3):
            return result
        configuration = self.store.recovery_workspaces() if self.store is not None else None
        for path, root, previous in candidates:
            if previous.get('projectId') != project_id:
                continue
            if configuration is not None:
                covered = any(path.is_relative_to(Path(entry['path'])) for entry in configuration['workspaces'])
                if not covered and any(path.is_relative_to(Path(disabled)) for disabled in configuration['disabledRoots']):
                    continue
            lock = path.with_suffix('.lock')
            if not scoped_path(path, root) or not scoped_path(lock, root) or not capture_lock_held(lock):
                continue
            try:
                task = self.cli.read_queue_task(path)
                if (task['state'] != 'running' or task['projectId'] != project_id
                        or self.cli.loopback_origin(task['url']) != self.origin
                        or task.get('intent', {}).get('command') != 'execute'
                        or not isinstance(task.get('nodeId'), str)):
                    continue
                active.append({'id': task['taskId'], 'nodeId': task['nodeId'], 'source': 'local-executor'})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result

    def _run(self):
        try:
            while not self.stopped.is_set():
                try:
                    self.drain_once()
                except Exception as exc:
                    self.last_results = [{'pending': True, 'recordingWarnings': [str(exc)]}]
                self.stopped.wait(self.interval)
        finally:
            for scanner in self.discovery.values():
                scanner.close()

    def start(self):
        if self.origin is not None and self.thread is None:
            self.thread = threading.Thread(target=self._run, name='ExpObserver recovery', daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        elif self.thread is None:
            for scanner in self.discovery.values():
                scanner.close()
