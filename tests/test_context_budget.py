import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('context_budget', Path(__file__).resolve().parents[1] / 'execution/context_budget.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContextTests(unittest.TestCase):
    def test_truncation_marker_fits_budget_and_result_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'source.py').write_text('x=1')
            config={**module.DEFAULTS,'max_output_chars':80}
            with patch.object(module,'invoke',return_value={'result':'x'*300}) as call:
                result=module.summarize(root,['source.py'],'question',config=config)
                self.assertEqual(len(result['answer']),80)
                self.assertTrue(result['truncated'])
                again=module.summarize(root,['source.py'],'question',config=config)
                self.assertTrue(again['cached']);self.assertEqual(call.call_count,1)

    def test_paths_are_confined_and_secrets_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source.py').write_text('value=1', encoding='utf-8')
            (root / '.env').write_text('secret', encoding='utf-8')
            self.assertEqual(module.collect(root, ['source.py'])[0]['lines'], 1)
            with self.assertRaises(ValueError): module.collect(root, ['.env'])
            with self.assertRaises(ValueError): module.collect(root, ['../outside.py'])

    def test_source_change_invalidates_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root / 'source.py'
            p.write_text('value=1')
            first = module.cache_key(module.collect(root, [str(p)]), 'question', {'model':'sonnet'})
            p.write_text('value=2')
            self.assertNotEqual(first, module.cache_key(module.collect(root, [str(p)]), 'question', {'model':'sonnet'}))

    def test_cache_identity_contains_policy_and_decision(self):
        files = [{'path':'a.py','sha256':'0','lines':1,'absolute_path':'x','text':'x'}]
        config = {**module.DEFAULTS, '_reasoning_decision': {'effective':'low'}}
        low = module.cache_key(files, 'q', config)
        config['_reasoning_decision'] = {'effective':'high'}
        high = module.cache_key(files, 'q', config)
        self.assertNotEqual(low, high)
        self.assertGreaterEqual(module.VERSION, 3)

    def test_one_decision_is_used_for_cache_worker_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'source.py').write_text('x=1')
            dimensions = {'scope': 2, 'uncertainty': 2, 'reasoning_complexity': 0,
                          'risk': 0, 'verification_complexity': 0}
            config = {**module.DEFAULTS, 'provider':'demo', 'model':'demo',
                      'reasoning_dimensions': dimensions, 'cap':'low'}
            with patch.object(module, 'invoke', return_value={'result':'ok'}) as invoke:
                result = module.summarize(root, ['source.py'], 'original question', config=config)
            sent = invoke.call_args.args[2]['_reasoning_decision']
            self.assertEqual(sent['recommended'], 'medium')
            self.assertEqual(sent['effective'], 'low')
            self.assertEqual(result['reasoning'], sent)
            self.assertEqual(invoke.call_count, 1)

    def test_large_read_hook_allows_targeted_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'big.py'; p.write_text('line\n' * 400)
            request = {'tool_name':'Read', 'tool_input':{'file_path':str(p)}}
            self.assertEqual(module.read_hook(request)['hookSpecificOutput']['permissionDecision'], 'deny')
            request['tool_input']['limit'] = 40
            self.assertEqual(module.read_hook(request), {})

    def test_hook_does_not_block_instructions_or_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'AGENTS.md'; p.write_text('line\n'*400)
            self.assertEqual(module.read_hook({'tool_name':'Read','tool_input':{'file_path':str(p)}}), {})


if __name__ == '__main__': unittest.main()
