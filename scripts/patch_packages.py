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
old='\tlocal package_name="$2"'
new='''\tlocal runtime_package_name="$2"
\tlocal package_name
\tpackage_name="$(python3 "$TERMUX_PACKAGES_DIRECTORY/scripts/codex_bootstrap_recipes.py" "$TERMUX_PACKAGES_DIRECTORY" --resolve "$runtime_package_name")" || return $?
\techo "[*] Runtime package '$runtime_package_name' uses source recipe '$package_name'"'''
assert text.count(old)==1
text=text.replace(old,new)
old='\t\t# Build packages.\n'
new='''\t\t# Fail before expensive compilation if the legacy bootstrap list contains unknown packages.
\t\tpython3 "$TERMUX_PACKAGES_DIRECTORY/scripts/codex_bootstrap_recipes.py" "$TERMUX_PACKAGES_DIRECTORY" --check "${PACKAGES[@]}" > "$TERMUX_PACKAGES_DIRECTORY/bootstrap-recipe-map.json" || return $?

\t\t# Build packages.
'''
assert text.count(old)==1
text=text.replace(old,new)
old='''\t\t# Extract all debs.
\t\textract_debs "$TERMUX_ARCH" || return $?'''
new='''\t\t# This marker is written only after every requested source recipe completed.
\t\techo "$TERMUX_ARCH" > "$TERMUX_PACKAGES_DIRECTORY/codex-compile-complete.txt"
\t\techo "$TERMUX_PREFIX" >> "$TERMUX_PACKAGES_DIRECTORY/codex-compile-complete.txt"
\t\tgit -C "$TERMUX_PACKAGES_DIRECTORY" rev-parse HEAD >> "$TERMUX_PACKAGES_DIRECTORY/codex-compile-complete.txt" || return $?

\t\t# Preserve all build outputs, but install only the requested runtime dependency closure.
\t\tlocal original_debs_directory="$TERMUX_BUILT_DEBS_DIRECTORY"
\t\tlocal runtime_debs_directory="$BOOTSTRAP_TMPDIR/runtime-debs-$TERMUX_ARCH"
\t\tpython3 "$TERMUX_PACKAGES_DIRECTORY/scripts/codex_select_runtime_debs.py" --input "$original_debs_directory" --output "$runtime_debs_directory" --arch "$TERMUX_ARCH" --report "$TERMUX_PACKAGES_DIRECTORY/runtime-package-selection.json" "${PACKAGES[@]}" || return $?
\t\tTERMUX_BUILT_DEBS_DIRECTORY="$runtime_debs_directory"
\t\textract_debs "$TERMUX_ARCH" || return $?
\t\tTERMUX_BUILT_DEBS_DIRECTORY="$original_debs_directory"'''
assert text.count(old)==1
text=text.replace(old,new)
bootstrap.write_text(text)
import shutil
for original,target in [('bootstrap_recipes.py','codex_bootstrap_recipes.py'),('select_runtime_debs.py','codex_select_runtime_debs.py')]:
 shutil.copyfile(Path(__file__).resolve().parent/original,a.source/'scripts'/target)
print('Source retargeted to',package,'; subpackage mappings and runtime-only packaging enabled.')
