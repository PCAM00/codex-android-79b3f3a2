#!/usr/bin/env python3
"""Fail closed on wrong ABI, old runtime prefixes, or credentials in bootstrap."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, re, struct, zipfile
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--report',type=Path,required=True);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));a=p.parse_args()
lock=json.loads(a.lock.read_text());prefix=lock['identity']['nativePrefix'].encode()
old=[b'/data/data/com.termux/files',b'/data/user/0/com.termux/files',b'/data/data/com.dsharnessmobile.shell/files']
failures=[];warnings=[];elf_count=0;paths=set();link_paths=set();size=0
with zipfile.ZipFile(a.archive) as archive:
 if archive.testzip():raise SystemExit('Corrupt bootstrap ZIP')
 for info in archive.infolist():
  name=info.filename.removeprefix('./');paths.add(name);size+=info.file_size
  if name.startswith('/') or '..' in PurePosixPath(name).parts:failures.append([name,'unsafe path'])
  if info.is_dir():continue
  data=archive.read(info)
  if re.search(rb'(gh[pousr]_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{36,})',data):failures.append([name,'possible credential; value is deliberately not printed'])
  if any(value in data for value in old):
   if name.startswith(('share/doc/','share/man/','share/licenses/')):warnings.append([name,'old-prefix documentation reference'])
   else:failures.append([name,'old runtime prefix'])
  if name=='etc/codex-build.json':
   config=json.loads(data)
   if config.get('applicationId')!=lock['identity']['applicationId'] or config.get('nativePrefix')!=lock['identity']['nativePrefix'] or config.get('sourceApp')!=lock['app']['commit'] or config.get('sourcePackages')!=lock['packages']['commit']:
    failures.append([name,'identity/source metadata mismatch'])
  if data.startswith(b'#!'):
   package=lock['identity']['applicationId']
   if f'{package}/{package}.app.'.encode() in data or f'{package}/.app.'.encode() in data:
    failures.append([name,'component class incorrectly resolved against installation ID'])
  if data.startswith(b'\x7fELF'):
   elf_count+=1
   if data[4]!=2 or data[5]!=1 or struct.unpack_from('<H',data,18)[0]!=183:failures.append([name,'not ELF64 little-endian aarch64'])
   else:
    off=struct.unpack_from('<Q',data,32)[0];step=struct.unpack_from('<H',data,54)[0];count=struct.unpack_from('<H',data,56)[0]
    for n in range(count):
     pos=off+n*step
     if pos+56>len(data):failures.append([name,'truncated ELF headers']);break
     if struct.unpack_from('<I',data,pos)[0]==3:
      start=struct.unpack_from('<Q',data,pos+8)[0];length=struct.unpack_from('<Q',data,pos+32)[0]
      if data[start:start+length].rstrip(b'\0')!=b'/system/bin/linker64':failures.append([name,'unexpected native interpreter'])
  if name=='SYMLINKS.txt':
   for line in data.decode().splitlines():
    if '←' not in line:failures.append([name,'malformed link']);continue
    target,dest=line.split('←',1);dest=dest.removeprefix('./');link_paths.add(dest)
    if dest.startswith('/') or '..' in PurePosixPath(dest).parts:failures.append([name,'unsafe symlink destination'])
  if name.startswith('etc/apt/') and name.endswith(('.list','.sources')):
   active=[line for line in data.decode(errors='replace').splitlines() if line.strip() and not line.lstrip().startswith('#')]
   if active:failures.append([name,'unapproved native binary repository'])
 for required in ['bin/bash','bin/sh','bin/env','bin/curl','bin/proot','libexec/proot/loader','SYMLINKS.txt','etc/codex-build.json']:
  if required not in paths|link_paths:failures.append([required,'required bootstrap entry missing'])
 if elf_count<10:failures.append(['bootstrap','unexpectedly few native programs'])
report={'applicationId':lock['identity']['applicationId'],'prefix':prefix.decode(),'architecture':'aarch64','sha256':hashlib.sha256(a.archive.read_bytes()).hexdigest(),'archiveBytes':a.archive.stat().st_size,'uncompressedBytes':size,'nativeElfFiles':elf_count,'failures':failures,'documentationWarnings':warnings,'staticChecksPassed':not failures,'deviceRuntimeTested':False}
a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='documentationWarnings'},indent=2))
if failures:raise SystemExit(1)
