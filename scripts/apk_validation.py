"""Parse AAPT XML-tree output and validate actual Android component bindings."""
import re

CLASS_COMPONENTS={'activity','service','receiver','provider'}
def parse_xmltree(text):
    roots=[];stack=[]
    for line in text.splitlines():
        element=re.match(r'^(\s*)E:\s+(\S+)',line)
        if element:
            depth=len(element[1]);node={'tag':element[2],'attrs':{},'children':[]}
            while stack and stack[-1][0]>=depth:stack.pop()
            (stack[-1][1]['children'] if stack else roots).append(node)
            stack.append((depth,node));continue
        attr=re.match(r'^\s*A:\s+([^\s(=]+)(?:\([^)]*\))?\s*=\s*(.*)$',line)
        if attr and stack:
            raw=attr[2];quoted=re.match(r'"([^"]*)"',raw)
            numeric=re.match(r'(?:\(type [^)]+\))?(0x[0-9A-Fa-f]+)(?:\s|$)',raw)
            value=quoted[1] if quoted else int(numeric[1],16) if numeric else raw
            stack[-1][1]['attrs'][attr[1]]=value
    return roots

def class_name(value,package):
    if not isinstance(value,str) or not value:return None
    if value.startswith('.'):return package+value
    return value if '.' in value else package+'.'+value

def walk(node):
    yield node
    for child in node['children']:yield from walk(child)

def validate_bindings(manifest_text,badging,classes,shortcuts_text,package='io.cdxbox'):
    errors=[];roots=parse_xmltree(manifest_text)
    root=next((n for n in roots if n['tag']=='manifest'),None)
    if not root:return ['Missing parsed Android manifest'],{}
    if root['attrs'].get('package')!=package:errors.append('Manifest package differs from install ID')
    if root['attrs'].get('android:sharedUserId')!=package:errors.append('Shared UID is not independently namespaced')
    app=next((n for n in root['children'] if n['tag']=='application'),None)
    if not app:return errors+['Missing application node'],{}
    actual_application=class_name(app['attrs'].get('android:name'),package)
    if actual_application!='com.termux.app.TermuxApplication' or actual_application not in classes:errors.append('Application is not bound to the expected real DEX class')
    activities={};services={};providers={};bindings=[]
    for node in app['children']:
        tag=node['tag'];attrs=node['attrs']
        if tag in CLASS_COMPONENTS:
            name=class_name(attrs.get('android:name'),package)
            if name not in classes:errors.append(f'{tag} references missing DEX class: {name}')
            bindings.append({'type':tag,'class':name})
            if tag=='activity':activities[name]=node
            if tag=='service':services[name]=node
            if tag=='provider':providers[name]=node
        elif tag=='activity-alias':
            target=class_name(attrs.get('android:targetActivity'),package)
            if target not in activities:errors.append('Activity alias target is not an earlier declared real activity: '+str(target))
    launcher=re.search(r"^launchable-activity:\s+name='([^']+)'[^\n]*?label='([^']*)'",badging,re.M)
    launcher_name=launcher[1] if launcher else None;launcher_label=launcher[2] if launcher else None
    if launcher_name!='com.termux.app.TermuxActivity' or launcher_name not in activities:errors.append('Actual launcher is not the expected declared Termux activity')
    if launcher_label!='Codex':errors.append('Actual launcher label is not Codex')
    if launcher_name in activities:
        nodes=list(walk(activities[launcher_name]));actions={n['attrs'].get('android:name') for n in nodes if n['tag']=='action'};categories={n['attrs'].get('android:name') for n in nodes if n['tag']=='category'}
        if 'android.intent.action.MAIN' not in actions or 'android.intent.category.LAUNCHER' not in categories:errors.append('Launcher activity lacks MAIN/LAUNCHER declaration')
    expected_providers={'com.termux.filepicker.TermuxDocumentsProvider':(package+'.documents','android.permission.MANAGE_DOCUMENTS'),'com.termux.app.TermuxOpenReceiver$ContentProvider':(package+'.files',package+'.permission.RUN_COMMAND')}
    for name,(authority,permission) in expected_providers.items():
        attrs=providers.get(name,{}).get('attrs',{})
        if attrs.get('android:authorities')!=authority or attrs.get('android:permission')!=permission:errors.append('Provider authority or permission mismatch: '+name)
    if 'com.termux.app.TermuxService' not in services:errors.append('Main TermuxService is not declared in the manifest')
    service=services.get('com.termux.app.RunCommandService')
    if not service or service['attrs'].get('android:permission')!=package+'.permission.RUN_COMMAND':errors.append('External command service is missing its independently namespaced permission')
    elif package+'.RUN_COMMAND' not in {n['attrs'].get('android:name') for n in walk(service) if n['tag']=='action'}:errors.append('External command service action mismatch')
    permission=next((n for n in root['children'] if n['tag']=='permission' and n['attrs'].get('android:name')==package+'.permission.RUN_COMMAND'),None)
    level=permission['attrs'].get('android:protectionLevel') if permission else None
    if not (isinstance(level,int) and level&15==1 or level=='dangerous'):errors.append('RUN_COMMAND permission is not declared dangerous')
    shortcuts=parse_xmltree(shortcuts_text);intents=[n for rootnode in shortcuts for n in walk(rootnode) if n['tag']=='intent']
    if len(intents)!=3:errors.append('Unexpected compiled shortcuts intent count')
    for intent in intents:
        attrs=intent['attrs'];target=class_name(attrs.get('android:targetClass'),package)
        if attrs.get('android:targetPackage')!=package:errors.append('Shortcut targets another application package')
        if target not in activities or target not in classes:errors.append('Shortcut targets a missing/undeclared Activity class: '+str(target))
    return errors,{'applicationClass':actual_application,'launcherClass':launcher_name,'launcherLabel':launcher_label,'componentBindings':bindings,'compiledShortcutsChecked':len(intents)}
