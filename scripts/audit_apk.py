#!/usr/bin/env python3
"""Audit actual APK entry points, DEX classes, ABI, embedded bootstrap and signing identity."""
from pathlib import Path
import argparse,hashlib,json,re,struct,subprocess,zipfile
from apk_validation import validate_bindings
p=argparse.ArgumentParser();p.add_argument('apk',type=Path);p.add_argument('--bootstrap',type=Path,required=True);p.add_argument('--aapt',required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--certificate',type=Path,default=Path('signing-certificate.json'));p.add_argument('--apksigner');p.add_argument('--require-signed',action='store_true');a=p.parse_args()
expected='io.cdxbox';failures=[]
badging=subprocess.check_output([a.aapt,'dump','badging',str(a.apk)],text=True)
manifest=subprocess.check_output([a.aapt,'dump','xmltree',str(a.apk),'AndroidManifest.xml'],text=True)
def value(pattern,text):
 match=re.search(pattern,text,re.M);return match[1] if match else None
package=value(r"^package: name='([^']+)'",badging)
label=value(r"^application-label:'([^']+)'",badging)
min_sdk=value(r"^sdkVersion:'([^']+)'",badging);target_sdk=value(r"^targetSdkVersion:'([^']+)'",badging)
shared_uid=value(r'android:sharedUserId[^\n]*?="([^"]+)"',manifest)
if package!=expected:failures.append('Final APK applicationId mismatch')
if label!='Codex':failures.append('Final application label mismatch')
if min_sdk!='24' or target_sdk!='28':failures.append('Unexpected min/target SDK')
for item in ['com.termux.documents','com.termux.files','com.termux.permission.RUN_COMMAND','com.dsharnessmobile.shell']:
 if '"'+item+'"' in manifest:failures.append('Old app identity in final manifest: '+item)
required_classes={'com.termux.app.TermuxApplication','com.termux.app.TermuxActivity','com.termux.app.TermuxService','com.termux.app.RunCommandService','com.termux.app.TermuxInstaller','com.termux.terminal.JNI','com.termux.filepicker.TermuxDocumentsProvider','com.termux.app.TermuxOpenReceiver$ContentProvider'}
def dex_classes(data):
 if not data.startswith(b'dex\n'):raise ValueError('Unexpected dex format')
 string_count,string_off=struct.unpack_from('<II',data,56);type_count,type_off=struct.unpack_from('<II',data,64);class_count,class_off=struct.unpack_from('<II',data,96)
 result=set()
 for index in range(class_count):
  cls=struct.unpack_from('<I',data,class_off+index*32)[0]
  if cls>=type_count:raise ValueError('Invalid DEX type index')
  string_index=struct.unpack_from('<I',data,type_off+cls*4)[0]
  if string_index>=string_count:raise ValueError('Invalid DEX string index')
  at=struct.unpack_from('<I',data,string_off+string_index*4)[0]
  for _ in range(5):
   b=data[at];at+=1
   if not b&128:break
  end=data.index(b'\0',at);descriptor=data[at:end].decode('utf-8',errors='replace')
  if descriptor.startswith('L') and descriptor.endswith(';'):result.add(descriptor[1:-1].replace('/','.'))
 return result
classes=set();abis=set();elf_count=0;bootstrap_match=False;bootstrap=a.bootstrap.read_bytes();shortcut_names=[]
with zipfile.ZipFile(a.apk) as apk:
 if apk.testzip():failures.append('APK ZIP CRC failure')
 for name in apk.namelist():
  if re.fullmatch(r'classes\d*\.dex',name):classes.update(dex_classes(apk.read(name)))
  if name.startswith('lib/') and name.endswith('.so'):
   abis.add(name.split('/')[1]);data=apk.read(name);elf_count+=1
   if not data.startswith(b'\x7fELF') or data[4]!=2 or struct.unpack_from('<H',data,18)[0]!=183:failures.append('Wrong JNI ELF ABI: '+name)
   if name.endswith('/libtermux-bootstrap.so'):bootstrap_match=bootstrap in data
  if name.startswith('res/xml') and name.endswith('/shortcuts.xml'):shortcut_names.append(name)
  if name.endswith(('.jks','.p12')):failures.append('Unexpected signing-key container inside APK')
if abis!={'arm64-v8a'}:failures.append('APK includes missing/unexpected native ABI: '+str(sorted(abis)))
if not bootstrap_match:failures.append('JNI bootstrap payload is not byte-identical to the audited ZIP')
missing=sorted(required_classes-classes)
if missing:failures.append('Missing required runtime/JNI classes: '+','.join(missing))
shortcuts=''
if len(shortcut_names)!=1:failures.append('Expected one compiled shortcuts XML resource')
else:shortcuts=subprocess.check_output([a.aapt,'dump','xmltree',str(a.apk),shortcut_names[0]],text=True)
binding_errors,binding_info=validate_bindings(manifest,badging,classes,shortcuts,expected);failures.extend(binding_errors)
certificate=None
if a.require_signed:
 if not a.apksigner:raise SystemExit('--apksigner is required for signed audit')
 signed=subprocess.check_output([a.apksigner,'verify','--verbose','--print-certs',str(a.apk)],text=True)
 certificate=value(r'Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]+)',signed)
 expected_cert=json.loads(a.certificate.read_text())['certificateSha256']
 if certificate is None or certificate.lower()!=expected_cert:failures.append('Dedicated signing certificate mismatch')
report={'auditVersion':2,'applicationId':package,'applicationLabel':label,**binding_info,'minSdk':min_sdk,'targetSdk':target_sdk,'sharedUserId':shared_uid,'nativeAbis':sorted(abis),'jniLibraries':elf_count,'requiredClassesPresent':not missing,'manifestBindingsVerified':not binding_errors,'bootstrapEmbeddedByteIdentically':bootstrap_match,'bootstrapSha256':hashlib.sha256(bootstrap).hexdigest(),'apkSha256':hashlib.sha256(a.apk.read_bytes()).hexdigest(),'certificateSha256':certificate,'signatureChecked':a.require_signed,'staticChecksPassed':not failures,'deviceRuntimeTested':False,'failures':failures}
a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if failures:raise SystemExit(1)
