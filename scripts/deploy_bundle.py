"""Verify and unpack an exact reviewed static export; never execute science."""
import argparse
import hashlib
import gzip
import json
from pathlib import Path
import re
import tarfile

PROJECT = 'jernigan-structure-atlas'
MAX_BYTES = 950_000_000
MAX_FILES = 10_000
MAX_MANIFEST_BYTES = 8_000_000
CHUNK = 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')


def digest(source):
    """Hash an open binary stream with bounded memory."""
    h = hashlib.sha256()
    for block in iter(lambda: source.read(CHUNK), b''):
        h.update(block)
    return h.hexdigest()


def safe_name(name):
    if (not isinstance(name, str) or not name or name.startswith('/') or
            any(p in ('', '.', '..') for p in name.split('/')) or
            any(c in name for c in ('\\', ':', '?', '#', '%')) or
            any(ord(c) < 32 or ord(c) == 127 for c in name) or
            any(p.startswith('.') for p in name.split('/')) and name != '.nojekyll'):
        raise ValueError('Unsafe static asset path: ' + repr(name))
    return name


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def manifest_rows(raw):
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('Oversized export manifest')
    receipt = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(receipt, dict) or type(receipt.get('schema_version')) is not int or
            receipt['schema_version'] != 1 or receipt.get('project') != PROJECT or
            receipt.get('scientific_execution') is not False):
        raise ValueError('Wrong project or export contract')
    rows = receipt.get('files')
    if not isinstance(rows, list) or not 1 <= len(rows) < MAX_FILES:
        raise ValueError('Invalid export allowlist')
    by_name = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid export row')
        name = safe_name(row.get('path'))
        if name == 'export-manifest.json' or name in by_name:
            raise ValueError('Duplicate or self-referential export row')
        if (type(row.get('bytes')) is not int or not 0 <= row['bytes'] <= MAX_BYTES or
                not isinstance(row.get('sha256'), str) or not SHA.fullmatch(row['sha256'])):
            raise ValueError('Invalid artifact size or hash: ' + name)
        by_name[name] = row
    if not {'index.html', '.nojekyll'} <= set(by_name):
        raise ValueError('Missing static entry point or .nojekyll')
    if sum(r['bytes'] for r in rows) + len(raw) > MAX_BYTES:
        raise ValueError('Oversized static export')
    return by_name


def preflight_headers(handle):
    """Bound decompression and reject extension headers before tarfile can read them."""
    count = total = expanded = 0
    limit = MAX_BYTES + MAX_FILES * 1024 + 10240
    with gzip.GzipFile(fileobj=handle, mode='rb') as source:
        def read(size):
            nonlocal expanded
            data = source.read(size)
            expanded += len(data)
            if expanded > limit:
                raise ValueError('Oversized expanded archive')
            return data
        while True:
            raw = read(512)
            if len(raw) != 512:
                raise ValueError('Truncated tar header')
            if raw == b'\0' * 512:
                if read(512) != b'\0' * 512:
                    raise ValueError('Missing tar end marker')
                # Reject appended archives or nonzero data after the end marker.
                while True:
                    trailing = read(CHUNK)
                    if not trailing:
                        return
                    if any(trailing):
                        raise ValueError('Trailing data after static export')
            member = tarfile.TarInfo.frombuf(raw, 'utf-8', 'strict')
            safe_name(member.name)
            count += 1
            total += member.size
            if (not member.isfile() or member.issparse() or member.size < 0 or
                    count > MAX_FILES or total > MAX_BYTES):
                raise ValueError('Unsupported or oversized raw tar member')
            remaining = ((member.size + 511) // 512) * 512
            while remaining:
                block = read(min(CHUNK, remaining))
                if not block:
                    raise ValueError('Truncated tar member')
                remaining -= len(block)


def validate_tar(tar):
    """Validate all regular files and hashes before writing any output."""
    members = {}
    total = 0
    for member in tar:
        name = safe_name(member.name)
        if not member.isfile() or member.issparse() or name in members:
            raise ValueError('Nonregular, sparse or duplicate member: ' + name)
        total += member.size
        if member.size < 0 or total > MAX_BYTES or len(members) >= MAX_FILES:
            raise ValueError('Oversized bundle')
        members[name] = member
    if 'export-manifest.json' not in members:
        raise ValueError('Missing export manifest')
    if members['export-manifest.json'].size > MAX_MANIFEST_BYTES:
        raise ValueError('Oversized export manifest')
    with tar.extractfile(members['export-manifest.json']) as source:
        manifest_raw = source.read(MAX_MANIFEST_BYTES + 1)
        rows = manifest_rows(manifest_raw)
    if set(members) != set(rows) | {'export-manifest.json'}:
        raise ValueError('Bundle differs from export allowlist')
    # Reject a file whose path is the parent of another file.
    for name in members:
        parts = name.split('/')
        if any('/'.join(parts[:i]) in members for i in range(1, len(parts))):
            raise ValueError('File/directory collision: ' + name)
    for name, row in rows.items():
        if members[name].size != row['bytes']:
            raise ValueError('Artifact size differs: ' + name)
        with tar.extractfile(members[name]) as source:
            if digest(source) != row['sha256']:
                raise ValueError('Artifact hash differs: ' + name)
    expected = {name: row['sha256'] for name, row in rows.items()}
    expected['export-manifest.json'] = hashlib.sha256(manifest_raw).hexdigest()
    return members, expected


def unpack(archive, expected, output=None):
    archive = Path(archive)
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError('An exact reviewed bundle SHA-256 is required')
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Bundle must be a regular local file')
    if output is not None:
        output = Path(output).absolute()
        if output.exists() or output.is_symlink():
            raise ValueError('Deployment requires a fresh directory')
        if any(p.is_symlink() for p in output.parents):
            raise ValueError('Symlinked output parent')
    # Keep the same file descriptor for digest and extraction.
    with archive.open('rb') as handle:
        if digest(handle) != expected:
            raise ValueError('Bundle hash changed')
        handle.seek(0)
        preflight_headers(handle)
        handle.seek(0)
        with tarfile.open(fileobj=handle, mode='r:gz') as tar:
            members, file_hashes = validate_tar(tar)
            if output is not None:
                output.mkdir(parents=True, exist_ok=False)
                for name in sorted(members):
                    dest = output / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    saved_hash = hashlib.sha256()
                    with tar.extractfile(members[name]) as source, dest.open('xb') as target:
                        for block in iter(lambda: source.read(CHUNK), b''):
                            target.write(block)
                            written += len(block)
                            saved_hash.update(block)
                    if written != members[name].size or saved_hash.hexdigest() != file_hashes[name]:
                        raise ValueError('Archive changed during extraction: ' + name)
        handle.seek(0)
        if digest(handle) != expected:
            raise ValueError('Archive changed during verification or extraction')
    return {'project': PROJECT, 'bundle_sha256': expected, 'files': len(members),
            'bytes': sum(m.size for m in members.values()), 'scientific_execution': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(unpack(args.archive, args.sha256, args.output), sort_keys=True))
