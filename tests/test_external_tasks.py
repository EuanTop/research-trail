"""Explicit remote lifecycle and legacy execution references retain source facts."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from backend.store import Store, StoreError, canonical


class ExternalTaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.apply([{'op': 'node.add', 'data': {'id': 'n', 'status': 'active'}},
                    {'op': 'node.add', 'data': {'id': 'finding'}}])

    def apply(self, operations, **other):
        return self.store.batch('study', {'operations': operations, **other})

    def remote(self, **updates):
        return {'id': 'remote-run', 'nodeId': 'n', 'title': 'Remote training', 'status': 'running',
                'startedAt': '2026-10-29T01:00:00Z', 'origin': 'observed',
                'configuration': {'externalTask': True, 'captureOrigin': 'external-task',
                                  'taskRef': 'job-123', 'remoteIdentity': 'training-host/workspace'}, **updates}

    def test_remote_task_outlives_successful_launcher_and_preserves_original_time(self):
        result = self.apply([{'op': 'run.add', 'data': self.remote()},
                             {'op': 'run.add', 'data': {'id': 'launcher', 'nodeId': 'n', 'status': 'completed'}}])
        self.assertEqual(result['runs'][0]['status'], 'running')
        self.assertEqual(result['nodes'][0]['status'], 'active')
        self.assertIsNone(result['runs'][0]['finishedAt'])
        result = self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', 'status': 'completed',
                               'finishedAt': '2026-10-29T01:10:00Z', 'durationMs': 600000,
                               'metrics': {'loss': .25}}}])
        self.assertEqual(result['runs'][0]['startedAt'], '2026-10-29T01:00:00Z')
        self.assertEqual(result['nodes'][0]['status'], 'active')
        self.assertEqual(result['runs'][0]['metrics'], {'loss': .25})

    def test_invalid_finish_and_identity_changes_rollback(self):
        self.apply([{'op': 'run.add', 'data': self.remote()}])
        before = self.store.get_project('study')
        bad_updates = [
            {'status': 'completed'}, {'status': 'running', 'durationMs': 1},
            {'status': 'failed', 'finishedAt': '2026-10-28T01:00:00Z'},
            {'status': 'completed', 'finishedAt': '2026-10-29T01:10:00Z', 'durationMs': -1},
            {'startedAt': '2026-10-29T01:01:00Z'}, {'nodeId': 'finding'},
            {'configuration': self.remote()['configuration'] | {'taskRef': 'different'}},
            {'configuration': {}},
        ]
        for update in bad_updates:
            with self.subTest(update=update), self.assertRaises(StoreError):
                self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', **update}}])
            self.assertEqual(self.store.get_project('study'), before)
        self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', 'status': 'cancelled',
                                                     'finishedAt': '2026-10-29T01:01:00Z'}}])
        with self.assertRaises(StoreError):
            self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', 'status': 'running', 'finishedAt': None}}])

    def test_missing_original_start_and_identity_are_rejected(self):
        for field in ('startedAt', 'configuration'):
            run = self.remote()
            if field == 'startedAt':
                del run[field]
            else:
                run[field] = {'externalTask': True}
            with self.assertRaises(StoreError):
                self.apply([{'op': 'run.add', 'data': run}])

    def test_reported_duration_and_wall_interval_are_independent_preserved_measurements(self):
        operation = {'op': 'run.add', 'data': self.remote(status='completed',
            finishedAt='2026-10-29T02:00:00Z', durationMs=3600095.0)}
        frozen = copy.deepcopy(operation)
        result = self.apply([operation], requestId='original-executor-report')
        run = result['runs'][0]
        self.assertEqual(run['durationMs'], 3600095.0)
        self.assertEqual(run['finishedAt'], '2026-10-29T02:00:00Z')
        self.assertEqual(operation, frozen)
        self.assertEqual(self.apply([operation], requestId='original-executor-report'), result)
        with self.store._transaction() as db:
            fingerprint = db.execute('SELECT fingerprint FROM versions WHERE project_id=? AND request_id=?',
                                     ('study', 'original-executor-report')).fetchone()[0]
        self.assertEqual(fingerprint, hashlib.sha256(canonical([frozen]).encode()).hexdigest())

    def test_terminal_reported_duration_can_be_corrected_without_restarting_the_job(self):
        original = self.apply([{'op': 'run.add', 'data': self.remote(status='completed',
            finishedAt='2026-10-29T01:10:00Z', durationMs=600000)}])
        update = {'op': 'run.update', 'data': {'id': 'remote-run', 'status': 'completed',
            'finishedAt': '2026-10-29T01:10:00Z', 'durationMs': 600052.0438745576,
            'metrics': {'executorSeconds': 600.0520438745576}}}
        corrected = self.apply([update], requestId='retained-terminal-report')
        self.assertEqual(corrected['runs'][0]['durationMs'], 600052.0438745576)
        self.assertEqual(corrected['runs'][0]['metrics'], {'executorSeconds': 600.0520438745576})
        self.assertEqual(self.apply([update], requestId='retained-terminal-report'), corrected)
        with self.store._transaction() as db:
            retained = self.store._revision(db, 'study', original['revision'])
        self.assertEqual(retained['runs'][0]['durationMs'], 600000)
        for change in ({'status': 'running', 'finishedAt': None},
                       {'finishedAt': '2026-10-29T01:11:00Z'}):
            with self.subTest(change=change), self.assertRaises(StoreError):
                self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', **change}}])

    def test_reported_zero_is_valid_but_invalid_counters_remain_invalid(self):
        self.apply([{'op': 'run.add', 'data': self.remote(status='completed',
            finishedAt='2026-10-29T01:10:00Z', durationMs=0)}])
        self.assertEqual(self.store.get_project('study')['runs'][0]['durationMs'], 0)
        for value in (-1, True, float('nan'), float('inf'), '600000'):
            with self.subTest(value=value), self.assertRaises(StoreError):
                self.apply([{'op': 'run.update', 'data': {'id': 'remote-run', 'durationMs': value}}])

    def test_legacy_run_sources_resolve_all_relations_and_keep_fingerprint(self):
        for index, relation in enumerate(('supports', 'related_to', 'leads_to', 'revises', 'custom.relation')):
            operations = [{'op': 'edge.add', 'data': {'id': f'e{index}', 'source': 'r', 'target': 'finding', 'relation': relation}}]
            if index == 0:
                operations.append({'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'n'}})
            original = copy.deepcopy(operations)
            request = f'frozen-{index}'
            result = self.apply(operations, requestId=request)
            edge = next(edge for edge in result['edges'] if edge['id'] == f'e{index}')
            self.assertEqual(edge['source'], 'n')
            self.assertEqual(edge.get('runIds'), ['r'] if relation == 'supports' else None)
            self.assertEqual(operations, original)
            self.assertEqual(self.apply(operations, requestId=request), result)
            with self.store._transaction() as db:
                fingerprint = db.execute('SELECT fingerprint FROM versions WHERE project_id=? AND request_id=?',
                                         ('study', request)).fetchone()[0]
            self.assertEqual(fingerprint, hashlib.sha256(canonical(original).encode()).hexdigest())

    def test_never_resolve_target_titles_cross_project_or_node_collision(self):
        self.apply([{'op': 'run.add', 'data': {'id': 'r', 'nodeId': 'n', 'title': 'A title'}},
                    {'op': 'node.add', 'data': {'id': 'r'}},
                    {'op': 'run.add', 'data': {'id': 'run-only-target', 'nodeId': 'n'}}])
        result = self.apply([{'op': 'edge.add', 'data': {'id': 'real-node', 'source': 'r', 'target': 'finding', 'relation': 'related_to'}}])
        self.assertEqual(result['edges'][0]['source'], 'r')
        for edge in ({'source': 'A title', 'target': 'finding'}, {'source': 'n', 'target': 'run-only-target'},
                     {'source': 'cross-project-run', 'target': 'finding'}):
            with self.assertRaises(StoreError):
                self.apply([{'op': 'edge.add', 'data': {'id': 'bad', **edge}}])
        self.apply([{'op': 'node.merge', 'data': {'id': 'r', 'target': 'finding'}}])
        aliased = self.apply([{'op': 'edge.add', 'data': {'id': 'merged-source', 'source': 'r', 'target': 'n', 'relation': 'supports'}}])
        merged_edge = next(edge for edge in aliased['edges'] if edge['id'] == 'merged-source')
        self.assertEqual(merged_edge['source'], 'finding')
        self.assertNotIn('runIds', merged_edge)
        self.store.create_project({'id': 'other', 'name': 'Other'})
        with self.assertRaises(StoreError):
            self.store.batch('other', {'operations': [{'op': 'node.add', 'data': {'id': 'other-node'}},
                                {'op': 'edge.add', 'data': {'id': 'cross', 'source': 'r', 'target': 'other-node'}}]})
