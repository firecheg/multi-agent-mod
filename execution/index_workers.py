"""Graphify snapshot retrieval and a bounded batch of cheap reader workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Bootstrap sibling imports whether this module is loaded as a script, as
# `execution.index_workers`, or via an installed console-script entry point.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from context_budget import collect, settings, summarize
from providers import ProviderRegistry, load_config
from reasoning_router import to_worker_config, validate_reasoning_config
from mam import project_id

KINDS = ('summary', 'code')


def shared_root():
    return Path(os.environ.get('AGENT_HARNESS_SHARED',
                os.environ.get('MAM_SHARED', Path.home()/'.agent-harness'))).resolve()


def index_for(project):
    registry=shared_root()/'indexes.json'
    entries=json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}
    # Full path, not basename: identically named projects are not conflated.
    return entries.get(project_id(project)) or entries.get(os.path.normcase(str(Path(project).resolve())))


def register(project, graph, snapshot):
    project=Path(project);graph=Path(graph)
    if not project.is_absolute() or not project.is_dir() or not graph.is_absolute() or not graph.is_file():
        raise ValueError('existing absolute project and graph paths required')
    project=project.resolve();graph=graph.resolve()
    allowed = (shared_root() / 'skills').resolve()
    if not graph.is_relative_to(allowed) and not graph.is_relative_to(project):
        raise ValueError('graph must be inside shared skills or the project')
    if not snapshot.strip(): raise ValueError('snapshot date and source commit required')
    path=shared_root()/'indexes.json'
    entries=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    entries[project_id(project)]={'graph':str(graph),'snapshot':snapshot}
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)
    return {'registered':str(project),'graph':str(graph)}


def graph_context(project, question, entry):
    project = Path(project).resolve()
    graph=Path(entry['graph']).resolve(strict=True)
    allowed=(shared_root()/'skills').resolve()
    if not graph.is_relative_to(allowed) and not graph.is_relative_to(project):
        raise ValueError('registered graph must be inside shared skills or this project')
    sha=hashlib.sha256(graph.read_bytes()).hexdigest()
    key=hashlib.sha256((sha+str(graph)+question+json.dumps(entry,sort_keys=True)).encode()).hexdigest()
    directory=project/'.mam/index';directory.mkdir(parents=True,exist_ok=True)
    output=directory/(key+'.md')
    if output.exists(): return output
    exe=shutil.which('graphify')
    if not exe: raise ValueError('Graphify CLI not found')
    result=subprocess.run([exe,'query',question,'--budget','900','--graph',str(graph)],
                          cwd=project,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    if result.returncode: raise ValueError('Graphify query failed: '+result.stderr[:500])
    text=result.stdout[:6500]
    body=f'Graphify snapshot, NOT current source code.\nGraph: {graph}\nSHA256: {sha}\n'
    body+='Snapshot metadata: '+str(entry.get('snapshot','unknown'))+'\n'
    body+='Graph question: '+question+'\nGraph result:\n'+text
    if len(result.stdout)>6500: body+='\n[Graph output truncated]'
    output.write_text(body,encoding='utf-8')
    return output


def batch(project,tasks):
    project=Path(project)
    if not project.is_absolute() or not project.is_dir(): raise ValueError('absolute existing project required')
    project=project.resolve()
    if not isinstance(tasks,list) or not 1<=len(tasks)<=6: raise ValueError('1..6 tasks required')
    entry=index_for(project)
    runtime = settings()
    registry = ProviderRegistry(load_config(runtime.get('config_path')))
    prepared=[];seen=set()
    # Validate ALL tasks before calling any model, then deduplicate identical ones.
    for task in tasks:
        if not isinstance(task,dict):
            raise ValueError('each task must be an object')
        kind=task.get('kind','summary');question=task.get('question','');paths=task.get('paths',[])
        if kind not in KINDS or not isinstance(question,str) or not question.strip() or len(question)>2000:
            raise ValueError('kind summary/code and question up to 2000 chars required')
        if not isinstance(paths,list) or len(paths)>6: raise ValueError('up to 6 paths per task')
        reasoning = (validate_reasoning_config(task['reasoning'])
                     if 'reasoning' in task else {})
        agent = task.get('agent') or registry.role_agent(kind)
        registry.profile(agent)  # preflight every task before any subprocess
        if paths: collect(project,paths,60000)
        if not paths and not entry: raise ValueError('no project index registered; provide source paths')
        signature=json.dumps([kind,question,paths,reasoning],sort_keys=True)
        if signature in seen: continue
        seen.add(signature);prepared.append((kind,question,list(paths),reasoning,agent))
    graph_paths={}
    if entry:
        for _,question,_,_,_ in prepared:
            if question not in graph_paths:
                graph_paths[question]=graph_context(project,question,entry)
    def work(item):
        kind,question,paths,reasoning,agent=item
        try:
            graph_path=graph_paths.get(question)
            if graph_path: paths.append(str(graph_path))
            provider,model,_=registry.resolve(agent)
            cfg={**runtime,'agent':agent,'provider':provider,'model':model,
                 'max_input_chars':70000,'max_output_chars':1500,
                 **to_worker_config(reasoning)}
            answer=summarize(project,paths,question,config=cfg)
            # Sources and the full CLI transcript are not returned to the calling agent.
            return {'kind':kind,'question':question,'index_used':bool(graph_path),
                    **{k:answer[k] for k in ('answer','cached','truncated','worker','model','seconds','usage','reported_cost_usd','source_chars','run')},
                    'reasoning': answer.get('reasoning')}
        except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
            return {'kind':kind,'question':question,'error':str(exc)[:500],'retried':False}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(work,prepared))
    return {'project':str(project),'max_parallel':3,'results':results,
            'answer_chars':sum(len(r.get('answer','')) for r in results)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--tasks-file',type=Path);group.add_argument('--register-graph',type=Path)
    p.add_argument('--snapshot',default='')
    a=p.parse_args()
    result=register(a.project,a.register_graph,a.snapshot) if a.register_graph else batch(a.project,json.loads(a.tasks_file.read_text(encoding='utf-8')))
    print(json.dumps(result,ensure_ascii=False,indent=2))
