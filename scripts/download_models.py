"""Explicit, pinned model acquisition. Never called during a user request."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()

def acquire(item, destination):
    path = destination / item['path']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and digest(path) == item['sha256']:
        return path
    temporary = path.with_suffix(path.suffix + '.part')
    try:
        with urllib.request.urlopen(item['url'], timeout=60) as response, temporary.open('wb') as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > item['size']:
                    raise ValueError('Download exceeds pinned size')
                output.write(chunk)
        if size != item['size'] or digest(temporary) != item['sha256']:
            raise ValueError('Model digest mismatch; refusing unverified weights')
        temporary.replace(path)
        return path
    finally:
        temporary.unlink(missing_ok=True)

def browser_archive(source, output):
    """Convert official ZIP to the tar.gz format expected by vosk-browser."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.part')
    total = 0
    try:
        with zipfile.ZipFile(source) as archive, tarfile.open(temporary, 'w:gz') as target:
            for member in archive.infolist():
                name = PurePosixPath(member.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in member.filename:
                    raise ValueError('Unsafe model archive path')
                if member.is_dir():
                    continue
                # vosk-browser expects a model/ directory at the archive root.
                relative = str(PurePosixPath('model', *name.parts[1:]))
                total += member.file_size
                if total > 256 * 1024 * 1024:
                    raise ValueError('Expanded model exceeds budget')
                info = tarfile.TarInfo(relative)
                info.size = member.file_size
                info.mode = 0o644
                with archive.open(member) as content:
                    target.addfile(info, content)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=['all', 'vosk', 'whisper-small', 'kokoro'], required=True)
    parser.add_argument('--destination', type=Path, default=ROOT / 'models/cache')
    parser.add_argument('--prepare-browser', action='store_true')
    parser.add_argument('--accept-model-licenses', action='store_true', required=True,
                        help='Confirm review of the model cards and licenses linked in docs/voice.md')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'models/models.lock').read_text())
    for item in lock['files']:
        if args.group not in ('all', item['group']):
            continue
        print('Verifying/downloading', item['path'], item['license'])
        path = acquire(item, args.destination)
        if args.prepare_browser and item['group'] == 'vosk':
            browser_archive(path, ROOT / 'apps/web/public/models/vosk-model-small-es-0.42.tar.gz')
    print('Model files verified. Real inference and microphone tests remain separate checks.')

if __name__ == '__main__':
    main()
