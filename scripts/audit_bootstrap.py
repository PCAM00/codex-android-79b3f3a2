#!/usr/bin/env python3
"""Fail closed on broken link metadata, wrong native ABI/prefix or credentials."""
from pathlib import Path
import argparse, hashlib, json, re, struct, zipfile
from bootstrap_validation import normalize_path, validate_zip_links

OLD_PREFIXES = (
    b'/data/data/com.termux/files',
    b'/data/user/0/com.termux/files',
    b'/data/data/com.dsharnessmobile.shell/files',
)


def load_reviewed_prefix_comments():
    """Load repository-owned review evidence, never rules supplied by the archive.

    Missing/malformed evidence fails closed. There is deliberately no CLI override,
    glob matching, language heuristic, or automatic hash refresh.
    """
    try:
        document = json.loads(Path(__file__).with_name('reviewed_prefix_comments.json').read_text(encoding='utf-8'))
        if type(document['schemaVersion']) is not int or document['schemaVersion'] != 1 or not isinstance(document['files'], list):
            raise ValueError('Unsupported review schema')
        reviewed = {}
        for rule in document['files']:
            if set(rule) != {'path', 'sha256', 'sourceDeb', 'review', 'hits'}:
                raise ValueError('Invalid review fields')
            name = rule['path']
            if normalize_path(name) != name or name in reviewed:
                raise ValueError('Noncanonical or duplicate reviewed path')
            if not re.fullmatch(r'[0-9a-f]{64}', rule['sha256']):
                raise ValueError('Invalid whole-file SHA256')
            if not isinstance(rule['review'], str) or not rule['review'].strip():
                raise ValueError('Missing full-context review')
            source = rule['sourceDeb']
            if set(source) != {'file', 'sha256', 'member'} or not all(isinstance(value, str) and value for value in source.values()):
                raise ValueError('Missing source evidence')
            if not re.fullmatch(r'[0-9a-f]{64}', source['sha256']) or not source['member'].endswith('/' + name):
                raise ValueError('Invalid source evidence')
            if not isinstance(rule['hits'], list) or not rule['hits']:
                raise ValueError('Missing exact hit lines')
            previous = 0
            for hit in rule['hits']:
                if set(hit) != {'line', 'content'} or type(hit['line']) is not int or hit['line'] <= previous:
                    raise ValueError('Invalid/duplicate hit line')
                if not isinstance(hit['content'], str) or '\n' in hit['content'] or not any(value in hit['content'].encode('utf-8') for value in OLD_PREFIXES):
                    raise ValueError('Invalid exact hit content')
                previous = hit['line']
            reviewed[name] = rule
        return reviewed
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError('Invalid reviewed-prefix comment allowlist') from error


def reviewed_prefix_comment(name, data, reviewed):
    """Match *all bytes and hits* of an already reviewed non-ELF file.

    Full-file hashing binds the surrounding syntax too: a # inside a heredoc or
    string, a shebang, a C macro, or an altered block-comment delimiter cannot
    inherit a review merely because an old-prefix-bearing line looks the same.
    """
    rule = reviewed.get(name)
    if data.startswith(b'\x7fELF') or rule is None or hashlib.sha256(data).hexdigest() != rule['sha256']:
        return None
    try:
        # LF only, without stripping whitespace or normalizing line endings.
        hits = [{'line': number, 'content': line.decode('utf-8')}
                for number, line in enumerate(data.split(b'\n'), 1)
                if any(value in line for value in OLD_PREFIXES)]
    except UnicodeDecodeError:
        return None
    if not hits or hits != rule['hits']:
        return None
    return rule


