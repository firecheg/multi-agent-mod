import json
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
import subprocess
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'execution'))
import index_workers as m
import worker_cli


class WorkerTests(unittest.TestCase):
    def test_registration_is_shared_with_git_subdirectories_not_other_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'repo';root.mkdir();sub=root/'sub';sub.mkdir()
            other=base/'other';other.mkdir();shared=base/'shared';(shared/'skills').mkdir(parents=True)
            subprocess.run(['git','init','-q',str(root)],check=True)
            graph=shared/'skills/graph.json';graph.write_text('{}')
            with patch.object(m,'shared_root',return_value=shared):
                m.register(root,graph,'2026-09-08 test source')
                self.assertEqual(m.index_for(root),m.index_for(sub))
                self.assertIsNone(m.index_for(other))

    def test_validate_all_before_calling_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1')
            task={'question':'x','paths':['a.py']}
            with patch.object(m,'index_for',return_value=None), patch.object(m,'summarize') as call:
                with self.assertRaises(ValueError): m.batch(root,[task,{'question':'bad','paths':['../outside.py']}])
                call.assert_not_called()
            with patch.object(m,'index_for',return_value=None), patch.object(m,'summarize',side_effect=ValueError('offline')) as call:
                result=m.batch(root,[task,task])
                self.assertEqual(call.call_count,1)
                self.assertFalse(result['results'][0]['retried'])

    def test_workers_bounded_and_models_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1')
            active=0;maximum=0;lock=threading.Lock();models=set()
            def worker(project,paths,question,config):
                nonlocal active,maximum
                with lock: active+=1;maximum=max(maximum,active);models.add(config['model'])
                time.sleep(.04)
                with lock: active-=1
                return dict(answer='ok',cached=False,truncated=False,worker=config['provider'],model=config['model'],seconds=.04,usage={},reported_cost_usd=None,source_chars=3,run='log')
            tasks=[{'question':str(i),'paths':['a.py'],'kind':'code' if i%2 else 'summary'} for i in range(6)]
            with patch.object(m,'index_for',return_value=None),patch.object(m,'summarize',side_effect=worker):
                result=m.batch(root,tasks)
            self.assertLessEqual(maximum,3);self.assertGreater(maximum,1)
            self.assertEqual(models,{'demo'})
            self.assertEqual(len(result['results']),6)

    def test_reasoning_dimensions_and_cap_reach_worker_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1')
            dimensions={'scope':2,'uncertainty':2,'reasoning_complexity':2,
                        'risk':0,'verification_complexity':0}
            task={'question':'q','paths':['a.py'],'kind':'code',
                  'reasoning':{'dimensions':dimensions,'cap':'medium'}}
            with patch.object(m,'index_for',return_value=None), patch.object(m,'summarize') as summarize:
                summarize.return_value=dict(answer='ok',cached=False,truncated=False,worker='codex',model='gpt-model-a',seconds=0,usage={},reported_cost_usd=None,source_chars=3,run='log',reasoning={'effective':'medium'})
                result=m.batch(root,[task])
            config=summarize.call_args.kwargs['config']
            self.assertEqual(config['reasoning_dimensions'],dimensions)
            self.assertEqual(config['cap'],'medium')
            self.assertEqual(result['results'][0]['reasoning']['effective'],'medium')

    def test_invalid_reasoning_is_rejected_before_graph_or_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1')
            bad_values=[False, [], {'provider':'claude'}, {'max_output_chars':9},
                        {'dimensions':{'scope':1}}]
            for reasoning in bad_values:
                with self.subTest(reasoning=reasoning), patch.object(m,'index_for',return_value={'graph':'x'}), patch.object(m,'graph_context') as graph, patch.object(m,'summarize') as summarize:
                    with self.assertRaises(ValueError):
                        m.batch(root,[{'question':'q','paths':['a.py'],'reasoning':reasoning}])
                    graph.assert_not_called(); summarize.assert_not_called()

    def test_graph_confined_and_cli_called_with_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir();shared=Path(tmp)/'shared';(shared/'skills').mkdir(parents=True)
            graph=shared/'skills/graph.json';graph.write_text('{}')
            entry={'graph':str(graph),'snapshot':'test commit'}
            with patch.object(m,'shared_root',return_value=shared),patch.object(m.shutil,'which',return_value='graphify'),patch.object(m.subprocess,'run') as run:
                run.return_value.returncode=0;run.return_value.stdout='node';run.return_value.stderr=''
                output=m.graph_context(root,'q',entry)
                self.assertIn('NOT current source',output.read_text())
                self.assertIn('--budget',run.call_args.args[0])
                m.graph_context(root,'q',entry);self.assertEqual(run.call_count,1)
                graph.write_text('{"changed":true}')
                m.graph_context(root,'q',entry);self.assertEqual(run.call_count,2)
                outside=Path(tmp)/'outside.json';outside.write_text('{}')
                with self.assertRaises(ValueError):m.graph_context(root,'q',{'graph':str(outside)})

    def test_configured_worker_argv_is_shell_free_and_has_effort(self):
        args=worker_cli.command('demo','demo',Path('run'),effort='medium')
        self.assertEqual(args[0], sys.executable)
        self.assertIn('--effort',args)

    def test_worker_persists_actual_argv_and_reuses_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)
            decision={'recommended':'high','selected':'medium','effective':'medium',
                      'status':'ok'}
            completed=subprocess.CompletedProcess(['worker'],0,'ok','')
            config={'provider':'demo','model':'demo','timeout_seconds':10,
                    '_reasoning_decision':decision}
            with patch.object(worker_cli,'command',return_value=['worker','--effort','medium']), \
                    patch.object(worker_cli.subprocess,'run',return_value=completed) as called:
                self.assertEqual(worker_cli.invoke('prompt',run,config)['result'],'ok')
            artifact=json.loads((run/'argv.json').read_text(encoding='utf-8'))
            self.assertEqual(artifact['argv'],called.call_args.args[0])
            self.assertEqual(artifact['reasoning'],decision)


if __name__=='__main__':unittest.main()
