#!/usr/bin/env python3
"""Select runtime dependencies only; do not put the entire native build toolchain in the APK."""
from pathlib import Path
import argparse,json,re,shutil,subprocess
DEP=re.compile(r'^([a-z0-9][a-z0-9+.-]*)(?::([a-z0-9-]+))?(?:\s*\((<<|<=|=|>=|>>)\s*([^()]+)\))?$')
def control(text):
    result={};key=None
    for line in text.splitlines():
        if line.startswith((' ','\t')) and key:result[key]+=' '+line.strip()
        elif ':' in line:key,value=line.split(':',1);result[key]=value.strip()
    return result

def atom(text):
    m=DEP.fullmatch(text.strip())
    if not m:raise ValueError('Unsupported dependency expression: '+text)
    return m.groups()

def version_ok(have,op,wanted):
    if not op:return True
    if not have:return False
    result=subprocess.run(['dpkg','--compare-versions',have,op,wanted],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode not in (0,1):raise ValueError('Invalid Debian version comparison')
    return result.returncode==0

def select(records,roots,arch):
    packages={};providers={}
    for item in records:
        if item['Architecture'] not in (arch,'all'):continue
        name=item['Package']
        if name in packages:raise ValueError('Multiple .deb versions/architectures for '+name)
        packages[name]=item
        for provision in filter(None,item.get('Provides','').split(',')):
            alias,qualifier,op,version=atom(provision)
            if op not in (None,'='):raise ValueError('Unsupported versioned Provides')
            providers.setdefault(alias,[]).append((name,version))
    def choose(text):
        for alternative in text.split('|'):
            name,qualifier,op,version=atom(alternative)
            if qualifier not in (None,'any','native',arch,'all'):continue
            if name in packages and version_ok(packages[name]['Version'],op,version):return name
            for provider,provided_version in providers.get(name,[]):
                if version_ok(provided_version,op,version):return provider
        raise ValueError('No matching built runtime dependency: '+text)
    todo=[choose(name) for name in roots]
    todo.extend(name for name,item in packages.items() if item.get('Essential','').lower()=='yes')
    selected=set()
    while todo:
        name=todo.pop()
        if name in selected:continue
        selected.add(name);item=packages[name]
        for field in ['Pre-Depends','Depends']:
            for dependency in filter(None,item.get(field,'').split(',')):
                try:todo.append(choose(dependency))
                except ValueError as error:raise ValueError(f'{name}: {error}') from None
    return [packages[name] for name in sorted(selected)]

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--arch',default='aarch64');p.add_argument('--report',type=Path,required=True);p.add_argument('roots',nargs='+');a=p.parse_args()
    assert a.input.resolve()!=a.output.resolve()
    records=[]
    for file in sorted(a.input.glob('*.deb')):
        item=control(subprocess.check_output(['dpkg-deb','-f',str(file)],text=True));item['_path']=str(file);records.append(item)
    if not records:raise SystemExit('No built native packages available')
    chosen=select(records,a.roots,a.arch);a.output.mkdir(parents=True,exist_ok=False)
    for item in chosen:shutil.copy2(item['_path'],a.output/Path(item['_path']).name)
    report={'architecture':a.arch,'requested':a.roots,'builtDebs':len(records),'selectedRuntimeDebs':len(chosen),'selected':[{'name':p['Package'],'version':p['Version']} for p in chosen],'excludedBuildOnly':[p['Package'] for p in records if p['Package'] not in {x['Package'] for x in chosen}]}
    a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'builtDebs':len(records),'selectedRuntimeDebs':len(chosen)},indent=2))
if __name__=='__main__':main()