def audit_archive(archive, lock):
    """Audit an open ZIP read-only; callers may use an in-memory ZIP for tests."""
    prefix = lock['identity']['nativePrefix'].encode()
    package = lock['identity']['applicationId']
    reviewed = load_reviewed_prefix_comments()
    failures = []; warnings = []; comment_matches = []
    elf64 = 0; helpers = []; size = 0; metadata_verified = False
    if archive.testzip():
        raise SystemExit('Corrupt bootstrap ZIP')
    try:
        layout = validate_zip_links(archive, strict_names=True)
    except ValueError as error:
        raise SystemExit('Bootstrap link/layout audit failed: ' + str(error))
    for name, info in layout['entries'].items():
        size += info.file_size
        if info.is_dir():
            continue
        data = archive.read(info)
        if re.search(rb'(gh[pousr]_[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{36,})', data):
            failures.append([name, 'possible credential; value withheld'])
        if any(value in data for value in OLD_PREFIXES):
            rule = reviewed_prefix_comment(name, data, reviewed)
            if rule is None:
                # No directory exemption: even an ELF or script under share/doc
                # must fail. Only exact, manually reviewed comments may warn.
                failures.append([name, 'old runtime prefix'])
            else:
                lines = ','.join(str(hit['line']) for hit in rule['hits'])
                warnings.append([name, 'reviewed old-prefix comments; whole-file SHA256=' + rule['sha256'] + '; lines=' + lines])
                comment_matches.append(rule)
        if name == 'etc/codex-build.json':
            try:
                config = json.loads(data)
            except Exception:
                config = {}
            metadata_verified = (config.get('applicationId') == package and config.get('nativePrefix') == lock['identity']['nativePrefix'] and config.get('sourceApp') == lock['app']['commit'] and config.get('sourcePackages') == lock['packages']['commit'])
            if not metadata_verified:
                failures.append([name, 'identity/source metadata mismatch'])
        if data.startswith(b'#!') and (f'{package}/{package}.app.'.encode() in data or f'{package}/.app.'.encode() in data):
            failures.append([name, 'component class incorrectly resolved against installation ID'])
        if data.startswith(b'\x7fELF'):
            if len(data) < 52 or data[5] != 1:
                failures.append([name, 'invalid ELF format']); continue
            bits = data[4]; machine = struct.unpack_from('<H', data, 18)[0]
            auxiliary = name == 'libexec/proot/loader32' and bits == 1 and machine == 40
            if auxiliary:
                helpers.append({'path': name, 'architecture': 'ARM32 proot compatibility loader'})
            elif bits == 2 and machine == 183:
                elf64 += 1
            else:
                failures.append([name, 'unexpected non-aarch64 native ELF']); continue
            if bits == 2:
                if len(data) < 64:
                    failures.append([name, 'truncated ELF64']); continue
                off = struct.unpack_from('<Q', data, 32)[0]; step = struct.unpack_from('<H', data, 54)[0]; count = struct.unpack_from('<H', data, 56)[0]; minimum = 56
            else:
                off = struct.unpack_from('<I', data, 28)[0]; step = struct.unpack_from('<H', data, 42)[0]; count = struct.unpack_from('<H', data, 44)[0]; minimum = 32
            if step < minimum and count:
                failures.append([name, 'invalid ELF program-header size']); continue
            for n in range(count):
                pos = off + n * step
                if pos + minimum > len(data):
                    failures.append([name, 'truncated ELF headers']); break
                if struct.unpack_from('<I', data, pos)[0] == 3:
                    start = struct.unpack_from('<Q' if bits == 2 else '<I', data, pos + (8 if bits == 2 else 4))[0]
                    length = struct.unpack_from('<Q' if bits == 2 else '<I', data, pos + (32 if bits == 2 else 16))[0]
                    expected = b'/system/bin/linker' if auxiliary else b'/system/bin/linker64'
                    if data[start:start + length].rstrip(b'\0') != expected:
                        failures.append([name, 'unexpected native interpreter'])
        if name.startswith('etc/apt/') and name.endswith(('.list', '.sources')):
            active = [line for line in data.decode(errors='replace').splitlines() if line.strip() and not line.lstrip().startswith('#')]
            if active:
                failures.append([name, 'unapproved native binary repository'])
    for required in ['bin/bash', 'bin/sh', 'bin/env', 'bin/curl', 'bin/proot', 'libexec/proot/loader']:
        if required not in layout['files'] | layout['link_paths']:
            failures.append([required, 'required bootstrap entry missing'])
    for required in ['SYMLINKS.txt', 'etc/codex-build.json', 'etc/apt/apt.conf.d/99-codex-source-isolation']:
        if required not in layout['files']:
            failures.append([required, 'must be an actual regular ZIP file, not a link'])
    if not metadata_verified:
        failures.append(['etc/codex-build.json', 'required source metadata was not verified'])
    if elf64 < 10:
        failures.append(['bootstrap', 'unexpectedly few aarch64 native programs'])
    return {'auditVersion': 3, 'applicationId': package, 'prefix': prefix.decode(), 'architecture': 'aarch64', 'uncompressedBytes': size, 'nativeAarch64ElfFiles': elf64, 'auxiliaryElfFiles': helpers, 'symlinkCount': len(layout['links']), 'metadataVerified': metadata_verified, 'failures': failures, 'documentationWarnings': warnings, 'reviewedPrefixComments': comment_matches, 'staticChecksPassed': not failures, 'deviceRuntimeTested': False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=Path('source-lock.json'))
    args = parser.parse_args(argv)
    lock = json.loads(args.lock.read_text())
    with zipfile.ZipFile(args.archive) as archive:
        report = audit_archive(archive, lock)
    report.update(sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(), archiveBytes=args.archive.stat().st_size)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    # Warnings and their exact reviewed evidence are visible in both outputs.
    print(json.dumps(report, indent=2))
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
