#!/usr/bin/env python3
"""Offline, no-disk-write prefix regressions; synthetic ZIPs are not runtime evidence.

Run with python3 -B tests/test_prefix_comment_allowlist.py -v. The retained-deb
checks additionally run when ../diagnostics/old-prefix-context and dpkg-deb exist;
otherwise those checks explicitly skip. Packages are only streamed to memory.
"""
from pathlib import Path
import contextlib
import copy
import hashlib
import io
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import types
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import audit_bootstrap as audit

LOCK = {
    'identity': {'applicationId': 'io.cdxbox', 'nativePrefix': '/data/data/io.cdxbox/files/usr'},
    'app': {'commit': 'synthetic-app-source'},
    'packages': {'commit': 'synthetic-package-source'},
}
OLD = audit.OLD_PREFIXES[0]
SHELL_PATH = 'bin/reviewed-fixture'
HEADER_PATH = 'include/reviewed-fixture.h'
SHELL_COMMENT = b'#!/system/bin/sh\nf() {\n    # example ' + OLD + b'/usr/lib/example.so\n    :\n}\n'
C_COMMENT = b'/*\n * example ' + OLD + b'/usr/bin/example\n */\n#define SAFE_VALUE 1\n'


def hit_lines(data):
    return [{'line': number, 'content': line.decode('utf-8')}
            for number, line in enumerate(data.split(b'\n'), 1)
            if any(prefix in line for prefix in audit.OLD_PREFIXES)]


def fixture_review(path, data):
    """Synthetic test evidence ONLY; never update the real allowlist from inputs."""
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(),
            'sourceDeb': {'file': 'synthetic.deb', 'sha256': '0' * 64, 'member': './usr/' + path},
            'review': 'Synthetic standalone comment, manually specified by this test.',
            'hits': hit_lines(data)}


FIXTURE_REVIEWS = {path: fixture_review(path, data) for path, data in
                   ((SHELL_PATH, SHELL_COMMENT), (HEADER_PATH, C_COMMENT))}


def elf(bits=2, machine=183, interpreter=None):
    """Minimal synthetic ELF containing a PT_INTERP for the existing ABI checks."""
    if interpreter is None:
        interpreter = b'/system/bin/linker64' if bits == 2 else b'/system/bin/linker'
    header_size, step = (64, 56) if bits == 2 else (52, 32)
    data = bytearray(header_size + step)
    data[:4] = b'\x7fELF'; data[4] = bits; data[5] = 1
    struct.pack_into('<H', data, 18, machine)
    struct.pack_into('<Q' if bits == 2 else '<I', data, 32 if bits == 2 else 28, header_size)
    struct.pack_into('<H', data, 54 if bits == 2 else 42, step)
    struct.pack_into('<H', data, 56 if bits == 2 else 44, 1)
    struct.pack_into('<I', data, header_size, 3)
    struct.pack_into('<Q' if bits == 2 else '<I', data, header_size + (8 if bits == 2 else 4), len(data))
    struct.pack_into('<Q' if bits == 2 else '<I', data, header_size + (32 if bits == 2 else 16), len(interpreter) + 1)
    return bytes(data) + interpreter + b'\0'


def zip_fixture(overrides=None, *, remove=(), rows='bash←bin/sh\n'):
    metadata = dict(LOCK['identity'], sourceApp=LOCK['app']['commit'], sourcePackages=LOCK['packages']['commit'])
    names = ['bin/bash', 'bin/env', 'bin/curl', 'bin/proot', 'libexec/proot/loader']
    names += [f'lib/fixture{number}.so' for number in range(5)]
    entries = {name: elf() for name in names}
    entries.update({'SYMLINKS.txt': rows, 'etc/codex-build.json': json.dumps(metadata),
                    'etc/apt/apt.conf.d/99-codex-source-isolation': '# synthetic isolation fixture\n'})
    entries.update(overrides or {})
    for name in remove:
        del entries[name]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    stream.seek(0)
    return stream


def audit_fixture(overrides=None, *, reviews=None, **kwargs):
    patch = mock.patch.object(audit, 'load_reviewed_prefix_comments', return_value=reviews) if reviews is not None else contextlib.nullcontext()
    with patch, zipfile.ZipFile(zip_fixture(overrides, **kwargs)) as archive:
        return audit.audit_archive(archive, LOCK)


