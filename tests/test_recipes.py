#!/usr/bin/env python3
"""Offline recipe tests using synthetic fixtures; this does NOT build or validate a runnable APK."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,tempfile,xml.etree.ElementTree as ET,zipfile
p=argparse.ArgumentParser();p.add_argument('--app-source',type=Path,required=True);a=p.parse_args()
repo=Path(__file__).resolve().parents[1];lock=json.loads((repo/'source-lock.json').read_text())
workspace=repo.parent.resolve()
with tempfile.TemporaryDirectory(prefix='codex-recipe-test-',dir=workspace) as temporary:
 temp=Path(temporary).resolve();assert temp.parent==workspace
 raw=temp/'fixture-raw.zip';out=temp/'fixture-final.zip';again=temp/'fixture-final-again.zip'
 with zipfile.ZipFile(raw,'w') as z:
  z.writestr('SYMLINKS.txt','bash←./bin/sh\n')
  z.writestr('bin/termux-wake-lock','#!/data/data/io.cdxbox/files/usr/bin/sh\nam startservice io.cdxbox/io.cdxbox.app.TermuxService\n')
  z.writestr('etc/apt/sources.list','deb https://example.invalid/official-old-prefix stable main\n')
 for src,dest,extra in [(raw,out,[]),(out,again,['--require-source-metadata'])]:
  subprocess.run(['python3',str(repo/'scripts/finalize_bootstrap.py'),str(src),str(dest),'--lock',str(repo/'source-lock.json'),*extra],check=True,stdout=subprocess.DEVNULL)
 with zipfile.ZipFile(again) as z:
  assert len(z.namelist())==len(set(z.namelist()))
  assert b'io.cdxbox/com.termux.app.TermuxService' in z.read('bin/termux-wake-lock')
  assert all(not line.strip() or line.lstrip().startswith('#') for line in z.read('etc/apt/sources.list').decode().splitlines())
  assert b'Dir::Etc::sourcelist "/dev/null";' in z.read('etc/apt/apt.conf.d/99-codex-source-isolation')
 print('PASS synthetic ZIP finalization: component targets, repository isolation, idempotence')
 mismatch=temp/'fixture-wrong-source.zip'
 with zipfile.ZipFile(mismatch,'w') as z:z.writestr('etc/codex-build.json',json.dumps({'applicationId':'com.termux'}))
 r=subprocess.run(['python3',str(repo/'scripts/finalize_bootstrap.py'),str(mismatch),str(temp/'rejected.zip'),'--lock',str(repo/'source-lock.json'),'--require-source-metadata'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert r.returncode!=0
 print('PASS incompatible bootstrap source metadata is rejected')
 source=temp/'app-source';shutil.copytree(a.app_source,source)
 # This intentionally synthetic report is confined to the temporary source-transform test.
 synthetic={'staticChecksPassed':True,'applicationId':'io.cdxbox','sha256':hashlib.sha256(again.read_bytes()).hexdigest(),'syntheticFixture':True}
 report=temp/'fixture-report.json';report.write_text(json.dumps(synthetic))
 subprocess.run(['python3',str(repo/'scripts/patch_app.py'),str(source),'--bootstrap',str(again),'--bootstrap-report',str(report),'--lock',str(repo/'source-lock.json'),'--certificate',str(repo/'signing-certificate.json'),'--build-number','1'],check=True,stdout=subprocess.DEVNULL)
 gradle=(source/'app/build.gradle').read_text();constants=(source/'termux-shared/src/main/java/com/termux/shared/termux/TermuxConstants.java').read_text()
 assert 'applicationId "io.cdxbox"' in gradle and 'abiFilters "arm64-v8a"' in gradle
 assert 'def downloadBootstrap(' not in gradle and 'dependsOn(validateBootstrap)' in gradle
 assert 'TERMUX_PACKAGE_NAME = "io.cdxbox";' in constants
 assert 'TERMUX_ACTIVITY_NAME = "com.termux.app.TermuxActivity";' in constants
 assert 'RUN_COMMAND_SERVICE_NAME = "com.termux.app.RunCommandService";' in constants
 manifest=ET.fromstring((source/'app/src/main/AndroidManifest.xml').read_text());ns='{http://schemas.android.com/apk/res/android}'
 assert manifest.attrib['package']=='com.termux'
 assert manifest.find('application').attrib[ns+'name']=='com.termux.app.TermuxApplication'
 for e in manifest.iter():
  for key in [ns+'name',ns+'targetActivity',ns+'parentActivityName']:
   assert not e.attrib.get(key,'').startswith('.')
 shortcuts=ET.fromstring((source/'app/src/main/res/xml/shortcuts.xml').read_text())
 assert all(i.attrib[ns+'targetPackage']=='io.cdxbox' for i in shortcuts.iter('intent'))
 assert all(i.attrib[ns+'targetClass'].startswith('com.termux.') for i in shortcuts.iter('intent'))
 assert (source/'app/src/main/cpp/bootstrap-aarch64.zip').read_bytes()==again.read_bytes()
 print('PASS source transformation: independent install ID, unchanged Java/JNI namespace, strict bootstrap hash')
workflow=json.loads((repo/'.github/workflows/apk.yml').read_text())
assert set(workflow['on'])=={'workflow_dispatch'}
assert all(job['runs-on']=='ubuntu-24.04' for job in workflow['jobs'].values())
assert 'secrets.' not in json.dumps(workflow['jobs']['assemble'])
assert workflow['jobs']['sign']['needs']=='assemble'
secret_steps=[s for s in workflow['jobs']['sign']['steps'] if 'secrets.' in json.dumps(s)]
assert len(secret_steps)==1
print('PASS workflow policy: standard runners, manual trigger, isolated signing secrets')
print('Offline tests complete. No installable APK was produced by these tests.')
