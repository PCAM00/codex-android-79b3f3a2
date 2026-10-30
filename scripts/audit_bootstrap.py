#!/usr/bin/env python3
"""Fail closed on broken link metadata, wrong native ABI/prefix or credentials."""
from pathlib import Path
import argparse,hashlib,json,re,struct,zipfile
from bootstrap_validation import validate_zip_links
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--report',type=Path,required=True);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));a=p.parse_args()
lock=json.loads(a.lock.read_text());prefix=lock['identity']['nativePrefix'].encode();package=lock['identity']['applicationId']
old=[b'/data/data/com.termux/files',b'/data/user/0/com.termux/files',b'/data/data/com.dsharnessmobile.shell/files']
failures=[];warnings=[];elf64=0;helpers=[];size=0;metadata_verified=False
with zipfile.ZipFile(a.archive) as archive:
 if archive.testzip():raise SystemExit('Corrupt bootstrap ZIP')
 try:layout=validate_zip_links(archive,strict_names=True)
 except ValueError as error:raise SystemExit('Bootstrap link/layout audit failed: '+str(error))
 for name,info in layout['entries'].items():
  size+=info.file_size
  if info.is_dir():continue
  data=archive.read(info)
  if re.search(rb'(gh[pousr]_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{36,})',data):failures.append([name,'possible credential; value withheld'])
  if any(value in data for value in old):
   if name.startswith(('share/doc/','share/man/','share/licenses/')):warnings.append([name,'old-prefix documentation reference'])
   else:failures.append([name,'old runtime prefix'])
  if name=='etc/codex-build.json':
   try:config=json.loads(data)
   except Exception:config={}
   metadata_verified=(config.get('applicationId')==package and config.get('nativePrefix')==lock['identity']['nativePrefix'] and config.get('sourceApp')==lock['app']['commit'] and config.get('sourcePackages')==lock['packages']['commit'])
   if not metadata_verified:failures.append([name,'identity/source metadata mismatch'])
  if data.startswith(b'#!') and (f'{package}/{package}.app.'.encode() in data or f'{package}/.app.'.encode() in data):
   failures.append([name,'component class incorrectly resolved against installation ID'])
  if data.startswith(b'\x7fELF'):
   if len(data)<52 or data[5]!=1:failures.append([name,'invalid ELF format']);continue
   bits=data[4];machine=struct.unpack_from('<H',data,18)[0]
   auxiliary=name=='libexec/proot/loader32' and bits==1 and machine==40
   if auxiliary:
    helpers.append({'path':name,'architecture':'ARM32 proot compatibility loader'})
   elif bits==2 and machine==183:elf64+=1
   else:failures.append([name,'unexpected non-aarch64 native ELF']);continue
   if bits==2:
    if len(data)<64:failures.append([name,'truncated ELF64']);continue
    off=struct.unpack_from('<Q',data,32)[0];step=struct.unpack_from('<H',data,54)[0];count=struct.unpack_from('<H',data,56)[0];minimum=56
   else:
    off=struct.unpack_from('<I',data,28)[0];step=struct.unpack_from('<H',data,42)[0];count=struct.unpack_from('<H',data,44)[0];minimum=32
   if step<minimum and count:failures.append([name,'invalid ELF program-header size']);continue
   for n in range(count):
    pos=off+n*step
    if pos+minimum>len(data):failures.append([name,'truncated ELF headers']);break
    if struct.unpack_from('<I',data,pos)[0]==3:
     start=struct.unpack_from('<Q' if bits==2 else '<I',data,pos+(8 if bits==2 else 4))[0]
     length=struct.unpack_from('<Q' if bits==2 else '<I',data,pos+(32 if bits==2 else 16))[0]
     expected=b'/system/bin/linker' if auxiliary else b'/system/bin/linker64'
     if data[start:start+length].rstrip(b'\0')!=expected:failures.append([name,'unexpected native interpreter'])
  if name.startswith('etc/apt/') and name.endswith(('.list','.sources')):
   active=[line for line in data.decode(errors='replace').splitlines() if line.strip() and not line.lstrip().startswith('#')]
   if active:failures.append([name,'unapproved native binary repository'])
 for required in ['bin/bash','bin/sh','bin/env','bin/curl','bin/proot','libexec/proot/loader']:
  if required not in layout['files']|layout['link_paths']:failures.append([required,'required bootstrap entry missing'])
 for required in ['SYMLINKS.txt','etc/codex-build.json','etc/apt/apt.conf.d/99-codex-source-isolation']:
  if required not in layout['files']:failures.append([required,'must be an actual regular ZIP file, not a link'])
 if not metadata_verified:failures.append(['etc/codex-build.json','required source metadata was not verified'])
 if elf64<10:failures.append(['bootstrap','unexpectedly few aarch64 native programs'])
report={'auditVersion':2,'applicationId':package,'prefix':prefix.decode(),'architecture':'aarch64','sha256':hashlib.sha256(a.archive.read_bytes()).hexdigest(),'archiveBytes':a.archive.stat().st_size,'uncompressedBytes':size,'nativeAarch64ElfFiles':elf64,'auxiliaryElfFiles':helpers,'symlinkCount':len(layout['links']),'metadataVerified':metadata_verified,'failures':failures,'documentationWarnings':warnings,'staticChecksPassed':not failures,'deviceRuntimeTested':False}
a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='documentationWarnings'},indent=2))
if failures:raise SystemExit(1)
