"""Spec Kit 1.0.4: подготовка в staging и добавление только отсутствующих файлов."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

VERSION='1.0.4'


def fingerprint(path):
    data=path.read_bytes()
    if path.name.endswith('.manifest.json') or path.name=='workflow-registry.json':
        def stable(value):
            if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in {'installed_at','updated_at'}}
            if isinstance(value,list):return [stable(v) for v in value]
            return value
        data=json.dumps(stable(json.loads(data)),sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def manifest(root):
    return {p.relative_to(root).as_posix():fingerprint(p)
            for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}


def initialize(project, apply=False):
    project=Path(project)
    if not project.is_absolute() or not project.is_dir():
        raise ValueError('нужен абсолютный путь существующего проекта')
    project=project.resolve();exe=shutil.which('specify')
    if not exe: raise ValueError('specify не установлен; см. общий skill speckit')
    version=subprocess.run([exe,'version'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    if VERSION not in version.stdout: raise ValueError('ожидалась версия specify '+VERSION)
    # Официальные ресурсы собираются один раз; два entrypoint — штатные адаптеры клиентов.
    with tempfile.TemporaryDirectory(prefix='mam-specify-') as tmp:
        stage=Path(tmp)/'project'
        subprocess.run([exe,'init',str(stage),'--integration','claude','--script','ps','--non-interactive','--ignore-agent-tools'],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        subprocess.run([exe,'integration','install','codex','--script','ps'],cwd=stage,check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        desired=manifest(stage);conflicts=[];new=[]
        for relative,sha in desired.items():
            destination=project/relative
            if not destination.resolve().is_relative_to(project):
                raise ValueError('ссылка выводит целевой путь за проект: '+relative)
            if destination.exists():
                if not destination.is_file() or fingerprint(destination)!=sha:
                    conflicts.append(relative)
            else:new.append(relative)
        result={'project':str(project),'version':VERSION,'new':new,'conflicts':conflicts,'applied':False}
        if not apply:return result
        if conflicts:raise ValueError('существующие файлы отличаются; ничего не изменено: '+', '.join(conflicts))
        created=[]
        try:
            for relative in new:
                target=project/relative;target.parent.mkdir(parents=True,exist_ok=True)
                # Эксклюзивное создание защищает от правок, сделанных после preview.
                with target.open('xb') as output:
                    created.append(target)
                    output.write((stage/relative).read_bytes())
        except Exception:
            for target in reversed(created):target.unlink()
            raise
        result['applied']=True
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--apply',action='store_true',help='по умолчанию только preview')
    a=parser.parse_args()
    try:print(json.dumps(initialize(a.project,a.apply),ensure_ascii=False,indent=2))
    except (ValueError,subprocess.CalledProcessError) as exc:parser.exit(1,str(exc)+'\n')
