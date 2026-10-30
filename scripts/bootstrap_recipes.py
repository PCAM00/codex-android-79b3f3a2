#!/usr/bin/env python3
"""Resolve bootstrap runtime package names to real source recipes, including subpackages."""
from pathlib import Path
import argparse,json,re
NAME=re.compile(r'^[a-z0-9][a-z0-9+.-]*$')
def resolve(root,name):
    if not NAME.fullmatch(name):raise ValueError('Invalid runtime package name: '+name)
    source=root/'packages'
    if (source/name/'build.sh').is_file():return name
    matches=sorted({p.parent.name for p in source.glob('*/'+name+'.subpackage.sh') if (p.parent/'build.sh').is_file()})
    if len(matches)!=1:raise ValueError(f'Cannot uniquely resolve runtime package {name}: {matches}')
    return matches[0]

def requested(script,extras):
    names=re.findall(r'(?<![A-Z_])PACKAGES\+=\("([a-z0-9+.-]+)"\)',script.read_text())
    if len(names)<25:raise ValueError('Unexpected pinned bootstrap package-list layout')
    return list(dict.fromkeys(names+[x for x in extras.split(',') if x]))

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--resolve');p.add_argument('--check',nargs='+');p.add_argument('--from-script',type=Path);p.add_argument('--extra',default='proot,curl');a=p.parse_args()
    if a.resolve:print(resolve(a.source,a.resolve));return
    names=a.check if a.check is not None else requested(a.from_script,a.extra)
    mapping={name:resolve(a.source,name) for name in names};print(json.dumps(mapping,indent=2))
if __name__=='__main__':main()
