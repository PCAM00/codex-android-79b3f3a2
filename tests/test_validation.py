#!/usr/bin/env python3
"""Structural regression tests. All ZIP/AXML examples are synthetic, not APK runtime evidence."""
from pathlib import Path
import io,json,struct,subprocess,sys,tempfile,zipfile
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo/'scripts'))
from bootstrap_validation import validate_zip_links
from apk_validation import validate_bindings

def zbytes(rows,entries=None):
 stream=io.BytesIO()
 with zipfile.ZipFile(stream,'w') as z:
  z.writestr('SYMLINKS.txt',rows)
  for name,data in (entries or {'bin/bash':b'fixture'}).items():z.writestr(name,data)
 stream.seek(0);return stream

def rejected(rows,entries=None):
 try:
  with zipfile.ZipFile(zbytes(rows,entries)) as z:validate_zip_links(z,strict_names=True)
 except ValueError:return
 raise AssertionError('Invalid link table accepted: '+repr(rows))
with zipfile.ZipFile(zbytes('bash←./bin/sh\n')) as z:assert validate_zip_links(z,strict_names=True)['link_paths']=={'bin/sh'}
for rows in ['', 'bash←bin/bash\n','bash←bin/sh←extra\n','←bin/sh\n','bash←\n','bash←bin/sh\nbash←./bin/sh\n','bash←../sh\n','target←foo\ntarget←foo/bar\n']:
 rejected(rows)
rejected('target←folder\n',{'folder/file':b'data'})
print('PASS malformed, duplicate, colliding and parent-conflicting symlink tables are rejected')

classes={'com.termux.app.TermuxApplication','com.termux.app.TermuxActivity','com.termux.app.activities.SettingsActivity','com.termux.app.TermuxService','com.termux.app.RunCommandService','com.termux.filepicker.TermuxDocumentsProvider','com.termux.app.TermuxOpenReceiver$ContentProvider'}
manifest='''E: manifest (line=1)
  A: package="io.cdxbox"
  A: android:sharedUserId(0x0101000b)="io.cdxbox"
  E: permission (line=2)
    A: android:name(0x01010003)="io.cdxbox.permission.RUN_COMMAND"
    A: android:protectionLevel(0x01010009)=(type 0x11)0x1
  E: application (line=3)
    A: android:name(0x01010003)="com.termux.app.TermuxApplication"
    E: activity (line=4)
      A: android:name(0x01010003)="com.termux.app.TermuxActivity"
      E: intent-filter (line=5)
        E: action (line=6)
          A: android:name(0x01010003)="android.intent.action.MAIN"
        E: category (line=7)
          A: android:name(0x01010003)="android.intent.category.LAUNCHER"
    E: activity-alias (line=8)
      A: android:name(0x01010003)="com.termux.HomeActivity"
      A: android:targetActivity(0x01010202)="com.termux.app.TermuxActivity"
    E: activity (line=9)
      A: android:name(0x01010003)="com.termux.app.activities.SettingsActivity"
    E: service (line=10)
      A: android:name(0x01010003)="com.termux.app.TermuxService"
    E: service (line=11)
      A: android:name(0x01010003)="com.termux.app.RunCommandService"
      A: android:permission(0x01010006)="io.cdxbox.permission.RUN_COMMAND"
      E: intent-filter (line=12)
        E: action (line=13)
          A: android:name(0x01010003)="io.cdxbox.RUN_COMMAND"
    E: provider (line=14)
      A: android:name(0x01010003)="com.termux.filepicker.TermuxDocumentsProvider"
      A: android:authorities(0x01010018)="io.cdxbox.documents"
      A: android:permission(0x01010006)="android.permission.MANAGE_DOCUMENTS"
    E: provider (line=15)
      A: android:name(0x01010003)="com.termux.app.TermuxOpenReceiver$ContentProvider"
      A: android:authorities(0x01010018)="io.cdxbox.files"
      A: android:permission(0x01010006)="io.cdxbox.permission.RUN_COMMAND"
'''
shortcuts='E: shortcuts (line=1)\n'+''.join('  E: shortcut (line=2)\n    E: intent (line=3)\n      A: android:targetPackage(0x01010021)="io.cdxbox"\n      A: android:targetClass(0x01010022)="'+name+'"\n' for name in ['com.termux.app.TermuxActivity','com.termux.app.TermuxActivity','com.termux.app.activities.SettingsActivity'])
badging="application-label:'Codex'\nlaunchable-activity: name='com.termux.app.TermuxActivity' label='Codex' icon='icon.png'\n"
errors,info=validate_bindings(manifest,badging,classes,shortcuts);assert errors==[],errors
assert info['launcherLabel']=='Codex' and info['compiledShortcutsChecked']==3
for wrong in [manifest.replace('="com.termux.app.TermuxApplication"','="io.cdxbox.app.TermuxApplication"'),manifest.replace('="com.termux.app.TermuxActivity"','="io.cdxbox.app.TermuxActivity"')]:
 assert validate_bindings(wrong,badging,classes,shortcuts)[0]
assert validate_bindings(manifest,badging.replace("label='Codex'","label='Wrong'"),classes,shortcuts)[0]
assert validate_bindings(manifest,badging,classes,shortcuts.replace('targetPackage(0x01010021)="io.cdxbox"','targetPackage(0x01010021)="com.termux"',1))[0]
assert validate_bindings(manifest.replace('targetActivity(0x01010202)="com.termux.app.TermuxActivity"','targetActivity(0x01010202)="com.termux.DoesNotExist"'),badging,classes,shortcuts)[0]
print('PASS actual application, launcher, alias and compiled-shortcut bindings are checked against DEX')

with tempfile.TemporaryDirectory(prefix='codex-validator-test-',dir=repo.parent) as directory:
 temp=Path(directory).resolve();assert temp.parent==repo.parent.resolve()
 data=bytearray(64);data[:4]=b'\x7fELF';data[4]=2;data[5]=1;struct.pack_into('<H',data,18,183)
 archive=temp/'synthetic-negative.zip'
 with zipfile.ZipFile(archive,'w') as z:
  z.writestr('SYMLINKS.txt','bash←bin/sh\n/dev/null←etc/codex-build.json\n')
  for name in ['bin/bash','bin/env','bin/curl','bin/proot','libexec/proot/loader']+[f'lib/fixture{i}.so' for i in range(6)]:z.writestr(name,data)
  z.writestr('etc/apt/apt.conf.d/99-codex-source-isolation','fixture')
 result=subprocess.run(['python3',str(repo/'scripts/audit_bootstrap.py'),str(archive),'--report',str(temp/'synthetic-report.json'),'--lock',str(repo/'source-lock.json')],stdout=subprocess.DEVNULL)
 assert result.returncode!=0
 report=json.loads((temp/'synthetic-report.json').read_text());assert not report['staticChecksPassed'] and not report['metadataVerified']
 assert any(row[0]=='etc/codex-build.json' for row in report['failures'])
print('PASS link-only metadata cannot masquerade as a verified identity/source JSON file')
print('Structural regression tests complete; no real APK/native-runtime claim is made.')
