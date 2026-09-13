"""Provider-neutral MCP stdio server: bounded reading and project-scoped memory."""
import json
from pathlib import Path
import sys

# Bootstrap sibling imports whether this module is loaded as a script, as
# `execution.context_server`, or via the installed `agent-harness-mcp`
# console-script entry point — only the last of those does not already put
# execution/'s own directory on sys.path for us.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import mam
from context_budget import settings, summarize
from index_workers import batch
from providers import ProviderRegistry, load_config
from reasoning_router import DIMENSIONS, KINDS, LEVELS, route, to_worker_config, validate_reasoning_config

PROJECT = {'type':'string','description':'Absolute path to an existing project; bounds reading and memory to it.'}
DIMENSION_PROPERTIES = {name:{'type':'integer','minimum':0,'maximum':2} for name in DIMENSIONS}
DIMENSIONS_SCHEMA = {'type':'object','properties':DIMENSION_PROPERTIES,'additionalProperties':False,
                     'anyOf':[{'maxProperties':0},{'required':list(DIMENSIONS)}]}
REASONING_PROPERTIES = {
    'effort':{'type':'string','enum':['auto',*LEVELS]},
    'task_kind':{'type':'string','enum':sorted(KINDS)},
    'dimensions':DIMENSIONS_SCHEMA,
    'cap':{'type':'string','enum':list(LEVELS)},
}
REASONING_SCHEMA = {'type':'object','properties':REASONING_PROPERTIES,'additionalProperties':False}
TOOLS = [
    {'name':'reasoning_assess','description':'Deterministically assess the recommended reasoning effort without calling a model.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
     'inputSchema':{'type':'object','properties':{'task':{'type':'string','maxLength':1600},'task_kind':REASONING_PROPERTIES['task_kind'],'dimensions':DIMENSIONS_SCHEMA,'effort':REASONING_PROPERTIES['effort'],'cap':REASONING_PROPERTIES['cap'],'provider':{'type':'string'},'model':{'type':'string'}},'required':['task'],'additionalProperties':False}},
    {'name':'research_batch','description':'Up to six short questions: an optional Graphify snapshot plus at most three cheap CLI agents. The "summary" and "code" task kinds each route through their configured role_bindings agent (both default to the offline demo worker). Returns excerpts, cost and errors, without retries.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':False,'openWorldHint':True},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'tasks':{'type':'array','minItems':1,'maxItems':6,
       'items':{'type':'object','properties':{'question':{'type':'string','maxLength':2000},'kind':{'type':'string','enum':['summary','code']},'paths':{'type':'array','items':{'type':'string'},'maxItems':6},'agent':{'type':'string'},'reasoning':REASONING_SCHEMA},'required':['question'],'additionalProperties':False}}},'required':['project','tasks'],'additionalProperties':False}},
    {'name':'context_read','description':'Answer a specific question about large project text files through a bounded configured CLI worker; returns an excerpt, sources and cost.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':False,'openWorldHint':True},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'paths':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':30},'question':{'type':'string'},'refresh':{'type':'boolean'},'agent':{'type':'string'},'reasoning':REASONING_SCHEMA},'required':['project','paths','question'],'additionalProperties':False}},
    {'name':'memory_search','description':'Find bounded context in the shared vault: only the current project and explicitly global notes.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'query':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':5}},'required':['project','query'],'additionalProperties':False}},
    {'name':'memory_write','description':'Save one durable fact to the current project memory. Search for an existing note first; global reach is explicit.',
     'annotations':{'readOnlyHint':False,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'name':{'type':'string'},'description':{'type':'string'},'body':{'type':'string'},'type':{'type':'string','enum':['decision','gotcha','pattern','project','person','reference']},'reach':{'type':'string','enum':['repo','global']}},'required':['project','name','description','body','type'],'additionalProperties':False}}
]


