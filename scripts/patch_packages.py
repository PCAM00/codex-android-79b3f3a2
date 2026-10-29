#!/usr/bin/env python3
"""Retarget source build properties, never patch prebuilt executables."""
from pathlib import Path
import argparse, json
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--lock',type=Path,default=Path('source-lock.json'));a=p.parse_args()
lock=json.loads(a.lock.read_text());package=lock['identity']['applicationId']
assert package=='io.cdxbox' and package not in lock['neverModifyPackages']
props=a.source/'scripts/properties.sh'
text=props.read_text()
old='TERMUX_APP__PACKAGE_NAME="com.termux"'
assert text.count(old)==1,'Pinned source layout changed'
props.write_text(text.replace(old,f'TERMUX_APP__PACKAGE_NAME="{package}"'))
bootstrap=a.source/'scripts/build-bootstraps.sh';text=bootstrap.read_text()
# Minimal audited repairs to the pinned official script; no unmerged fork is executed.
old='add_termux_bootstrap_second_stage_files "$package_arch"'
assert text.count(old)==1
text=text.replace(old,'add_termux_bootstrap_second_stage_files "$TERMUX_ARCH"')
for part in ['data','control']:
 old=f'''\t\t\telif [ -f "./{part}.tar.gz" ]; then
\t\t\t\t{part}_archive="{part}.tar.gz"'''
 new=old+f'''
\t\t\telif [ -f "./{part}.tar.zst" ]; then
\t\t\t\t{part}_archive="{part}.tar.zst"'''
 assert text.count(old)==1
 text=text.replace(old,new)
bootstrap.write_text(text)
print('Source retargeted to',package,'; existing com.termux binaries will not be reused.')
