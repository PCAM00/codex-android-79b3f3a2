#!/usr/bin/env python3
"""Finalize only configuration files of a freshly source-built bootstrap."""
from pathlib import Path, PurePosixPath
import argparse, json, zipfile
p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));p.add_argument('--require-source-metadata',action='store_true');a=p.parse_args()
assert a.input.resolve()!=a.output.resolve()
lock=json.loads(a.lock.read_text());prefix=lock['identity']['nativePrefix']
def network_source(name):
 return name=='etc/apt/sources.list' or (name.startswith('etc/apt/sources.list.d/') and name.endswith(('.list','.sources')))
a.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(a.input) as original,zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as final:
 if a.require_source_metadata:
  previous=json.loads(original.read('etc/codex-build.json'))
  assert previous.get('applicationId')==lock['identity']['applicationId']
  assert previous.get('nativePrefix')==lock['identity']['nativePrefix']
  assert previous.get('sourceApp')==lock['app']['commit'] and previous.get('sourcePackages')==lock['packages']['commit']
 names=[]
 for info in original.infolist():
  name=info.filename.removeprefix('./')
  if name.startswith('/') or '..' in PurePosixPath(name).parts:raise SystemExit('Unsafe bootstrap path')
  if network_source(name) or name in {'etc/motd','etc/codex-build.json','etc/apt/apt.conf.d/99-codex-source-isolation'}:continue
  data=original.read(info)
  if data.startswith(b'#!'):
   package=lock['identity']['applicationId']
   data=data.replace(f'{package}/{package}.app.'.encode(),f'{package}/com.termux.app.'.encode())
   data=data.replace(f'{package}/.app.'.encode(),f'{package}/com.termux.app.'.encode())
  if name=='SYMLINKS.txt':
   lines=[]
   for line in data.decode().splitlines():
    if '←' not in line:raise SystemExit('Invalid symlink metadata')
    target,dest=line.split('←',1)
    if not network_source(dest.removeprefix('./')):lines.append(line)
   data=('\n'.join(lines)+'\n').encode()
  info.filename=name;final.writestr(info,data);names.append(name)
 config={**lock['identity'],'sourceApp':lock['app']['commit'],'sourcePackages':lock['packages']['commit'],'nativePackageRepository':'disabled: only matching io.cdxbox packages may be installed','runtimeTested':False}
 for name,data in {
  'etc/apt/sources.list':'# io.cdxbox custom-prefix build.\n# Official com.termux binary packages are incompatible.\n# No network repository is enabled. Use only the matching native-debs build artifact.\n',
  'etc/motd':'Codex — independent Termux-derived environment\nPackage: io.cdxbox\nThis is a private custom build, not an official OpenAI Android app.\nNative packages must match this application prefix.\nCodex CLI/runtime setup and device validation are separate steps.\n',
  'etc/apt/apt.conf.d/99-codex-source-isolation':'// io.cdxbox native base: use matching local package artifacts only.\nDir::Etc::sourcelist "/dev/null";\nDir::Etc::sourceparts "-";\n',
  'etc/codex-build.json':json.dumps(config,indent=2)+'\n'
 }.items():
  info=zipfile.ZipInfo(name);info.external_attr=0o100600<<16;info.compress_type=zipfile.ZIP_DEFLATED;final.writestr(info,data)
print('Bootstrap configuration/component references finalized; ELF binaries unchanged:',a.output)
