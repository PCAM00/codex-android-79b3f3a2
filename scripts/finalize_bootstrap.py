#!/usr/bin/env python3
"""Finalize configuration and source-built shell helper targets; never modify ELF bytes."""
from pathlib import Path
import argparse,json,zipfile
from bootstrap_validation import validate_zip_links
p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));p.add_argument('--require-source-metadata',action='store_true');a=p.parse_args()
assert a.input.resolve()!=a.output.resolve()
lock=json.loads(a.lock.read_text());package=lock['identity']['applicationId']
replaced={'etc/motd','etc/codex-build.json','etc/apt/apt.conf.d/99-codex-source-isolation','etc/apt/sources.list'}
def network_source(name):return name=='etc/apt/sources.list' or (name.startswith('etc/apt/sources.list.d/') and name.endswith(('.list','.sources')))
a.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(a.input) as original:
 layout=validate_zip_links(original)
 if a.require_source_metadata:
  assert 'etc/codex-build.json' in layout['files'],'Source metadata must be a regular file'
  previous=json.loads(original.read(layout['entries']['etc/codex-build.json']))
  assert previous.get('applicationId')==package and previous.get('nativePrefix')==lock['identity']['nativePrefix']
  assert previous.get('sourceApp')==lock['app']['commit'] and previous.get('sourcePackages')==lock['packages']['commit']
 with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as final:
  for name,info in layout['entries'].items():
   if network_source(name) or name in replaced:continue
   data=original.read(info)
   if data.startswith(b'#!'):
    data=data.replace(f'{package}/{package}.app.'.encode(),f'{package}/com.termux.app.'.encode())
    data=data.replace(f'{package}/.app.'.encode(),f'{package}/com.termux.app.'.encode())
   if name=='SYMLINKS.txt':
    links=[(target,dest) for target,dest in layout['links'] if not network_source(dest) and dest not in replaced]
    data=('\n'.join(target+'←'+dest for target,dest in links)+'\n').encode()
   info.filename=name+('/' if info.is_dir() else '');final.writestr(info,data)
  config={**lock['identity'],'javaNamespace':'com.termux','sourceApp':lock['app']['commit'],'sourcePackages':lock['packages']['commit'],'nativePackageRepository':'disabled: only matching io.cdxbox packages may be installed','runtimeTested':False}
  for name,data in {
   'etc/apt/sources.list':'# io.cdxbox custom-prefix build.\n# Official com.termux binary packages are incompatible.\n# No network repository is enabled. Use only the matching native-debs build artifact.\n',
   'etc/motd':'Codex — independent Termux-derived environment\nPackage: io.cdxbox\nThis is a custom build, not an official OpenAI Android app.\nNative packages must match this application prefix.\nCodex CLI/runtime setup and device validation are separate steps.\n',
   'etc/apt/apt.conf.d/99-codex-source-isolation':'// io.cdxbox native base: use matching local package artifacts only.\nDir::Etc::sourcelist "/dev/null";\nDir::Etc::sourceparts "-";\n',
   'etc/codex-build.json':json.dumps(config,indent=2)+'\n'
  }.items():
   info=zipfile.ZipInfo(name);info.external_attr=0o100600<<16;info.compress_type=zipfile.ZIP_DEFLATED;final.writestr(info,data)
with zipfile.ZipFile(a.output) as final:validate_zip_links(final,strict_names=True)
print('Bootstrap configuration/component references finalized; ELF binaries unchanged:',a.output)
