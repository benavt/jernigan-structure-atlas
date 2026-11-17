import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deploy_bundle as deploy
import package_site


def sha(data):
    return hashlib.sha256(data).hexdigest()


class StaticDelivery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = {'index.html': b'<html>Saved Atlas</html>', '.nojekyll': b'',
                       'data/models.json': b'{"models":["a"]}', 'reports/review.pdf': b'%PDF-reviewed'}

    def manifest(self, **kwargs):
        value = {'schema_version': 1, 'project': deploy.PROJECT, 'scientific_execution': False,
                 'files': [{'path': name, 'bytes': len(data), 'sha256': sha(data)}
                           for name, data in sorted(self.assets.items())]}
        value.update(kwargs)
        return json.dumps(value).encode()

    def bundle(self, changes=None, extra=(), manifest=None):
        assets = dict(self.assets)
        assets['export-manifest.json'] = self.manifest() if manifest is None else manifest
        assets.update(changes or {})
        output = self.root / ('bundle-' + str(len(list(self.root.iterdir()))) + '.tar.gz')
        with tarfile.open(output, 'w:gz') as tar:
            for name, data in assets.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
            for member, data in extra:
                tar.addfile(member, io.BytesIO(data) if data is not None else None)
        return output, sha(output.read_bytes())

    def source(self):
        path = self.root / 'source'
        path.mkdir()
        for name, data in self.assets.items():
            member = path / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(data)
        (path / 'export-manifest.json').write_bytes(self.manifest())
        return path

    def test_exact_saved_export_round_trip(self):
        archive, expected = self.bundle()
        output = self.root / 'unpacked'
        receipt = deploy.unpack(archive, expected, output)
        self.assertFalse(receipt['scientific_execution'])
        self.assertEqual(receipt['files'], len(self.assets) + 1)
        for name, data in self.assets.items():
            self.assertEqual((output / name).read_bytes(), data)

    def test_hash_and_asset_mutation_fail_before_writing(self):
        for changes, expected_override in [({}, '0' * 64), ({'index.html': b'Changed'}, None)]:
            with self.subTest(changes=changes):
                archive, expected = self.bundle(changes)
                output = self.root / 'invalid-output'
                with self.assertRaises(ValueError):
                    deploy.unpack(archive, expected_override or expected, output)
                self.assertFalse(output.exists())

    def test_traversal_encoded_paths_hidden_and_file_collisions(self):
        for name in ['../escape', '/absolute', 'a/../escape', 'a//b', './index.html',
                     'a\\b', 'file:stream', 'a%2fb', '.git/config', 'a/#b', 'a/\x01b']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    deploy.safe_name(name)
        archive, expected = self.bundle({'data': b'parent collision'})
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected)

    def test_links_nonregular_duplicate_and_oversize_rejected(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]:
            member = tarfile.TarInfo('extra')
            member.type = kind
            member.linkname = '../outside'
            archive, expected = self.bundle(extra=[(member, None)])
            with self.subTest(type=kind), self.assertRaises(ValueError):
                deploy.unpack(archive, expected)
        member = tarfile.TarInfo('index.html')
        archive, expected = self.bundle(extra=[(member, b'')])
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected)
        archive, expected = self.bundle()
        with patch.object(deploy, 'MAX_BYTES', 20), self.assertRaises(ValueError):
            deploy.unpack(archive, expected)
        with patch.object(deploy, 'MAX_FILES', 2), self.assertRaises(ValueError):
            deploy.unpack(archive, expected)
        with patch.object(deploy, 'MAX_MANIFEST_BYTES', 10), self.assertRaises(ValueError):
            deploy.unpack(archive, expected)

    def test_extended_headers_and_appended_archives_rejected(self):
        member = tarfile.TarInfo('extended-header')
        member.type = tarfile.XHDTYPE
        member.size = 13
        archive, expected = self.bundle(extra=[(member, b'13 comment=x\n')])
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected)
        archive, expected = self.bundle()
        import gzip
        with archive.open('ab') as handle:
            handle.write(gzip.compress(b'appended payload'))
        with self.assertRaises(ValueError):
            deploy.unpack(archive, sha(archive.read_bytes()))

    def test_wrong_contract_and_allowlist_rejected(self):
        receipts = [self.manifest(project='other'), self.manifest(scientific_execution=True),
                    self.manifest(schema_version=True), self.manifest(files=[]),
                    b'{"schema_version":1,"schema_version":1}']
        base = json.loads(self.manifest())
        duplicate = dict(base, files=base['files'] + [base['files'][0]])
        bad_size = json.loads(self.manifest())
        bad_size['files'][0]['bytes'] = True
        receipts.extend([json.dumps(duplicate).encode(), json.dumps(bad_size).encode()])
        for receipt in receipts:
            archive, expected = self.bundle(manifest=receipt)
            with self.subTest(manifest=receipt), self.assertRaises(ValueError):
                deploy.unpack(archive, expected)
        archive, expected = self.bundle({'undeclared.json': b'not reviewed'})
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected)

    def test_existing_destination_and_symlink_parent_rejected(self):
        archive, expected = self.bundle()
        existing = self.root / 'existing'
        existing.mkdir()
        (existing / 'preserved').write_text('keep')
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected, existing)
        self.assertEqual((existing / 'preserved').read_text(), 'keep')
        link = self.root / 'linked'
        link.symlink_to(existing, target_is_directory=True)
        with self.assertRaises(ValueError):
            deploy.unpack(archive, expected, link / 'output')

    def test_packaging_is_deterministic_and_allowlist_exact(self):
        source = self.source()
        first, second = self.root / 'first.tar.gz', self.root / 'second.tar.gz'
        a = package_site.package(source, first)
        b = package_site.package(source, second)
        self.assertEqual(a['bundle_sha256'], b['bundle_sha256'])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with self.assertRaises(ValueError):
            package_site.package(source, first)
        (source / 'extra').write_text('unreviewed')
        with self.assertRaises(ValueError):
            package_site.package(source, self.root / 'third.tar.gz')

    def test_packaging_rejects_changed_bytes_links_and_nested_output(self):
        source = self.source()
        with self.assertRaises(ValueError):
            package_site.package(source, source / 'site.tar.gz')
        (source / 'index.html').write_text('changed')
        with self.assertRaises(ValueError):
            package_site.package(source, self.root / 'changed.tar.gz')
        (source / 'index.html').unlink()
        (source / 'index.html').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            package_site.package(source, self.root / 'linked.tar.gz')

    def test_concurrent_manifest_and_source_replacement_rejected(self):
        for replace_assets in (False, True):
            with self.subTest(replace_assets=replace_assets):
                if (self.root / 'source').exists():
                    shutil.rmtree(self.root / 'source')
                source = self.source()
                original = tarfile.TarFile.addfile
                changed = False
                def race(archive, member, fileobj=None):
                    nonlocal changed
                    if not changed and member.name == 'export-manifest.json':
                        changed = True
                        updated = json.loads(self.manifest())
                        updated['unreviewed_amendment'] = True
                        if replace_assets:
                            replacement = b'X' * len(self.assets['index.html'])
                            (source / 'index.html').write_bytes(replacement)
                            for row in updated['files']:
                                if row['path'] == 'index.html':
                                    row.update(bytes=len(replacement), sha256=sha(replacement))
                        (source / 'export-manifest.json').write_text(json.dumps(updated))
                    return original(archive, member, fileobj)
                destination = self.root / 'race.tar.gz'
                with patch.object(tarfile.TarFile, 'addfile', race), self.assertRaises(ValueError):
                    package_site.package(source, destination)
                self.assertFalse(destination.exists())

    def test_bytes_changed_between_validation_and_extraction_rejected(self):
        archive, expected = self.bundle()
        original = tarfile.TarFile.extractfile
        reads = 0
        def changed_read(tar, member):
            nonlocal reads
            if getattr(member, 'name', member) == 'index.html':
                reads += 1
                if reads == 2:
                    return io.BytesIO(b'X' * len(self.assets['index.html']))
            return original(tar, member)
        with patch.object(tarfile.TarFile, 'extractfile', changed_read), self.assertRaises(ValueError):
            deploy.unpack(archive, expected, self.root / 'race-output')

    def test_deployer_standalone_with_no_project_or_runtime_imports(self):
        archive, expected = self.bundle()
        isolated = self.root / 'isolated'
        isolated.mkdir()
        script = isolated / 'deploy_bundle.py'
        shutil.copyfile(Path(deploy.__file__), script)
        result = subprocess.run([sys.executable, '-I', str(script), str(archive), '--sha256',
                                 expected, '--output', str(isolated / 'site')],
                                cwd=isolated, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['bundle_sha256'], expected)
        self.assertEqual((isolated / 'site/index.html').read_bytes(), self.assets['index.html'])


if __name__ == '__main__':
    unittest.main()
