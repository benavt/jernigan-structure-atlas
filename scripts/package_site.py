"""Deterministically package an existing privacy-reviewed static directory."""
import argparse
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile

from deploy_bundle import digest, manifest_rows, safe_name, unpack


def package(source, destination):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source.is_symlink() or not source.is_dir() or any(p.is_symlink() for p in source.parents):
        raise ValueError('Source must be a real static directory')
    if (destination.exists() or destination.is_symlink() or
            any(p.is_symlink() for p in destination.parents)):
        raise ValueError('Archive requires a fresh regular output path')
    if destination == source or source in destination.parents:
        raise ValueError('Archive must be outside the saved static directory')
    manifest = source / 'export-manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('Missing regular export manifest')
    with manifest.open('rb') as handle:
        from deploy_bundle import MAX_MANIFEST_BYTES
        manifest_raw = handle.read(MAX_MANIFEST_BYTES + 1)
        rows = manifest_rows(manifest_raw)
    files = {}
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in static directory')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Nonregular static artifact')
        name = safe_name(path.relative_to(source).as_posix())
        files[name] = path
    if set(files) != set(rows) | {'export-manifest.json'}:
        raise ValueError('Static directory differs from export allowlist')
    for name, row in rows.items():
        with files[name].open('rb') as handle:
            if files[name].stat().st_size != row['bytes'] or digest(handle) != row['sha256']:
                raise ValueError('Saved artifact changed: ' + name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Create privately under a random name; expose the final name only after verification.
    with tempfile.NamedTemporaryFile(prefix='.site-', suffix='.tar.gz', dir=destination.parent,
                                     delete=False) as temporary:
        temp = Path(temporary.name)
    try:
        with temp.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                                                 mtime=0, compresslevel=9) as compressed:
            with tarfile.open(mode='w', fileobj=compressed, format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(files):
                    item = tarfile.TarInfo(name)
                    item.size = len(manifest_raw) if name == 'export-manifest.json' else rows[name]['bytes']
                    item.mode, item.uid, item.gid, item.mtime = 0o644, 0, 0, 0
                    item.uname = item.gname = ''
                    if name == 'export-manifest.json':
                        archive.addfile(item, io.BytesIO(manifest_raw))
                    else:
                        with files[name].open('rb') as handle:
                            archive.addfile(item, handle)
        with temp.open('rb') as handle:
            sha = digest(handle)
        result = unpack(temp, sha)  # Recheck the actual archive, including concurrent source changes.
        # A changed manifest must never silently replace the reviewed contract.
        if manifest.is_symlink() or manifest.read_bytes() != manifest_raw:
            raise ValueError('Export manifest changed during packaging')
        current = {}
        for path in source.rglob('*'):
            if path.is_symlink():
                raise ValueError('Static source changed to symlink during packaging')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('Static source changed to nonregular artifact')
            current[safe_name(path.relative_to(source).as_posix())] = path
        if set(current) != set(files):
            raise ValueError('Static source file set changed during packaging')
        for name, row in rows.items():
            with current[name].open('rb') as handle:
                if current[name].stat().st_size != row['bytes'] or digest(handle) != row['sha256']:
                    raise ValueError('Static source changed during packaging: ' + name)
        # Atomic no-overwrite finalization on the same filesystem.
        import os
        os.link(temp, destination)
        return result
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.output), sort_keys=True))