class ExactCommentReviewTests(unittest.TestCase):
    def assert_prefix_failure(self, path, data, reviews=None):
        report = audit_fixture({path: data}, reviews=reviews)
        self.assertIn([path, 'old runtime prefix'], report['failures'])
        self.assertFalse(report['staticChecksPassed'])
        self.assertEqual(report['documentationWarnings'], [])
        self.assertEqual(report['reviewedPrefixComments'], [])

    def test_exact_reviewed_comments_warn_not_hide(self):
        report = audit_fixture({SHELL_PATH: SHELL_COMMENT, HEADER_PATH: C_COMMENT}, reviews=FIXTURE_REVIEWS)
        self.assertTrue(report['staticChecksPassed'], report['failures'])
        self.assertEqual(len(report['documentationWarnings']), 2)
        self.assertEqual(report['reviewedPrefixComments'], list(FIXTURE_REVIEWS.values()))
        for path, message in report['documentationWarnings']:
            self.assertIn(FIXTURE_REVIEWS[path]['sha256'], message)
            self.assertIn('lines=', message)

    def test_no_blanket_exemption_for_comments_or_directories(self):
        for path in ('bin/unreviewed', 'include/unreviewed.h', 'share/doc/example', 'share/man/example.1', 'share/licenses/example'):
            with self.subTest(path=path):
                self.assert_prefix_failure(path, SHELL_COMMENT)

    def test_path_is_exact_even_with_identical_bytes(self):
        for path in (SHELL_PATH + '.backup', 'share/doc/' + SHELL_PATH, 'bin/REVIEWED-fixture'):
            with self.subTest(path=path):
                self.assert_prefix_failure(path, SHELL_COMMENT, FIXTURE_REVIEWS)

    def test_any_remaining_hit_in_changed_file_fails(self):
        variants = {
            'non-hit-byte': SHELL_COMMENT + b'\n',
            'line-shift': b'\n' + SHELL_COMMENT,
            'crlf': SHELL_COMMENT.replace(b'\n', b'\r\n'),
            'same-line-extra-hit': SHELL_COMMENT.replace(b'/usr/lib/example.so', b'/usr/lib/example.so ' + OLD),
            'extra-comment': SHELL_COMMENT + b'# ' + OLD + b'\n',
            'extra-active-code': SHELL_COMMENT + b'exec ' + OLD + b'/usr/bin/sh\n',
            'extra-other-old-prefix': SHELL_COMMENT + b'# ' + audit.OLD_PREFIXES[1] + b'\n',
            'extra-host-prefix': SHELL_COMMENT + b'# ' + audit.OLD_PREFIXES[2] + b'\n',
            'active-hit': SHELL_COMMENT.replace(b'# example ', b'exec '),
            # The old-prefix-bearing line stays identical, but its context changes.
            'heredoc-context': SHELL_COMMENT.replace(b'f() {', b"cat <<'EOF'").replace(b'    :\n}', b'EOF'),
            'string-context': SHELL_COMMENT.replace(b'f() {', b"value='").replace(b'    :\n}', b"'"),
        }
        for label, data in variants.items():
            with self.subTest(label=label):
                self.assert_prefix_failure(SHELL_PATH, data, FIXTURE_REVIEWS)
        self.assert_prefix_failure(HEADER_PATH, C_COMMENT.replace(b'/*', b'  '), FIXTURE_REVIEWS)
        self.assert_prefix_failure(HEADER_PATH, C_COMMENT.replace(b' * example ', b'#define BAD_PATH '), FIXTURE_REVIEWS)

    def test_exact_hit_list_is_checked_independently_of_hash(self):
        # A stale hit list is rejected even if somebody only refreshes the hash.
        for changed in (b'\n' + SHELL_COMMENT, SHELL_COMMENT + b'# ' + OLD + b'\n',
                        SHELL_COMMENT.replace(b'/usr/lib/example.so', b'/usr/lib/example.so ' + OLD)):
            reviews = copy.deepcopy(FIXTURE_REVIEWS)
            reviews[SHELL_PATH]['sha256'] = hashlib.sha256(changed).hexdigest()
            self.assert_prefix_failure(SHELL_PATH, changed, reviews)
        for key, value in (('line', 4), ('content', '# ' + OLD.decode())):
            reviews = copy.deepcopy(FIXTURE_REVIEWS)
            reviews[SHELL_PATH]['hits'][0][key] = value
            self.assert_prefix_failure(SHELL_PATH, SHELL_COMMENT, reviews)
        reviews = copy.deepcopy(FIXTURE_REVIEWS)
        reviews[SHELL_PATH]['sha256'] = '0' * 64
        self.assert_prefix_failure(SHELL_PATH, SHELL_COMMENT, reviews)

    def test_active_shell_macro_shebang_and_heredoc_fail(self):
        for prefix in audit.OLD_PREFIXES:
            for data in (b'export PREFIX=' + prefix + b'/usr\n',
                         b'exec ' + prefix + b'/usr/bin/sh\n',
                         b'#define PREFIX "' + prefix + b'/usr"\n',
                         b'#!' + prefix + b'/usr/bin/sh\n',
                         b"cat <<'EOF'\n# " + prefix + b'/usr\nEOF\n',
                         b'cat <<EOF\n# $(exec ' + prefix + b'/usr/bin/sh)\nEOF\n'):
                for path in (SHELL_PATH, HEADER_PATH, 'share/doc/disguised'):
                    with self.subTest(prefix=prefix, path=path, data=data):
                        self.assert_prefix_failure(path, data, FIXTURE_REVIEWS)

    def test_elf_old_prefix_never_exempt_even_with_matching_rule(self):
        for path, data in (('lib/old.so', elf() + OLD), ('share/doc/old.elf', elf() + OLD),
                           ('libexec/proot/loader32', elf(1, 40) + OLD)):
            reviews = {path: fixture_review(path, data)}
            with self.subTest(path=path):
                self.assert_prefix_failure(path, data, reviews)

    def test_rebuilt_file_without_any_old_prefix_needs_no_exception(self):
        changed = SHELL_COMMENT.replace(OLD, b'/data/data/io.cdxbox/files')
        report = audit_fixture({SHELL_PATH: changed}, reviews=FIXTURE_REVIEWS)
        self.assertTrue(report['staticChecksPassed'])
        self.assertEqual(report['documentationWarnings'], [])

    def test_missing_or_malformed_manifest_fails_closed(self):
        with mock.patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'Invalid reviewed-prefix'):
                audit.load_reviewed_prefix_comments()
        document = {'schemaVersion': 1, 'files': list(copy.deepcopy(FIXTURE_REVIEWS).values())}
        cases = ['{', '[]', json.dumps({'schemaVersion': 99, 'files': []})]
        duplicate = copy.deepcopy(document); duplicate['files'].append(duplicate['files'][0])
        cases.append(json.dumps(duplicate))
        for key, value in (('path', '../escape'), ('sha256', 'short'), ('hits', []), ('review', '')):
            changed = copy.deepcopy(document); changed['files'][0][key] = value
            cases.append(json.dumps(changed))
        for content in cases:
            with self.subTest(content=content), mock.patch.object(Path, 'read_text', return_value=content):
                with self.assertRaisesRegex(ValueError, 'Invalid reviewed-prefix'):
                    audit.load_reviewed_prefix_comments()


