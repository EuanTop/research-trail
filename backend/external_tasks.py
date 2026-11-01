"""Validation for explicitly reported remote jobs; never executes or polls them."""
from __future__ import annotations

import math
from datetime import datetime
from .store import StoreError

TERMINAL = {'completed', 'failed', 'cancelled'}
STATUSES = TERMINAL | {'queued', 'running', 'paused'}
IDENTITY_FIELDS = ('captureOrigin', 'taskRef', 'remoteIdentity')


def external(run):
    return isinstance(run.get('configuration'), dict) and run['configuration'].get('externalTask') is True


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError('Timezone required')
        return result
    except (AttributeError, TypeError, ValueError) as exc:
        raise StoreError('External task times must be ISO timestamps with a timezone.', 'invalid_external_task') from exc


def validate(run):
    if not external(run):
        return
    config = run['configuration']
    if config.get('captureOrigin') != 'external-task' or any(
            not isinstance(config.get(key), str) or not config[key].strip() or len(config[key]) > 1000
            for key in IDENTITY_FIELDS):
        raise StoreError('External tasks require captureOrigin, taskRef and remoteIdentity.', 'invalid_external_task')
    if run.get('origin') != 'observed' or run.get('status') not in STATUSES:
        raise StoreError('External tasks require observed origin and an explicit lifecycle status.', 'invalid_external_task')
    started = _time(run.get('startedAt'))
    finished = run.get('finishedAt')
    duration = run.get('durationMs')
    if run['status'] in TERMINAL:
        elapsed = (_time(finished) - started).total_seconds() * 1000
        if elapsed < 0:
            raise StoreError('External task finish must not precede its start.', 'invalid_external_task')
        # The executor may measure duration with a monotonic timer while these
        # timestamps use a wall clock. Preserve both measurements: drift or
        # timestamp precision is not evidence that the reported work is invalid.
        if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0):
            raise StoreError('External task reported duration must be a finite nonnegative number.', 'invalid_external_task')
    elif finished is not None or duration is not None:
        raise StoreError('An unfinished external task cannot have a finish time or duration.', 'invalid_external_task')


def validate_update(existing, update):
    if not external(existing):
        return
    proposed = existing | update
    if not external(proposed) or proposed.get('startedAt') != existing.get('startedAt') or proposed.get('nodeId') != existing.get('nodeId'):
        raise StoreError('External task identity, owner and original start time are immutable.', 'external_task_conflict', 409)
    before, after = existing['configuration'], proposed['configuration']
    if any(before.get(key) != after.get(key) for key in IDENTITY_FIELDS):
        raise StoreError('External task remote identity is immutable.', 'external_task_conflict', 409)
    # Reported duration is a measurement which may be enriched or corrected,
    # just like metrics; the normal revision history retains its previous value.
    if existing['status'] in TERMINAL and any(proposed.get(key) != existing.get(key) for key in ('status', 'finishedAt')):
        raise StoreError('A finished external task cannot be restarted; record a new task.', 'external_task_conflict', 409)
