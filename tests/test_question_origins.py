"""Question provenance is explicit, portable and independent of containment."""
import copy
from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest

from backend.store import Store, StoreError, canonical


class QuestionOriginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.store.create_project({'id': 'study', 'name': 'Study'})
        self.store.create_project({'id': 'other', 'name': 'Other'})
        self.apply([{'op': 'node.add', 'data': {'id': 'goal', 'kind': 'question'}},
                    {'op': 'node.add', 'data': {'id': 'question', 'kind': 'question', 'parentId': 'goal'}},
                    {'op': 'artifact.add', 'data': {'id': 'paper', 'origin': 'mock'}}])

    def apply(self, operations, **extra):
        return self.store.batch('study', {'operations': operations, **extra})

    def origin(self, value, **extra):
        return self.apply([{'op': 'node.update', 'data': {'id': 'question', 'questionOrigin': value}}], **extra)

    def question(self, project=None):
        return next(node for node in (project or self.store.get_project('study'))['nodes'] if node['id'] == 'question')

    def test_containment_and_relationships_do_not_invent_an_origin(self):
        self.apply([{'op': 'edge.add', 'data': {'source': 'goal', 'target': 'question', 'relation': 'supports'}}])
        self.assertNotIn('questionOrigin', self.question())
        self.assertIsNone(next(node for node in self.store.context('study')['nodes'] if node['id'] == 'question')['questionOrigin'])

    def test_explicit_origin_preserves_custom_data_and_exact_retry_timestamp(self):
        origin = {'type': 'custom.user-trigger', 'nodeIds': ['goal'], 'artifactIds': ['paper'],
                  'reason': 'Review the goal against retained observations.', 'url': 'https://example.org/paper',
                  'retrospective': True, 'custom': {'scope': ['first', None]}}
        operation = {'op': 'node.update', 'data': {'id': 'question', 'questionOrigin': origin}}
        frozen = copy.deepcopy(operation)
        result = self.apply([operation], requestId='origin-declaration')
        retained = self.question(result)['questionOrigin']
        self.assertEqual({key: retained[key] for key in origin}, origin)
        self.assertIsNotNone(datetime.fromisoformat(retained['recordedAt'].replace('Z', '+00:00')).utcoffset())
        self.assertEqual(operation, frozen)
        self.assertEqual(self.apply([operation], requestId='origin-declaration'), result)
        with self.store._transaction() as db:
            fingerprint = db.execute('SELECT fingerprint FROM versions WHERE project_id=? AND request_id=?',
                                     ('study', 'origin-declaration')).fetchone()[0]
        self.assertEqual(fingerprint, hashlib.sha256(canonical([frozen]).encode()).hexdigest())

    def test_frozen_client_time_is_preserved_and_node_ensure_does_not_replace_existing_origin(self):
        original = {'type': 'goal', 'nodeIds': ['goal'], 'recordedAt': '2026-10-01T10:00:00+08:00'}
        self.origin(original)
        self.apply([{'op': 'node.ensure', 'data': {'id': 'question', 'questionOrigin': {'type': 'independent'}}}])
        self.assertEqual(self.question()['questionOrigin'], original)
        created = self.apply([{'op': 'node.ensure', 'data': {'id': 'new', 'questionOrigin': {'type': 'user'}}}])
        self.assertIn('recordedAt', next(node for node in created['nodes'] if node['id'] == 'new')['questionOrigin'])

    def test_independent_and_custom_origins_allow_optional_source_fields(self):
        for value in ({'type': 'independent'}, {'type': 'literature', 'url': 'https://example.org'},
                      {'type': 'user', 'reason': 'The user proposed a new question.'}, {'type': 'custom.hunch'}):
            with self.subTest(value=value):
                self.origin(value)
                self.assertEqual(self.question()['questionOrigin']['type'], value['type'])
        self.origin(None)
        self.assertIsNone(self.question()['questionOrigin'])

    def test_invalid_origin_shapes_reject_atomically(self):
        invalid = [True, [], {}, {'type': ''}, {'type': 'goal', 'nodeIds': 'goal'},
                   {'type': 'goal', 'artifactIds': [None]}, {'type': 'user', 'reason': 1},
                   {'type': 'goal', 'retrospective': 'yes'}, {'type': 'user', 'url': 'javascript:alert(1)'},
                   {'type': 'user', 'url': 'http://'}, {'type': 'user', 'url': 1},
                   {'type': 'goal', 'recordedAt': '2026-11-01T10:00:00'},
                   {'type': 'independent', 'nodeIds': ['goal']}]
        before = self.store.get_project('study')
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(StoreError):
                self.origin(value)
            self.assertEqual(self.store.get_project('study'), before)

    def test_new_references_resolve_aliases_and_never_cross_projects_or_self_reference(self):
        self.apply([{'op': 'node.add', 'data': {'id': 'old-source'}},
                    {'op': 'node.merge', 'data': {'id': 'old-source', 'target': 'goal'}}])
        self.origin({'type': 'goal', 'nodeIds': ['old-source']})
        self.assertEqual(self.question()['questionOrigin']['nodeIds'], ['goal'])
        self.store.batch('other', {'operations': [{'op': 'node.add', 'data': {'id': 'foreign'}}]})
        for value in ({'type': 'goal', 'nodeIds': ['foreign']}, {'type': 'goal', 'nodeIds': ['question']},
                      {'type': 'literature', 'artifactIds': ['absent-paper']}):
            with self.subTest(value=value), self.assertRaises(StoreError):
                self.origin(value)

    def test_source_removal_retains_unresolved_provenance_and_unrelated_edits_work(self):
        self.apply([{'op': 'node.add', 'data': {'id': 'source'}}])
        self.origin({'type': 'finding', 'nodeIds': ['source'], 'artifactIds': ['paper']})
        retained = self.question()['questionOrigin']
        self.apply([{'op': 'node.delete', 'data': {'id': 'source'}}])
        self.assertEqual(self.question()['questionOrigin'], retained)
        self.apply([{'op': 'node.update', 'data': {'id': 'question', 'summary': 'An independent edit'}}])
        self.assertEqual(self.question()['questionOrigin'], retained)
        with self.assertRaises(StoreError):
            self.origin(retained | {'reason': 'A new declaration must resolve its sources.'})
        exported = self.store.get_project('study')
        imported = self.store.import_project(exported)
        self.assertEqual(self.question(imported)['questionOrigin'], retained)

    def test_scoped_context_includes_origin_sources_without_fetching_unrelated_graph(self):
        self.origin({'type': 'goal', 'nodeIds': ['goal'], 'artifactIds': ['paper']})
        context = self.store.context('study', 'question')
        self.assertEqual(context['nodes'][0]['questionOrigin']['nodeIds'], ['goal'])
        self.assertEqual([node['id'] for node in context['boundaryNodes']], ['goal'])
        self.assertEqual([item['id'] for item in context['artifacts']], ['paper'])


if __name__ == '__main__':
    unittest.main()
