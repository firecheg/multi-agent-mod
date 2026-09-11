"""Разовые CLI-вызовы Haiku/Luna без пользовательских плагинов и shell-инструмента."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from reasoning_router import (assessment_text, route, replace_effort_args,
                              validate_reasoning_config)


def command(provider, model, run, effort=None):
    if provider == 'claude':
        native = Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe'
        exe = str(native) if native.is_file() else shutil.which('claude')
        if not exe: raise ValueError('Claude CLI not found')
        args = [exe,'-p','--model',model,'--tools','',
                '--disable-slash-commands','--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
                '--setting-sources','','--no-session-persistence','--output-format','json',
                '--system-prompt','Анализируй только входные документы. Без инструментов и делегации.']
        return replace_effort_args(args, provider, effort)
    if provider != 'codex': raise ValueError('unknown worker provider')
    candidates = list((Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI/Codex/bin').glob('*/codex.exe'))
    exe = str(max(candidates,key=lambda p:p.stat().st_mtime)) if candidates else shutil.which('codex')
    if not exe: raise ValueError('Codex CLI not found')
    args = [exe,'exec','--ignore-user-config','--model',model,'--sandbox','read-only',
            '--ephemeral','--skip-git-repo-check','--disable','shell_tool','--disable','plugins',
            '--disable','multi_agent','--disable','skill_search','--enable','skip_host_skill_discovery',
            '-c','project_doc_max_bytes=0','-c','web_search="disabled"',
            '-c','approval_policy="never"',
            '--json','--output-last-message',str(run/'answer.txt'),'-']
    return replace_effort_args(args, provider, effort)


def invoke(prompt, run, config):
    provider=config.get('provider','claude')
    if '_reasoning_decision' in config:
        decision = config['_reasoning_decision']
        if not isinstance(decision, dict):
            raise ValueError('_reasoning_decision must be an object')
    else:
        reasoning = validate_reasoning_config({
            **({'effort': config['effort']} if 'effort' in config else {}),
            **({'task_kind': config['task_kind']} if 'task_kind' in config else {}),
            **({'dimensions': config['reasoning_dimensions']} if 'reasoning_dimensions' in config else {}),
            **({'cap': config['cap']} if 'cap' in config else {}),
        })
        decision = route(provider, config.get('model'),
                         assessment_text(config.get('_routing_task', prompt)),
                         reasoning.get('dimensions'), reasoning.get('task_kind'),
                         reasoning.get('effort','auto'), reasoning.get('cap'))
    (run/'reasoning.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding='utf-8')
    argv = command(provider,config['model'],run,decision.get('effective'))
    (run/'argv.json').write_text(json.dumps({'argv':argv,'reasoning':decision},ensure_ascii=False,indent=2),encoding='utf-8')
    proc=subprocess.run(argv,input=prompt,cwd=run,
                        capture_output=True,text=True,encoding='utf-8',errors='replace',
                        timeout=config['timeout_seconds'])
    (run/'worker.json').write_text(proc.stdout,encoding='utf-8')
    (run/'stderr.log').write_text(proc.stderr,encoding='utf-8')
    if proc.returncode: raise ValueError(f'{provider} exited {proc.returncode}; log: {run}; no automatic retry')
    if provider=='claude': return json.loads(proc.stdout)
    events=[json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    failures=[e for e in events if e.get('type') in ('error','turn.failed')]
    completed=[e for e in events if e.get('type')=='turn.completed']
    if failures or not completed: raise ValueError(f'Codex did not complete; log: {run}')
    return {'result':(run/'answer.txt').read_text(encoding='utf-8'),
            'usage':completed[-1].get('usage'), 'modelUsage':None,'total_cost_usd':None}
