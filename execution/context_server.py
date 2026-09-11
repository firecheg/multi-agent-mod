"""Общий MCP stdio: ограниченное чтение и память MAM с явным проектом."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mam
from context_budget import settings, summarize
from index_workers import batch
from reasoning_router import DIMENSIONS, KINDS, LEVELS, route, validate_reasoning_config

PROJECT = {'type':'string','description':'Абсолютный путь существующего проекта; определяет границы чтения и памяти.'}
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
    {'name':'reasoning_assess','description':'Детерминированно оценить рекомендуемый reasoning effort без вызова модели.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
     'inputSchema':{'type':'object','properties':{'task':{'type':'string','maxLength':1600},'task_kind':REASONING_PROPERTIES['task_kind'],'dimensions':DIMENSIONS_SCHEMA,'effort':REASONING_PROPERTIES['effort'],'cap':REASONING_PROPERTIES['cap'],'provider':{'type':'string'},'model':{'type':'string'}},'required':['task'],'additionalProperties':False}},
    {'name':'research_batch','description':'До шести коротких вопросов: Graphify-выборка и максимум три дешёвых CLI-агента. summary → Haiku, code → Luna. Возвращает выжимки, расход и ошибки без повторов.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':False,'openWorldHint':True},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'tasks':{'type':'array','minItems':1,'maxItems':6,
       'items':{'type':'object','properties':{'question':{'type':'string','maxLength':2000},'kind':{'type':'string','enum':['summary','code']},'paths':{'type':'array','items':{'type':'string'},'maxItems':6},'reasoning':REASONING_SCHEMA},'required':['question'],'additionalProperties':False}}},'required':['project','tasks'],'additionalProperties':False}},
    {'name':'context_read','description':'Ответить на конкретный вопрос по большим текстовым файлам проекта через ограниченного CLI-исполнителя; возвращает выжимку, источники и расход.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':False,'openWorldHint':True},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'paths':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':30},'question':{'type':'string'},'refresh':{'type':'boolean'},'reasoning':REASONING_SCHEMA},'required':['project','paths','question'],'additionalProperties':False}},
    {'name':'memory_search','description':'Найти ограниченный контекст в общей памяти: только текущий проект и явно глобальные заметки.',
     'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
     'inputSchema':{'type':'object','properties':{'project':PROJECT,'query':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':5}},'required':['project','query'],'additionalProperties':False}},
    {'name':'memory_write','description':'Сохранить устойчивый факт в памяти текущего проекта. Сначала искать существующую заметку; глобальная область задаётся явно.',
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
        return route(args.get('provider',''), args.get('model'), args['task'],
                     reasoning.get('dimensions'), reasoning.get('task_kind'),
                     reasoning.get('effort','auto'), reasoning.get('cap'))
    project = Path(args['project'])
    if not project.is_absolute() or not project.is_dir():
        raise ValueError('project должен быть абсолютным путём существующего каталога')
    mam.WORK = project.resolve()
    if name == 'research_batch':
        return batch(project,args['tasks'])
    if name == 'context_read':
        reasoning = (validate_reasoning_config(args['reasoning'])
                     if 'reasoning' in args else {})
        config = {**settings(), 'provider':'claude', 'model':'haiku',
                  **({'effort':reasoning['effort']} if 'effort' in reasoning else {}),
                  **({'task_kind':reasoning['task_kind']} if 'task_kind' in reasoning else {}),
                  **({'reasoning_dimensions':reasoning['dimensions']} if 'dimensions' in reasoning else {}),
                  **({'cap':reasoning['cap']} if 'cap' in reasoning else {})}
        return summarize(project,args['paths'],args['question'],args.get('refresh',False),config=config)
    if name == 'memory_search':
        limit = args.get('limit',3)
        if not isinstance(limit,int) or not 1 <= limit <= 5:
            raise ValueError('limit: 1..5')
        return {'project_id':mam.project_id(), 'context':mam.mem_context(args['query'],limit)}
    if len(args['body']) > 12000 or len(args['description']) > 400:
        raise ValueError('заметка слишком длинная; сохраните один устойчивый факт')
    if args['type'] not in ['decision','gotcha','pattern','project','person','reference']:
        raise ValueError('неподдерживаемый тип заметки')
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


if __name__ == '__main__':
    for line in sys.stdin:
        try:
            if len(line) > 250000:
                raise ValueError('request too large')
            response = handle(json.loads(line))
        except (ValueError, TypeError) as exc:
            response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(exc)}}
        if response is not None:
            print(json.dumps(response,ensure_ascii=False), flush=True)
