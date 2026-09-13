"""Проверки протокола MCP и офлайн-интеграции."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
class Integrations(unittest.TestCase):
    def test_mcp_survives_invalid_request_and_lists_annotated_tools(self):
        requests=[None,[],{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':None}]
        cp=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'execution/context_server.py')],
                          input='\n'.join(json.dumps(x) for x in requests)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(cp.returncode,0,cp.stderr)
        responses=[json.loads(x) for x in cp.stdout.splitlines()]
        self.assertEqual(responses[0]['error']['code'],-32600)
        tools={x['name']:x for x in responses[3]['result']['tools']}
        self.assertTrue(tools['memory_search']['annotations']['readOnlyHint'])
        self.assertFalse(tools['memory_write']['annotations']['readOnlyHint'])
        self.assertEqual(responses[4]['error']['code'],-32602)

    def test_mcp_reasoning_schemas_and_parameter_propagation(self):
        sys.path.insert(0, str(ROOT/'execution'))
        import context_server as server
        tools={tool['name']:tool for tool in server.TOOLS}
        dimensions=tools['reasoning_assess']['inputSchema']['properties']['dimensions']
        self.assertFalse(dimensions['additionalProperties'])
        self.assertIn('cap',tools['reasoning_assess']['inputSchema']['properties'])
        self.assertIn('reasoning',tools['research_batch']['inputSchema']['properties']['tasks']['items']['properties'])
        self.assertIn('reasoning',tools['context_read']['inputSchema']['properties'])
        all_dimensions={'scope':0,'uncertainty':1,'reasoning_complexity':2,
                        'risk':0,'verification_complexity':1}
        with tempfile.TemporaryDirectory() as tmp, patch.object(server,'summarize',return_value={'answer':'ok'}) as summarize:
            root=Path(tmp).resolve();(root/'a.py').write_text('x')
            server.call('context_read',{'project':str(root),'paths':['a.py'],'question':'q',
                                        'reasoning':{'dimensions':all_dimensions,'cap':'low'}})
        config=summarize.call_args.kwargs['config']
        self.assertEqual(config['reasoning_dimensions'],all_dimensions)
        self.assertEqual(config['cap'],'low')
        self.assertEqual(config['model'],'demo')

    def test_mcp_rejects_invalid_nested_reasoning(self):
        sys.path.insert(0, str(ROOT/'execution'))
        import context_server as server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'a.py').write_text('x')
            for reasoning in (False, {'provider':'codex'}, {'dimensions':{'scope':1}}):
                with self.subTest(reasoning=reasoning), self.assertRaises(ValueError):
                    server.call('context_read',{'project':str(root),'paths':['a.py'],
                                                'question':'q','reasoning':reasoning})

if __name__=='__main__':unittest.main()