def call(name, args):
    if name not in {t['name'] for t in TOOLS}:
        raise ValueError('unknown tool')
    if name == 'reasoning_assess':
        if not isinstance(args,dict) or set(args)-{'task','task_kind','dimensions','effort','cap','provider','model'}:
            raise ValueError('invalid reasoning_assess arguments')
        if 'task' not in args:
            raise ValueError('task is required')
        reasoning = validate_reasoning_config({key:args[key] for key in
                    ('task_kind','dimensions','effort','cap') if key in args})
        runtime = settings()
        registry = ProviderRegistry(load_config(runtime.get('config_path')))
        provider = args.get('provider')
        model = args.get('model')
        if not provider or not model:
            agent = registry.role_agent('context_read')
            provider, model, _ = registry.resolve(agent)
        resolver = registry.capabilities if provider in registry.config['providers'] else None
        return route(provider, model, args['task'],
                     reasoning.get('dimensions'), reasoning.get('task_kind'),
                     reasoning.get('effort','auto'), reasoning.get('cap'),
                     capability_resolver=resolver)
    project = Path(args['project'])
    if not project.is_absolute() or not project.is_dir():
        raise ValueError('project must be an absolute path to an existing directory')
    mam.WORK = project.resolve()
    if name == 'research_batch':
        return batch(project,args['tasks'])
    if name == 'context_read':
        reasoning = (validate_reasoning_config(args['reasoning'])
                     if 'reasoning' in args else {})
        base = settings()
        registry = ProviderRegistry(load_config(base.get('config_path')))
        # An explicit "agent" argument wins; otherwise the configured
        # "context_read" role binding decides — never a vendor name baked
        # into this file.
        agent = args.get('agent') or registry.role_agent('context_read')
        provider, model, _ = registry.resolve(agent)
        config = {**base, 'agent':agent, 'provider':provider, 'model':model, **to_worker_config(reasoning)}
        return summarize(project,args['paths'],args['question'],args.get('refresh',False),config=config)
    if name == 'memory_search':
        limit = args.get('limit',3)
        if not isinstance(limit,int) or not 1 <= limit <= 5:
            raise ValueError('limit: 1..5')
        return {'project_id':mam.project_id(), 'context':mam.mem_context(args['query'],limit)}
    if len(args['body']) > 12000 or len(args['description']) > 400:
        raise ValueError('note too long; save one durable fact')
    if args['type'] not in ['decision','gotcha','pattern','project','person','reference']:
        raise ValueError('unsupported note type')
    path = mam.mem_write('brain',args['name'],args['description'],args['type'],args['body'],args.get('reach','repo'))
    return {'path':str(path), 'project_id':mam.project_id()}


def handle(request):
    if not isinstance(request,dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'),str):
        return {'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,
                'error':{'code':-32600,'message':'Invalid Request'}}
    method, params = request.get('method'), request.get('params',{})
    if 'id' not in request:
        return None
    result = {'jsonrpc':'2.0','id':request['id']}
    if not isinstance(params,dict):
        result['error']={'code':-32602,'message':'Invalid params'}
        return result
    if method == 'initialize':
        result['result'] = {'protocolVersion':'2025-06-18','capabilities':{'tools':{}},
                            'serverInfo':{'name':'agent-harness','version':'1.0.0'}}
    elif method == 'ping': result['result'] = {}
    elif method == 'tools/list': result['result'] = {'tools':TOOLS}
    elif method == 'tools/call':
        try:
            output = call(params['name'],params.get('arguments',{}))
            result['result'] = {'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False)}]}
        except Exception as exc:
            result['result'] = {'content':[{'type':'text','text':str(exc)}],'isError':True}
    else:
        result['error'] = {'code':-32601,'message':'Method not found'}
    return result


def main():
    """Entry point for the `agent-harness-mcp` console script: one JSON-RPC
    request per stdin line, one JSON-RPC response per stdout line."""
    for line in sys.stdin:
        try:
            if len(line) > 250000:
                raise ValueError('request too large')
            response = handle(json.loads(line))
        except (ValueError, TypeError) as exc:
            response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(exc)}}
        if response is not None:
            print(json.dumps(response,ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
