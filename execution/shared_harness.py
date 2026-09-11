"""Общий каталог скиллов и обратимое подключение Codex/Claude на Windows."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def inside(path, root):
    # Проверяем лексический путь перед изменением ссылки и физический корень.
    path, root = Path(os.path.abspath(path)), Path(root).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f'path outside allowed root: {path}')
    return path


def tree_files(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            child = Path(directory) / name
            if child.is_symlink() or child.is_junction():
                raise ValueError(f'nested directory link requires explicit handling: {child}')
        for name in files:
            child = Path(directory) / name
            if child.is_symlink():
                raise ValueError(f'nested file link requires explicit handling: {child}')
            result[child.relative_to(root).as_posix()] = digest(child)
    return result


def plan(home, shared, mam):
    home, shared, mam = Path(home).resolve(), Path(shared).resolve(), Path(mam).resolve()
    inside(shared, home)
    skills, conflicts = {}, []
    for host in ('.claude', '.codex'):
        root = home / host / 'skills'
        if not root.exists():
            continue
        if not root.resolve().is_relative_to(home):
            raise ValueError(f'skills directory escapes home: {root}')
        for child in sorted(root.iterdir()):
            if child.name.startswith('.') or not (child / 'SKILL.md').is_file():
                continue
            resolved = child.resolve()
            approved_external = child.name == 'multi-agent' and resolved == (mam / 'skills/multi-agent').resolve()
            if not resolved.is_relative_to(home) and not approved_external:
                raise ValueError(f'external skill link requires explicit registration: {child}')
            entry = skills.setdefault(child.name, {'source': str(child.resolve()), 'originals': []})
            entry['originals'].append(str(child))
    for name, entry in skills.items():
        entry['target'] = str(mam / 'skills/multi-agent' if name == 'multi-agent' else shared / 'skills' / name)
        sources = list(dict.fromkeys(str(Path(p).resolve()) for p in entry['originals']))
        entry['sources'] = sources
        hashes = {}
        for source in sources:
            for relative, sha in tree_files(Path(source)).items():
                if relative in hashes and hashes[relative] != sha:
                    conflicts.append({'skill': name, 'file': relative, 'winner': entry['source'], 'alternate': source})
                hashes.setdefault(relative, sha)
        entry['hashes'] = hashes
    return {'home': str(home), 'shared': str(shared), 'mam': str(mam), 'skills': skills, 'conflicts': conflicts}


def junction(path, target):
    if os.name == 'nt':
        env = {**os.environ, 'MAM_LINK_PATH': str(path), 'MAM_LINK_TARGET': str(target)}
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:MAM_LINK_PATH -Target $env:MAM_LINK_TARGET | Out-Null"],
                       env=env, check=True, capture_output=True)
    else:
        os.symlink(target, path, target_is_directory=True)


def check_operation(op):
    path = Path(op['path'])
    if op['kind'] in ('directory', 'hardlink'):
        if not path.exists() or not os.path.samefile(path, op['target']):
            raise ValueError(f'changed link: {path}')
    elif not path.is_file() or digest(path) != op['sha256']:
        raise ValueError(f'changed configuration: {path}')


def apply(home, shared, mam, rules):
    home, shared, mam = Path(home).resolve(), Path(shared).resolve(), Path(mam).resolve()
    inside(shared, home)
    state_path = shared / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['status'] == 'active':
            for operation in state['operations']:
                check_operation(operation)
            return state
        if state['status'] != 'rolled_back':
            raise ValueError('unfinished transaction; inspect state.json before continuing')
    inventory = plan(home, shared, mam)
    transaction = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    backup = shared / 'backups' / transaction
    backup.mkdir(parents=True)
    save(backup / 'plan.json', inventory)
    core = shared / 'rules/AGENTS.md'
    core.parent.mkdir(parents=True, exist_ok=True)
    core.write_text(rules, encoding='utf-8')
    # Сначала создаём и проверяем общий каталог. Клиентские пути пока не трогаем.
    for name, entry in inventory['skills'].items():
        target = Path(entry['target'])
        if name == 'multi-agent':
            if not (target / 'SKILL.md').exists():
                raise ValueError('multi-agent target missing')
            continue
        if target.exists():
            if tree_files(target) != entry['hashes']:
                raise ValueError(f'pre-existing canonical skill differs: {target}')
            continue
        for source in entry['sources']:
            for relative in tree_files(Path(source)):
                dest = target / relative
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(Path(source) / relative, dest)
        if tree_files(target) != entry['hashes']:
            raise ValueError(f'copy verification failed: {target}')
    state = {'transaction': transaction, 'home': str(home), 'shared': str(shared),
             'status': 'applying', 'operations': [], 'skills': inventory['skills']}
    save(state_path, state)

    def replace(path, kind, target=None, text=None):
        path = inside(path, home)
        # Не разрешаем родительскому junction вывести операцию за пределы профиля.
        inside(path.parent.resolve(), home)
        path.parent.mkdir(parents=True, exist_ok=True)
        old = backup / 'originals' / path.relative_to(home)
        exists = os.path.lexists(path)
        op = {'path': str(path), 'kind': kind, 'backup': str(old) if exists else None}
        if target is not None:
            op['target'] = str(Path(target).resolve())
        # Запись намерения позволяет восстановиться даже после остановки процесса.
        op['phase'] = 'planned'
        state['operations'].append(op)
        save(state_path, state)
        if exists:
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, old)
        op['phase'] = 'backed_up'
        save(state_path, state)
        if kind == 'directory':
            junction(path, target)
        elif kind == 'hardlink':
            os.link(target, path)
        else:
            path.write_text(text, encoding='utf-8')
            op['sha256'] = digest(path)
        op['phase'] = 'installed'
        save(state_path, state)

    try:
        for name, entry in inventory['skills'].items():
            for host in ('.claude', '.codex'):
                replace(home / host / 'skills' / name, 'directory', entry['target'])
        replace(home / '.codex/AGENTS.md', 'hardlink', core)
        replace(home / '.claude/AGENTS.md', 'hardlink', core)
        replace(home / '.claude/CLAUDE.md', 'file', text=f'@{core.as_posix()}\n')
        state['status'] = 'active'
        save(state_path, state)
    except Exception:
        # Только собственные операции; оригиналы сохранены до создания ссылки.
        for op in reversed(state['operations']):
            path = Path(op['path'])
            if op['phase'] == 'installed':
                if op['kind'] == 'directory':
                    os.rmdir(path) if os.name == 'nt' else path.unlink()
                else:
                    path.unlink()
            if op['backup'] and Path(op['backup']).exists() and not os.path.lexists(path):
                os.replace(op['backup'], path)
        state['status'] = 'rolled_back'
        save(state_path, state)
        raise
    return state


def rollback(home, shared):
    home, shared = Path(home).resolve(), Path(shared).resolve()
    inside(shared, home)
    state_path = shared / 'state.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state['status'] == 'rolled_back':
        return state
    if state['status'] != 'active' or Path(state['home']) != home:
        raise ValueError('transaction is not active for this profile')
    # Полная проверка ДО первого изменения: правки пользователя останавливают откат.
    for op in state['operations']:
        inside(op['path'], home)
        if op['backup']:
            inside(op['backup'], shared)
            if not os.path.lexists(op['backup']):
                raise ValueError(f'missing backup: {op["backup"]}')
        check_operation(op)
    if (shared / 'adapters.json').exists():
        import client_adapters
        if client_adapters.issues(shared, allow_partial=True):
            raise ValueError('; '.join(client_adapters.issues(shared, allow_partial=True)))
        client_adapters.rollback(shared)
    for op in reversed(state['operations']):
        path = Path(op['path'])
        if op['kind'] == 'directory':
            os.rmdir(path) if os.name == 'nt' else path.unlink()
        else:
            path.unlink()
        if op['backup']:
            os.replace(op['backup'], path)
    state['status'] = 'rolled_back'
    save(state_path, state)
    return state


def doctor(home, shared):
    state = json.loads((Path(shared) / 'state.json').read_text(encoding='utf-8'))
    problems = []
    if state['status'] != 'active':
        problems.append('transaction is not active')
    for op in state['operations']:
        try:
            check_operation(op)
        except (ValueError, OSError) as exc:
            problems.append(str(exc))
    if (Path(shared) / 'adapters.json').exists():
        import client_adapters
        problems.extend(client_adapters.issues(shared))
    return {'status': state['status'], 'skills': len(state['skills']),
            'transaction': state['transaction'], 'problems': problems}


def register(home, shared, mam, source):
    home, shared, mam, source = [Path(p).resolve() for p in (home,shared,mam,source)]
    inside(shared,home)
    if not source.is_relative_to(shared/'skills') and not source.is_relative_to(mam/'skills'):
        raise ValueError('skill source must be in the shared catalog or harness skills')
    if not (source/'SKILL.md').is_file():raise ValueError('SKILL.md missing')
    state_path=shared/'state.json';state=json.loads(state_path.read_text(encoding='utf-8'))
    if state['status']!='active':raise ValueError('migration must be active')
    name=source.name
    paths=[home/host/'skills'/name for host in ('.claude','.codex')]
    canonical=shared/'skills'/name
    if source!=canonical:paths.insert(0,canonical)
    for path in paths:
        inside(path,home);inside(path.parent.resolve(),home)
        if os.path.lexists(path) and not os.path.samefile(path,source):
            raise ValueError(f'existing skill differs: {path}')
    created=[]
    try:
        for path in paths:
            if path.exists():continue
            path.parent.mkdir(parents=True,exist_ok=True);junction(path,source);created.append(path)
            state['operations'].append({'path':str(path),'kind':'directory','backup':None,'target':str(source),'phase':'installed'})
        state['skills'][name]={'source':str(source),'target':str(source),'originals':[]}
        save(state_path,state)
    except Exception:
        for path in reversed(created):os.rmdir(path) if os.name=='nt' else path.unlink()
        raise
    return {'registered':name,'source':str(source)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'apply', 'doctor', 'rollback','add'])
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--shared', type=Path)
    parser.add_argument('--mam', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--rules', type=Path)
    parser.add_argument('--source',type=Path)
    args = parser.parse_args()
    shared = args.shared or args.home / '.agent-harness'
    if args.command == 'add':
        if not args.source:parser.error('--source required')
        result=register(args.home,shared,args.mam,args.source)
    elif args.command == 'plan':
        result = plan(args.home, shared, args.mam)
    elif args.command == 'apply':
        if not args.rules:
            parser.error('--rules required')
        result = apply(args.home, shared, args.mam, args.rules.read_text(encoding='utf-8'))
        result = {'status': result['status'], 'transaction': result['transaction'], 'skills': len(result['skills'])}
    elif args.command == 'rollback':
        result = rollback(args.home, shared)
        result = {'status': result['status'], 'transaction': result['transaction']}
    else:
        result = doctor(args.home, shared)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('problems'):
        sys.exit(1)


if __name__ == '__main__':
    main()
