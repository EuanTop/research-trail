"""Question provenance survives offline capture; invalid records do not hot-loop."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_capture as capture_fixtures
from tests import test_delivery_status as delivery_fixtures
cli = capture_fixtures.cli
working_directory = capture_fixtures.working_directory


class OriginCliTests(unittest.TestCase):
    setUp = capture_fixtures.CaptureTests.setUp
    invoke = capture_fixtures.CaptureTests.invoke
    offline = capture_fixtures.CaptureTests.offline

    def receipt(self, request_id):
        return next((path, cli.read_queue_task(path)) for path in
                    (self.root / '.exp-observer-runs/outbox').glob('*.json')
                    if cli.read_queue_task(path).get('requestId') == request_id)

    def test_question_origin_is_frozen_with_finding_and_retry_does_not_invent_edges(self):
        args = ('event', '--project', 'study', '--question', 'What explains transfer?',
                '--finding', 'Observed difference', '--origin-type', 'custom.goal-decomposition',
                '--origin-node', 'a', '--origin-reason', 'Compare against the stated goal',
                '--origin-retrospective', '--request-id', 'origin-frozen')
        _, pending = self.invoke(*args, client=self.offline())
        self.assertTrue(pending['pending'])
        path, frozen = self.receipt('origin-frozen')
        origin = next(op['data']['questionOrigin'] for op in frozen['operations'] if op['op'] == 'node.update')
        self.assertEqual(origin['type'], 'custom.goal-decomposition')
        self.assertEqual(origin['nodeIds'], ['a'])
        self.assertTrue(origin['retrospective'])
        self.assertEqual(origin['recordedAt'], frozen['capturedAt'])
        self.assertFalse(any(op.get('data', {}).get('relation') in ('branches', 'motivates') for op in frozen['operations']))
        self.invoke(*args)
        registered = cli.read_queue_task(path)
        self.assertEqual(registered['operations'], frozen['operations'])
        question = next(n for n in self.store.get_project('study')['nodes'] if n['id'] == pending['questionId'])
        self.assertEqual(question['questionOrigin'], origin)
        finding = next(n for n in self.store.get_project('study')['nodes'] if n['id'] == pending['nodeId'])
        self.assertNotIn('questionOrigin', finding)
        self.invoke('event', '--project', 'study', '--question', question['id'], '--finding', 'A later observation')
        self.assertEqual(next(n for n in self.store.get_project('study')['nodes'] if n['id'] == question['id'])['questionOrigin'], origin)

    def test_independent_origin_and_existing_record_edits_preserve_omitted_metadata(self):
        self.invoke('record', '--project', 'study', '--node', 'a', '--origin-type', 'independent',
                    '--origin-reason', 'A new idea worth exploring', '--request-id', 'origin-independent')
        original = self.store.get_project('study')['nodes'][0]['questionOrigin']
        self.invoke('record', '--project', 'study', '--node', 'a', '--summary', 'Updated actual summary')
        self.assertEqual(self.store.get_project('study')['nodes'][0]['questionOrigin'], original)
        with self.assertRaisesRegex(cli.ClientError, 'cannot declare source nodes'):
            self.invoke('event', '--project', 'study', '--question', 'New topic', '--origin-type', 'independent', '--origin-node', 'a')
        with self.assertRaisesRegex(cli.ClientError, '--origin-type'):
            self.invoke('event', '--project', 'study', '--question', 'New topic', '--origin-reason', 'Not enough metadata')
        with self.assertRaisesRegex(cli.ClientError, 'http or https'):
            self.invoke('event', '--project', 'study', '--question', 'New topic', '--origin-type', 'literature', '--origin-url', 'javascript:alert(1)')

    def test_exact_ascii_source_title_resolves_and_missing_natural_title_is_not_a_new_node(self):
        self.store.batch('study', {'operations': [{'op': 'node.update', 'data': {'id': 'a', 'title': 'Benchmark'}}]})
        _, saved = self.invoke('event', '--project', 'study', '--question', 'Does this generalize?',
                               '--origin-type', 'goal', '--origin-node', 'Benchmark')
        origin = next(n for n in self.store.get_project('study')['nodes'] if n['id'] == saved['questionId'])['questionOrigin']
        self.assertEqual(origin['nodeIds'], ['a'])
        before = self.store.get_project('study')
        with self.assertRaisesRegex(cli.ClientError, 'source title was not found'):
            self.invoke('event', '--project', 'study', '--question', 'Unrelated new idea', '--origin-type', 'finding', '--origin-node', 'Missing source title')
        self.assertEqual(self.store.get_project('study'), before)

    def test_context_exposes_frozen_origin_and_legacy_intents_stay_unchanged(self):
        _, result = self.invoke('event', '--project', 'study', '--question', 'Why this problem?', '--reason', 'User asked for it',
                                '--origin-type', 'user', '--request-id', 'origin-context', client=self.offline())
        with working_directory(self.root):
            _, _, _, nodes = cli.local_context(self.root / '.exp-observer-runs/outbox', self.offline(), 'study', result['questionId'])
        self.assertEqual(nodes[0]['questionOrigin']['reason'], 'User asked for it')
        self.invoke('record', '--project', 'study', '--title', 'Legacy recording', '--request-id', 'without-origin', client=self.offline())
        _, task = self.receipt('without-origin')
        self.assertFalse(any(key.startswith('origin_') for key in task['intent']))
        self.assertFalse(any('questionOrigin' in op['data'] for op in task['operations']))

    def test_missing_origin_id_waits_without_creating_a_source_node(self):
        _, result = self.invoke('event', '--project', 'study', '--question', 'A source-dependent question?',
                                '--origin-type', 'goal', '--origin-node', 'node-retained-source',
                                '--request-id', 'origin-unresolved', client=self.offline())
        path, task = self.receipt('origin-unresolved')
        self.assertTrue(result['pending'])
        self.assertFalse(any(operation['data'].get('id') == 'node-retained-source'
                             for operation in task['operations']))
        origin = task['operations'][0]['data']['questionOrigin']
        self.assertEqual(origin['nodeIds'], ['node-retained-source'])
        self.invoke('event', '--project', 'study', '--question', 'A source-dependent question?',
                    '--origin-type', 'goal', '--origin-node', 'node-retained-source', '--request-id', 'origin-unresolved')
        self.assertEqual(cli.read_queue_task(path)['delivery']['lastError']['code'], 'invalid_reference')
        self.assertFalse(any(node['id'] == 'node-retained-source' for node in self.store.get_project('study')['nodes']))


class RecoveryDependencyTests(unittest.TestCase):
    setUp = delivery_fixtures.DeliveryStatusTests.setUp
    capture = delivery_fixtures.DeliveryStatusTests.capture
    new_recovery = delivery_fixtures.DeliveryStatusTests.new_recovery

    def test_run_ids_and_retained_artifacts_are_dependencies(self):
        producer = {'url': self.url, 'projectId': 'study', 'state': 'ready',
                    'operations': [{'op': 'run.add', 'data': {'id': 'run-source', 'nodeId': 'existing'}}],
                    'artifacts': [{'id': 'artifact-source'}]}
        dependent = {'url': self.url, 'projectId': 'study', 'state': 'ready', 'operations': [
            {'op': 'edge.add', 'data': {'source': 'existing', 'target': 'other', 'runIds': ['run-source']}},
            {'op': 'node.update', 'data': {'id': 'other', 'questionOrigin': {'type': 'literature', 'artifactIds': ['artifact-source']}}}]}
        first, second = self.workspace/'first.json', self.workspace/'second.json'
        items = [(second, self.workspace, dependent), (first, self.workspace, producer)]
        self.assertEqual(cli.queue_dependency_map(items)[second], {first})
        self.assertEqual([item[0] for item in cli.queue_delivery_order(items)], [first, second])
        self.assertEqual(dependent['operations'][0]['data']['runIds'], ['run-source'])

    def test_deterministic_failure_stops_background_retries_but_manual_retry_works(self):
        path, _ = self.capture('record', '--project', 'study', '--title', 'A preserved finding')
        original = copy.deepcopy(cli.read_queue_task(path))
        task = cli.read_queue_task(path)
        cli.delivery_attempt(path, task)
        cli.delivery_failed(path, task, cli.ClientError('Bad duration semantics', code='invalid_external_task'), [])
        failed = cli.read_queue_task(path)
        self.assertFalse(failed['delivery']['retryable'])
        self.assertIsNone(failed['delivery']['nextAttemptAt'])
        for _ in range(3):
            self.recovery.drain_once()
        self.assertEqual(cli.read_queue_task(path)['delivery']['attempts'], failed['delivery']['attempts'])
        status = self.recovery.delivery_status('study')
        item = next(item for item in status['items'] if item['taskId'] == task['taskId'])
        self.assertFalse(item['retryable'])
        self.recovery.retry_delivery('study', task['taskId'])
        healed = cli.read_queue_task(path)
        self.assertEqual(healed['state'], 'synced')
        self.assertEqual(healed['operations'], original['operations'])
        self.assertTrue(healed['delivery']['retryable'])

    def test_manual_retry_delivers_referenced_run_producer_first(self):
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'node-existing', 'title': 'Existing research question'}}]})
        metrics = self.workspace / 'measured.json'
        metrics.write_text('{"accuracy": 0.9}', encoding='utf-8')
        producer_path, producer = self.capture('record', '--project', 'study', '--node', 'node-existing',
                                               '--title', 'Measured run', '--metrics-file', str(metrics))
        dependent_path, dependent = self.capture('record', '--project', 'study', '--title', 'Evidence-based result',
                                                 '--after', producer['runId'], '--relation', 'supports')
        task = cli.read_queue_task(dependent_path)
        # The referenced source node already exists; only run provenance requires this producer.
        deps = cli.queue_dependency_map([(producer_path, self.workspace, cli.read_queue_task(producer_path)),
                                         (dependent_path, self.workspace, task)])
        self.assertEqual(deps[dependent_path], {producer_path})
        status = self.recovery.delivery_status('study')
        waiting = next(item for item in status['items'] if item['taskId'] == task['taskId'])['waitingFor']
        self.assertEqual(waiting[0]['title'], 'Measured run')
        with patch.object(self.recovery, '_submit', wraps=self.recovery._submit) as submit:
            result = self.recovery.retry_delivery('study', task['taskId'])
        self.assertEqual([call.args[0][0] for call in submit.call_args_list], [producer_path, dependent_path])
        self.assertEqual(result['retriedCount'], 2)
        self.assertEqual(cli.read_queue_task(dependent_path)['state'], 'synced')
        edge = next(edge for edge in self.store.get_project('study')['edges'] if edge['target'] == dependent['nodeId'])
        self.assertEqual(edge['runIds'], [producer['runId']])

    def test_readable_node_title_is_kept_for_a_run_update_receipt(self):
        _, created = self.capture('record', '--project', 'study', '--title', 'An actual research question')
        path, _ = self.capture('record', '--project', 'study', '--node', created['nodeId'], '--summary', 'New progress')
        status = self.recovery.delivery_status('study')
        titles = [item['title'] for item in status['items'] if item['nodeId'] == created['nodeId']]
        self.assertEqual(titles, ['An actual research question', 'An actual research question'])
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'node-cached', 'title': 'A previously synchronized question'}}]})
        self.capture('record', '--project', 'study', '--node', 'node-cached', '--summary', 'Only updated progress')
        item = next(item for item in self.recovery.delivery_status('study')['items'] if item['nodeId'] == 'node-cached')
        self.assertEqual(item['title'], 'A previously synchronized question')


if __name__ == '__main__':
    unittest.main()
