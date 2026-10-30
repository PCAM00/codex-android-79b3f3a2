"""Bootstrap ZIP/link validation matching TermuxInstaller's deferred symlink creation."""
from pathlib import PurePosixPath

def normalize_path(value, *, allow_root=False):
    if not isinstance(value,str) or '\x00' in value or value.startswith('/'):
        raise ValueError('Unsafe bootstrap path')
    path=PurePosixPath(value)
    if '..' in path.parts:
        raise ValueError('Parent traversal in bootstrap path')
    normalized=path.as_posix()
    if normalized=='.':
        if allow_root:return ''
        raise ValueError('Empty bootstrap path')
    return normalized

def parents(value):
    return {p.as_posix() for p in PurePosixPath(value).parents if p.as_posix()!='.'}

def validate_zip_links(archive, *, strict_names=False):
    entries={};files=set();directories=set();link_info=None
    for info in archive.infolist():
        name=normalize_path(info.filename,allow_root=info.is_dir())
        if not name:
            if strict_names:raise ValueError('Noncanonical root ZIP entry')
            continue
        canonical=name+('/' if info.is_dir() else '')
        if strict_names and info.filename!=canonical:
            raise ValueError('Noncanonical final ZIP entry: '+info.filename)
        if name in entries:
            raise ValueError('Duplicate normalized ZIP entry: '+name)
        entries[name]=info
        directories.update(parents(name))
        if info.is_dir():directories.add(name)
        else:files.add(name)
        if name=='SYMLINKS.txt':
            if info.is_dir():raise ValueError('SYMLINKS.txt must be a regular file')
            link_info=info
    if files & directories:
        raise ValueError('ZIP file/directory collision: '+sorted(files&directories)[0])
    if link_info is None:raise ValueError('Missing SYMLINKS.txt')
    rows=archive.read(link_info).decode('utf-8').splitlines()
    if not rows:raise ValueError('Empty symlink table would fail TermuxInstaller')
    links=[];destinations=set();link_parents=set()
    for row in rows:
        if row.count('←')!=1:raise ValueError('Malformed symlink line')
        target,raw_dest=row.split('←')
        if not target or not raw_dest or '\x00' in target or raw_dest.endswith('/'):
            raise ValueError('Empty/invalid symlink field')
        dest=normalize_path(raw_dest)
        if dest in destinations:raise ValueError('Duplicate symlink destination: '+dest)
        destinations.add(dest);link_parents.update(parents(dest));links.append((target,dest))
    occupied=files|directories|link_parents
    collision=destinations&occupied
    if collision:raise ValueError('Symlink destination would already exist: '+sorted(collision)[0])
    if link_parents&files:raise ValueError('A symlink parent is a regular ZIP file')
    return {'entries':entries,'files':files,'directories':directories,'links':links,'link_paths':destinations}
