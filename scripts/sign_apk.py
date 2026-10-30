#!/usr/bin/env python3
"""Sign the audited unsigned APK in an isolated job; never log signing secrets."""
from pathlib import Path
import argparse,base64,hashlib,json,os,shutil,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=Path('unsigned/Codex-unsigned.apk'));p.add_argument('--bootstrap',type=Path,default=Path('unsigned/bootstrap-aarch64.zip'));p.add_argument('--aapt',required=True);p.add_argument('--apksigner',required=True);p.add_argument('--output',type=Path,default=Path('dist'));a=p.parse_args()
os.umask(0o077)
prior=json.loads(Path('unsigned/unsigned-audit.json').read_text())
assert prior['staticChecksPassed'] and prior['applicationId']=='io.cdxbox'
assert hashlib.sha256(a.input.read_bytes()).hexdigest()==prior['apkSha256']
store=base64.b64decode(os.environ['CODEX_KEYSTORE'],validate=True)
assert os.environ.get('CODEX_STORE_PASSWORD') and len(store)>1000
a.output.mkdir(parents=True,exist_ok=True)
result=a.output/'Codex-android-arm64.apk'
with tempfile.TemporaryDirectory(prefix='codex-sign-',dir=os.environ.get('RUNNER_TEMP')) as temporary:
 root=Path(temporary).resolve();assert root.is_dir() and root.name.startswith('codex-sign-')
 keystore=root/'signing.p12';keystore.write_bytes(store);keystore.chmod(0o600)
 env=dict(os.environ);env.pop('CODEX_KEYSTORE',None)
 subprocess.run([a.apksigner,'sign','--ks',str(keystore),'--ks-type','PKCS12','--ks-key-alias','codex','--ks-pass','env:CODEX_STORE_PASSWORD','--key-pass','env:CODEX_STORE_PASSWORD','--v1-signing-enabled','true','--v2-signing-enabled','true','--out',str(result),str(a.input)],env=env,check=True)
os.environ.pop('CODEX_KEYSTORE',None)
os.environ.pop('CODEX_STORE_PASSWORD',None)
subprocess.run(['python3','scripts/audit_apk.py',str(result),'--bootstrap',str(a.bootstrap),'--aapt',a.aapt,'--apksigner',a.apksigner,'--require-signed','--report',str(a.output/'apk-report.json')],check=True)
for source in ['source-lock.json','signing-certificate.json']:
 shutil.copyfile(source,a.output/source)
shutil.copyfile('unsigned/bootstrap-report.json',a.output/'bootstrap-report.json')
(a.output/'SHA256SUMS').write_text(hashlib.sha256(result.read_bytes()).hexdigest()+'  '+result.name+'\n')
(a.output/'INSTALL-NOTES.txt').write_text('Codex (io.cdxbox) — independent Termux-derived runtime.\nThis is a custom build, not an official OpenAI Android app.\nIt must not replace com.termux or com.dsharnessmobile.shell.\nStatic APK/bootstrap/signature checks passed; Android installation and runtime tests are still required.\nFirst launch installs its own private bootstrap. No API key is embedded.\nNative APT network sources are intentionally disabled: only matching native packages may be used.\nCodex CLI and graphical client setup are subsequent steps after the runtime is verified.\n')
print('Dedicated signing complete; only APK, public certificate metadata, checksums and reports are in dist.')
