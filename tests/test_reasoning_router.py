import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'execution'))
import reasoning_router as r


ALL_ZERO = {name: 0 for name in r.DIMENSIONS}


class ReasoningTests(unittest.TestCase):
    def test_complete_score_boundaries_and_unknown(self):
        cases = [
            ({**ALL_ZERO, 'scope': 2}, 'low'),
            ({**ALL_ZERO, 'scope': 2, 'uncertainty': 1}, 'medium'),
            ({**ALL_ZERO, 'scope': 2, 'uncertainty': 2,
              'reasoning_complexity': 2}, 'high'),
            ({name: 2 for name in r.DIMENSIONS}, 'xhigh'),
        ]
        for dimensions, expected in cases:
            with self.subTest(dimensions=dimensions):
                self.assertEqual(r.assess('', dimensions)['recommended'], expected)
        self.assertEqual(r.assess('normal feature')['recommended'], 'medium')
        self.assertEqual(r.assess('', {})['recommended'], 'medium')

    def test_task_kind_defaults_and_floors(self):
        for kind in ('mechanical', 'lookup', 'format', 'rename', 'summary'):
            with self.subTest(kind=kind):
                self.assertEqual(r.assess('lots of files', task_kind=kind)['recommended'], 'low')
        for kind in ('security', 'concurrency', 'schema_migration', 'flaky_bug',
                     'unknown_root_cause'):
            with self.subTest(kind=kind):
                self.assertEqual(r.assess('small task', task_kind=kind)['recommended'], 'high')
        for kind in ('cross_service_redesign', 'prod_data_migration', 'incident'):
            with self.subTest(kind=kind):
                self.assertEqual(r.assess('small task', task_kind=kind)['recommended'], 'xhigh')

    def test_strict_reasoning_contract(self):
        good = {'effort': 'auto', 'task_kind': 'review', 'dimensions': ALL_ZERO,
                'cap': 'high'}
        self.assertEqual(r.validate_reasoning_config(good), good)
        self.assertEqual(r.validate_reasoning_config({}), {})
        for bad in (False, [], {'extra': 1}, {'effort': True}, {'cap': False},
                    {'task_kind': 3}, {'dimensions': {'scope': 1}},
                    {'dimensions': None},
                    {'dimensions': {'scope': True, **{k: 0 for k in r.DIMENSIONS if k != 'scope'}}},
                    {'model': 'gpt-model-a'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                r.validate_reasoning_config(bad)
        graph = {**good, 'model': 'gpt-model-a'}
        self.assertEqual(r.validate_reasoning_config(graph, allow_model=True), graph)
        with self.assertRaises(ValueError):
            r.validate_reasoning_config({**good, 'model': False}, allow_model=True)

    def test_cap_is_visible_and_auto_never_max(self):
        resolver = lambda provider, model: set(r.LEVELS) if model == 'capable' else {'low', 'medium', 'high'}
        decision = r.route('third-party', 'capable', dimensions={name: 2 for name in r.DIMENSIONS}, cap='high', capability_resolver=resolver)
        self.assertEqual(decision['recommended'], 'xhigh')
        self.assertEqual(decision['selected'], 'high')
        self.assertEqual(decision['effective'], 'high')
        self.assertTrue(any('cap' in reason for reason in decision['reasons']))
        self.assertNotEqual(r.route('third-party', 'capable', task_kind='incident', capability_resolver=resolver)['effective'], 'max')
        self.assertEqual(r.route('third-party', 'limited', requested='max', capability_resolver=resolver)['status'], 'unsupported')
        self.assertEqual(r.route('third-party', 'capable', requested='max', capability_resolver=resolver)['effective'], 'max')

    def test_real_model_capabilities_and_unknowns(self):
        resolver = lambda provider, model: {'low', 'medium', 'high'} if model == 'known' else set()
        self.assertEqual(r.route('third-party', 'known', task_kind='security', capability_resolver=resolver)['status'], 'ok')
        self.assertEqual(r.route('third-party', 'known', requested='xhigh', capability_resolver=resolver)['status'], 'unsupported')
        self.assertEqual(r.route('third-party', 'empty', requested='max', capability_resolver=resolver)['status'], 'unsupported')
        unknown = r.route('third-party', None, task_kind='security')
        self.assertEqual(unknown['status'], 'unknown_model')
        self.assertIsNone(unknown['effective'])
        with self.assertRaises(ValueError):
            r.route(False, 'gpt-model-a')
        with self.assertRaises(ValueError):
            r.route('codex', False)

    def test_effort_replacement_only_touches_provider_options_before_separator(self):
        codex = ['exec', '--config', 'model_reasoning_effort=high', '-cmodel_reasoning_effort=medium',
                 '-c', 'foo=1', 'model_reasoning_effort=prompt-data', '--',
                 '--config', 'model_reasoning_effort=max', '--effort=high']
        self.assertEqual(
            r.replace_effort_args(codex, 'codex', 'low'),
            ['exec', '-c', 'foo=1', 'model_reasoning_effort=prompt-data',
             '-c', 'model_reasoning_effort="low"', '--',
             '--config', 'model_reasoning_effort=max', '--effort=high'])
        claude = ['-p', 'prompt', '--effort', 'high', '--', '--effort=max']
        self.assertEqual(r.replace_effort_args(claude, 'claude', 'medium'),
                         ['-p', 'prompt', '--effort', 'medium', '--', '--effort=max'])

    def test_model_selector_parser_and_override(self):
        args = ['exec', '-c', 'model="gpt-model-a"', '--model=gpt-model-a', '--', '--model', 'prompt']
        self.assertEqual(r.model_from_args(args, 'codex'), 'gpt-model-a')
        with self.assertRaises(ValueError):
            r.model_from_args(['exec','-c','model=gpt-5.5','--model=gpt-model-a'], 'codex')
        replaced = r.replace_model_args(args, 'codex', 'gpt-model-b')
        self.assertEqual(r.model_from_args(replaced, 'codex'), 'gpt-model-b')
        self.assertEqual(replaced[-2:], ['--model', 'prompt'])


if __name__ == '__main__':
    unittest.main()