class ExistingAuditGuardTests(unittest.TestCase):
    def test_aarch64_and_only_legitimate_arm32_loader_pass(self):
        report = audit_fixture({'libexec/proot/loader32': elf(1, 40)})
        self.assertTrue(report['staticChecksPassed'], report['failures'])
        self.assertEqual(report['nativeAarch64ElfFiles'], 10)
        self.assertEqual(report['auxiliaryElfFiles'], [{'path': 'libexec/proot/loader32', 'architecture': 'ARM32 proot compatibility loader'}])
        self.assertTrue(report['metadataVerified'])
        self.assertEqual(report['symlinkCount'], 1)
        self.assertFalse(report['deviceRuntimeTested'])

    def test_wrong_abi_and_interpreters_still_fail(self):
        cases = [('lib/wrong.so', elf(1, 40), 'unexpected non-aarch64 native ELF'),
                 ('lib/wrong.so', elf(2, 62), 'unexpected non-aarch64 native ELF'),
                 ('libexec/proot/loader32', elf(1, 3), 'unexpected non-aarch64 native ELF'),
                 ('lib/wrong.so', elf(interpreter=b'/system/bin/linker'), 'unexpected native interpreter'),
                 ('libexec/proot/loader32', elf(1, 40, b'/system/bin/linker64'), 'unexpected native interpreter')]
        for path, data, message in cases:
            with self.subTest(path=path, message=message):
                self.assertIn([path, message], audit_fixture({path: data})['failures'])

    def test_malformed_elf_and_native_count_still_fail(self):
        data = bytearray(elf()); struct.pack_into('<H', data, 54, 1)
        cases = [(b'\x7fELF', 'invalid ELF format'),
                 (elf()[:52], 'truncated ELF64'),
                 (elf()[:64], 'truncated ELF headers'),
                 (bytes(data), 'invalid ELF program-header size')]
        for data, message in cases:
            with self.subTest(message=message):
                self.assertIn(['lib/bad.so', message], audit_fixture({'lib/bad.so': data})['failures'])
        report = audit_fixture(remove=('lib/fixture4.so',))
        self.assertIn(['bootstrap', 'unexpectedly few aarch64 native programs'], report['failures'])

    def test_real_metadata_and_isolation_files_still_required(self):
        for path in ('etc/codex-build.json', 'etc/apt/apt.conf.d/99-codex-source-isolation'):
            report = audit_fixture(remove=(path,), rows='bash←bin/sh\n/dev/null←' + path + '\n')
            self.assertIn([path, 'must be an actual regular ZIP file, not a link'], report['failures'])
            self.assertFalse(report['staticChecksPassed'])
            if path.endswith('.json'):
                self.assertFalse(report['metadataVerified'])
                self.assertIn([path, 'required source metadata was not verified'], report['failures'])
        report = audit_fixture({'etc/codex-build.json': '{}'})
        self.assertIn(['etc/codex-build.json', 'identity/source metadata mismatch'], report['failures'])

    def test_symlink_and_zip_layout_still_fail_closed(self):
        for rows in ('', 'bash←bin/bash\n', 'bash←bin/sh←extra\n', 'bash←bin/sh\nbash←./bin/sh\n',
                     'bash←../sh\n', 'target←foo\ntarget←foo/bar\n'):
            with self.subTest(rows=rows), self.assertRaisesRegex(SystemExit, 'Bootstrap link/layout audit failed'):
                audit_fixture(rows=rows)
        for path in ('./noncanonical', '../traversal'):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                audit_fixture({path: b'data'})

    def test_component_and_apt_repository_checks_still_fail(self):
        path = 'bin/component'
        report = audit_fixture({path: b'#!/system/bin/sh\nam start io.cdxbox/io.cdxbox.app.TermuxService\n'})
        self.assertIn([path, 'component class incorrectly resolved against installation ID'], report['failures'])
        path = 'etc/apt/sources.list'
        report = audit_fixture({path: 'deb https://example.invalid stable main\n'})
        self.assertIn([path, 'unapproved native binary repository'], report['failures'])
        self.assertTrue(audit_fixture({path: '# disabled\n'})['staticChecksPassed'])

    def test_cli_exit_status_and_visible_warning_report_without_disk_writes(self):
        for entries, expected in (({SHELL_PATH: SHELL_COMMENT}, 0),
                                  ({SHELL_PATH: SHELL_COMMENT + b'exec ' + OLD + b'/usr/bin/sh\n'}, 1)):
            stream = zip_fixture(entries)
            stream.read_bytes = stream.getvalue
            stream.stat = lambda: types.SimpleNamespace(st_size=len(stream.getvalue()))
            report_path = mock.Mock()
            args = types.SimpleNamespace(archive=stream, report=report_path, lock=mock.Mock())
            args.lock.read_text.return_value = json.dumps(LOCK)
            output = io.StringIO()
            with mock.patch.object(audit.argparse.ArgumentParser, 'parse_args', return_value=args), \
                 mock.patch.object(audit, 'load_reviewed_prefix_comments', return_value=FIXTURE_REVIEWS), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(audit.main([]), expected)
            written = json.loads(report_path.write_text.call_args.args[0])
            self.assertEqual(json.loads(output.getvalue()), written)
            self.assertEqual(written['sha256'], hashlib.sha256(stream.getvalue()).hexdigest())
            self.assertEqual(written['archiveBytes'], len(stream.getvalue()))
            self.assertEqual(len(written['documentationWarnings']), 1 if expected == 0 else 0)


class RetainedPackageEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = REPO.parent / 'diagnostics' / 'old-prefix-context'
        hashes = {
            'termux-exec_1:2.5.0-1_aarch64.deb': '4a904f518d14d25035241294f0503af1d761ff3de3a3fbc3230fc915bbddee44',
            'termux-tools_1.46.0+really1.45.0-1_aarch64.deb': '2ca8e80147ffb272ef8484b459f4ac77c3dfa6387796fc169fb14ea1f8fde9ff',
            'termux-core_0.4.0-1_aarch64.deb': '012347bf96029fdb4fc28d3a043d8b0edd3de5b3efdf183ee9f3224a0948b480',
        }
        if shutil.which('dpkg-deb') is None or not all((directory / name).is_file() for name in hashes):
            raise unittest.SkipTest('Retained public .deb evidence or dpkg-deb is unavailable; synthetic tests still run')
        cls.packages = {}
        root = './data/data/io.cdxbox/files/usr/'
        for name, digest in hashes.items():
            path = directory / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise AssertionError('Retained package changed: ' + name)
            result = subprocess.run(['dpkg-deb', '--fsys-tarfile', str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:') as archive:
                cls.packages[name.split('_')[0]] = {
                    member.name[len(root):]: archive.extractfile(member).read()
                    for member in archive if member.isfile() and member.name.startswith(root)
                }

    def test_real_reviewed_hashes_and_complete_hits_match(self):
        reviews = audit.load_reviewed_prefix_comments()
        self.assertEqual(len(reviews), 2)
        files = self.packages['termux-exec']
        hit_files = {name: data for name, data in files.items() if any(prefix in data for prefix in audit.OLD_PREFIXES)}
        self.assertEqual(set(hit_files), set(reviews))
        self.assertEqual(sum(sum(data.count(prefix) for prefix in audit.OLD_PREFIXES) for data in hit_files.values()), 5)
        for name, data in hit_files.items():
            self.assertEqual(hashlib.sha256(data).hexdigest(), reviews[name]['sha256'])
            self.assertEqual(hit_lines(data), reviews[name]['hits'])
        report = audit_fixture(hit_files)
        self.assertTrue(report['staticChecksPassed'], report['failures'])
        self.assertEqual(len(report['documentationWarnings']), 2)
        self.assertEqual(len(report['reviewedPrefixComments']), 2)

    def test_changed_actual_reviewed_files_cannot_reuse_review(self):
        for name, rule in audit.load_reviewed_prefix_comments().items():
            original = self.packages['termux-exec'][name]
            variants = [original + b'\n', b'\n' + original, original + b'# ' + OLD + b'\n',
                        original.replace(OLD, OLD + b' ' + OLD, 1)]
            if name.startswith('bin/'):
                variants.append(original.replace(b'    # Prevent `CANNOT', b'    echo `CANNOT'))
                variants.append(original.replace(b'termux_exec__ld_preload_lib__setup__run_command() {', b"cat <<'EOF'"))
            else:
                variants.append(original.replace(b'/*\n', b'  \n', 1))
                variants.append(original.replace(b' * LD_DEBUG=3 ', b'#define BAD_PATH '))
            for data in variants:
                self.assertIsNone(audit.reviewed_prefix_comment(name, data, {name: rule}))
                self.assertIn([name, 'old runtime prefix'], audit_fixture({name: data})['failures'])
            self.assertIn(['share/doc/' + name, 'old runtime prefix'], audit_fixture({'share/doc/' + name: original})['failures'])

    def test_retained_termux_tools_all_15_files_and_70_hits_still_fail(self):
        files = self.packages['termux-tools']
        hit_files = {name: data for name, data in files.items() if any(prefix in data for prefix in audit.OLD_PREFIXES)}
        self.assertEqual(len(hit_files), 15)
        self.assertEqual(sum(sum(data.count(prefix) for prefix in audit.OLD_PREFIXES) for data in hit_files.values()), 70)
        report = audit_fixture(hit_files)
        self.assertFalse(report['staticChecksPassed'])
        self.assertEqual(report['documentationWarnings'], [])
        self.assertEqual(report['reviewedPrefixComments'], [])
        self.assertEqual({name for name, reason in report['failures'] if reason == 'old runtime prefix'}, set(hit_files))
        self.assertIn(b'NEW_SHELL=' + OLD + b'/usr/bin/$1', files['bin/chsh'])
        self.assertIn(b'export ANDROID_DATA=' + OLD, files['bin/dalvikvm'])
        self.assertIn(b'\\!/data/data/com.termux/files/usr/bin/\\2', files['bin/termux-fix-shebang'])

    def test_retained_termux_core_has_no_old_prefix(self):
        self.assertFalse(any(prefix in data for data in self.packages['termux-core'].values() for prefix in audit.OLD_PREFIXES))


if __name__ == '__main__':
    unittest.main()
