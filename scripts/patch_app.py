#!/usr/bin/env python3
"""Fork installation identity while preserving the upstream Java/JNI namespace."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,zipfile
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--bootstrap',type=Path,required=True);p.add_argument('--bootstrap-report',type=Path,required=True);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));p.add_argument('--certificate',type=Path,default=Path('signing-certificate.json'));p.add_argument('--build-number',type=int,default=1);a=p.parse_args()
lock=json.loads(a.lock.read_text());identity=lock['identity'];package=identity['applicationId'];namespace='com.termux'
assert package=='io.cdxbox' and package not in lock['neverModifyPackages'] and len(package)<=10
assert subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip()==lock['app']['commit']
report=json.loads(a.bootstrap_report.read_text());digest=hashlib.sha256(a.bootstrap.read_bytes()).hexdigest()
assert report['staticChecksPassed'] and report['applicationId']==package and report['sha256']==digest
with zipfile.ZipFile(a.bootstrap) as archive:
 stages=[i.filename for i in archive.infolist() if not i.is_dir() and i.filename.endswith('/termux-bootstrap-second-stage.sh')]
 assert len(stages)==1,'Expected exactly one bootstrap initialization entry point'
 second_stage=stages[0]
 assert archive.read(second_stage).startswith(('#!'+identity['nativePrefix']+'/bin/bash').encode())
certificate=json.loads(a.certificate.read_text());assert certificate['applicationId']==package
fingerprint=certificate['certificateSha256'];assert re.fullmatch('[0-9a-f]{64}',fingerprint)
assert 1<=a.build_number<1000000

def one(text,old,new):
 if text.count(old)!=1:raise RuntimeError(f'Pinned source expectation changed: {old[:90]}')
 return text.replace(old,new)

gradle=a.source/'app/build.gradle';text=gradle.read_text()
text=one(text,'applicationId "com.termux"',f'applicationId "{package}"\n        ndk {{ abiFilters "arm64-v8a" }}')
text=one(text,'manifestPlaceholders.TERMUX_PACKAGE_NAME = "com.termux"',f'manifestPlaceholders.TERMUX_PACKAGE_NAME = "{package}"')
text=one(text,'manifestPlaceholders.TERMUX_APP_NAME = "Termux"','manifestPlaceholders.TERMUX_APP_NAME = "Codex"')
text=one(text,'versionCode 1002',f'versionCode {1002000+a.build_number}')
text=one(text,'versionName "0.118.3"',f'versionName "0.118.3-codex.{a.build_number}"')
text=one(text,"include 'x86', 'x86_64', 'armeabi-v7a', 'arm64-v8a'","include 'arm64-v8a'")
start=text.index('def downloadBootstrap(');end=text.index('afterEvaluate {',start)
validate='''// Only the source-built, audited io.cdxbox bootstrap is accepted. No upstream fallback.
task validateBootstrap() {
    doLast {
        def bootstrap = file("src/main/cpp/bootstrap-aarch64.zip")
        if (!bootstrap.isFile()) throw new GradleException("Missing custom bootstrap")
        def actual = java.security.MessageDigest.getInstance("SHA-256").digest(bootstrap.bytes).encodeHex().toString()
        if (actual != "EXPECTED_SHA") throw new GradleException("Custom bootstrap SHA-256 mismatch")
    }
}

'''.replace('EXPECTED_SHA',digest)
text=text[:start]+validate+text[end:]
text=one(text,'dependsOn(downloadBootstraps)','dependsOn(validateBootstrap)')
gradle.write_text(text)

constants=a.source/'termux-shared/src/main/java/com/termux/shared/termux/TermuxConstants.java';text=constants.read_text()
text=one(text,'public static final String TERMUX_PACKAGE_NAME = "com.termux";',f'public static final String TERMUX_PACKAGE_NAME = "{package}";')
text=one(text,'public static final String TERMUX_APP_NAME = "Termux";','public static final String TERMUX_APP_NAME = "Codex";')
classes={'TERMUX_ACTIVITY_NAME':'.app.TermuxActivity','TERMUX_SETTINGS_ACTIVITY_NAME':'.app.activities.SettingsActivity','TERMUX_SERVICE_NAME':'.app.TermuxService','RUN_COMMAND_SERVICE_NAME':'.app.RunCommandService'}
for name,suffix in classes.items():
 text=one(text,f'public static final String {name} = TERMUX_PACKAGE_NAME + "{suffix}";',f'public static final String {name} = "{namespace}{suffix}";')
pattern=r'(public static final String APK_RELEASE_GITHUB_SIGNING_CERTIFICATE_SHA256_DIGEST = ")[0-9A-F]+(";)'
text,n=re.subn(pattern,lambda m:m[1]+fingerprint.upper()+m[2],text);assert n==1
constants.write_text(text)

for relative in ['app/src/main/res/values/strings.xml','termux-shared/src/main/res/values/strings.xml']:
 file=a.source/relative;text=file.read_text()
 text=one(text,'<!ENTITY TERMUX_PACKAGE_NAME "com.termux">',f'<!ENTITY TERMUX_PACKAGE_NAME "{package}">')
 text=one(text,'<!ENTITY TERMUX_APP_NAME "Termux">','<!ENTITY TERMUX_APP_NAME "Codex">')
 text=text.replace('<!ENTITY TERMUX_PREFIX_DIR_PATH "/data/data/com.termux/files/usr">',f'<!ENTITY TERMUX_PREFIX_DIR_PATH "{identity["nativePrefix"]}">')
 file.write_text(text)
shortcuts=a.source/'app/src/main/res/xml/shortcuts.xml';text=shortcuts.read_text()
assert text.count('android:targetPackage="com.termux"')==3
text=text.replace('android:targetPackage="com.termux"',f'android:targetPackage="{package}"')
text=one(text,'android:name="com.termux.app.failsafe_session"',f'android:name="{package}.app.failsafe_session"')
shortcuts.write_text(text)

manifest=a.source/'app/src/main/AndroidManifest.xml';text=manifest.read_text()
# Fully qualify class-valued attributes so Gradle cannot resolve them against the new applicationId.
text=re.sub(r'(android:(?:name|targetActivity|parentActivityName)=")(\.[^"]+)(")',lambda m:m[1]+namespace+m[2]+m[3],text)
removed=[]
for permission in ['android.permission.READ_LOGS','android.permission.DUMP','android.permission.WRITE_SECURE_SETTINGS','android.permission.PACKAGE_USAGE_STATS']:
 text,n=re.subn(r'^\s*<uses-permission android:name="'+re.escape(permission)+r'"[^\n]*/>\n','\n',text,flags=re.M)
 if n:removed.append(permission)
manifest.write_text(text)
installer=a.source/'app/src/main/java/com/termux/app/TermuxInstaller.java';text=installer.read_text()
text=one(text,'zipEntryName.equals("etc/termux/bootstrap/termux-bootstrap-second-stage.sh")',f'zipEntryName.equals("{second_stage}")')
text=one(text,'TERMUX_PREFIX_DIR_PATH + "/etc/termux/bootstrap/termux-bootstrap-second-stage.sh"',f'TERMUX_PREFIX_DIR_PATH + "/{second_stage}"')
installer.write_text(text)
# Preserve package="com.termux": that is the Java/R namespace, not the final install ID.
assert 'package="com.termux"' in manifest.read_text()
jni=(a.source/'app/src/main/cpp/termux-bootstrap.c').read_text()
assert 'Java_com_termux_app_TermuxInstaller_getZip' in jni
output=a.source/'app/src/main/cpp/bootstrap-aarch64.zip'
if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest()!=digest:raise SystemExit('Unexpected bootstrap already present')
shutil.copyfile(a.bootstrap,output)
info={'applicationId':package,'label':'Codex','javaNamespace':namespace,'architecture':'arm64-v8a','bootstrapSha256':digest,'bootstrapSecondStageRelativePath':second_stage,'certificateSha256':fingerprint,'versionCode':1002000+a.build_number,'versionName':f'0.118.3-codex.{a.build_number}','removedUnusedProtectedPermissions':removed,'deviceRuntimeTested':False}
(a.source/'codex-patch-report.json').write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps(info,indent=2))
