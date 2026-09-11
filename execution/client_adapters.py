"""Точечные настройки MCP и Claude hook; откат сохраняет чужие изменения."""
import argparse
import json
from pathlib import Path
import sys
import tomllib

START = '# BEGIN agent-harness managed MCP'
END = '# END agent-harness managed MCP'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')


def get(data, keys):
    for key in keys:
        if not isinstance(data,dict) or key not in data:
            return None
        data=data[key]
    return data


def put(data, keys, value):
    for key in keys[:-1]: data=data.setdefault(key,{})
    if value is None: data.pop(keys[-1],None)
    else: data[keys[-1]]=value


def issues(shared, allow_partial=False):
    state=load(Path(shared)/'adapters.json'); problems=[]
    if not state or state.get('status') == 'rolled_back': return problems
    partial = allow_partial and state.get('status') == 'applying'
    if state.get('status') != 'active' and not partial:
        problems.append('unfinished adapter transaction; run configure or rollback to recover')
    for op in state['json']:
        current = get(load(Path(op['path'])),op['keys'])
        if current != op['new'] and not (partial and current == op['old']):
            problems.append('changed managed setting: '+op['path']+' '+'.'.join(op['keys']))
    path=Path(state['toml']['path'])
    text=path.read_text(encoding='utf-8-sig') if path.exists() else ''
    if state['toml']['block'] not in text:
        untouched = partial and START not in text and END not in text
        try:
            untouched = untouched and 'agent_harness' not in tomllib.loads(text).get('mcp_servers',{})
        except tomllib.TOMLDecodeError:
            untouched = False
        if not untouched:
            problems.append('changed managed MCP block: '+str(path))
    return problems


def configure(home, shared, mam, python):
    home,shared,mam=map(lambda p:Path(p).resolve(),(home,shared,mam))
    state_path=shared/'adapters.json'
    previous=load(state_path)
    if previous.get('status') == 'active':
        if issues(shared): raise ValueError('; '.join(issues(shared)))
        return previous
    if previous.get('status') == 'applying':
        rollback(shared)
    server={'command':str(python),'args':['-X','utf8',str(mam/'execution/context_server.py')],
            'env':{'MAM_HOME':str(mam),'MAM_SHARED':str(shared),'MAM_MEMORY':str(home/'.mam-memory')}}
    registry={**load(shared/'connections.json'),'version':1,'mcp':{'agent_harness':server},
              'native_plugins':{'ponytail':{'clients':['codex','claude'],'managed_by':'native plugin managers'}},
              'client_specific':'Codex app connectors and native browser/document tools remain managed by Codex; Claude security hooks remain managed by Claude.'}
    write(shared/'connections.json',registry)
    command='"'+str(python)+'" -X utf8 "'+str(mam/'execution/context_budget.py')+'" hook'
    settings_path=home/'.claude/settings.json'
    existing_hook=get(load(settings_path),['hooks','PreToolUse']) or []
    hook={'matcher':'Read|Bash','hooks':[{'type':'command','command':command,'timeout':10}]}
    codex_hooks=home/'.codex/hooks.json'
    existing_codex=get(load(codex_hooks),['hooks','PreToolUse']) or []
    codex_hook={'matcher':'Bash','hooks':[{'type':'command','command':command,'timeout':10}]}
    operations=[(home/'.claude.json',['mcpServers','agent_harness'],server),
                (settings_path,['hooks','PreToolUse'],[*existing_hook,hook]),
                (codex_hooks,['hooks','PreToolUse'],[*existing_codex,codex_hook])]
    config=home/'.codex/config.toml'
    old_text=config.read_text(encoding='utf-8-sig') if config.exists() else ''
    if START in old_text or 'agent_harness' in tomllib.loads(old_text).get('mcp_servers',{}):
        raise ValueError('pre-existing agent_harness MCP requires manual merge')
    # JSON-строки совместимы с TOML basic strings для этих путей и аргументов.
    q=lambda value:json.dumps(value,ensure_ascii=False)
    block='\n'+START+'\n[mcp_servers.agent_harness]\ncommand = '+q(server['command'])+'\nargs = '+q(server['args'])+'\nstartup_timeout_sec = 30\n[mcp_servers.agent_harness.env]\n'
    block+=''.join(k+' = '+q(v)+'\n' for k,v in server['env'].items())+END+'\n'
    tomllib.loads(old_text+block)
    state={'status':'applying','json':[],'toml':{'path':str(config),'block':block}}
    for path,keys,value in operations:
        old=get(load(path),keys)
        if keys[-1]=='agent_harness' and old is not None:
            raise ValueError('pre-existing Claude agent_harness MCP requires manual merge')
        state['json'].append({'path':str(path),'keys':keys,'old':old,'new':value})
    write(state_path,state)
    try:
        for op in state['json']:
            path=Path(op['path']);data=load(path)
            if get(data,op['keys']) != op['old']: raise ValueError('configuration changed during migration')
            put(data,op['keys'],op['new']);write(path,data)
        if config.exists() and config.read_text(encoding='utf-8-sig') != old_text:
            raise ValueError('Codex configuration changed during migration')
        config.write_text(old_text+block,encoding='utf-8')
        state['status']='active';write(state_path,state)
    except Exception:
        for op in state['json']:
            path=Path(op['path']);data=load(path)
            if get(data,op['keys']) == op['new']:
                put(data,op['keys'],op['old']);write(path,data)
        state['status']='rolled_back';write(state_path,state)
        raise
    return state


def rollback(shared):
    shared=Path(shared);state=load(shared/'adapters.json')
    if not state or state.get('status')=='rolled_back': return
    found=issues(shared, allow_partial=True)
    if found: raise ValueError('; '.join(found))
    for op in state['json']:
        path=Path(op['path']);data=load(path)
        if get(data,op['keys']) == op['new']:
            put(data,op['keys'],op['old']);write(path,data)
    path=Path(state['toml']['path'])
    if path.exists():
        text=path.read_text(encoding='utf-8-sig')
        if state['toml']['block'] in text:
            path.write_text(text.replace(state['toml']['block'],'',1),encoding='utf-8')
    state['status']='rolled_back';write(shared/'adapters.json',state)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['configure','upgrade','doctor','rollback'])
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--mam',type=Path,default=Path(__file__).resolve().parents[1])
    a=p.parse_args();shared=a.home/'.agent-harness'
    if a.command=='upgrade':
        rollback(shared)
        configure(a.home,shared,a.mam,sys.executable)
    elif a.command=='configure': configure(a.home,shared,a.mam,sys.executable)
    elif a.command=='rollback': rollback(shared)
    result={'problems':issues(shared)}
    print(json.dumps(result,ensure_ascii=False))
    sys.exit(bool(result['problems']))
