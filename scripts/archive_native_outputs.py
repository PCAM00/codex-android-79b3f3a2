#!/usr/bin/env python3
"""Archive native outputs into one POSIX tar so Debian epoch colons are preserved safely."""
from pathlib import Path
import argparse,hashlib,json,tarfile
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
files=sorted(a.source.glob('*.deb')) if a.source.is_dir() else []
a.output.parent.mkdir(parents=True,exist_ok=True)
manifest=[]
with tarfile.open(a.output,'w') as tar:
 for file in files:
  if not file.is_file() or file.is_symlink():raise SystemExit('Unexpected native output type')
  tar.add(file,arcname=file.name,recursive=False)
  with file.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  manifest.append({'file':file.name,'bytes':file.stat().st_size,'sha256':digest})
a.output.with_suffix('.manifest.json').write_text(json.dumps({'nativePackages':manifest},indent=2)+'\n')
print('Archived native package files:',len(files),'without renaming Debian package versions')
