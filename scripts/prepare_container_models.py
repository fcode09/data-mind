"""Explicit, resumable provisioning of hash-verified public models into volumes."""
import argparse
import json
from pathlib import Path
from download_models import ROOT, acquire, browser_archive
from download_embedding_model import FILES as EMBEDDING_FILES

LLM = {
    'path': 'Qwen3-0.6B-Q8_0.gguf',
    'url': 'https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf',
    'size': 639446688,
    'sha256': '9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031',
}


def prepare(group, destination, browser_destination):
    if group in ('voice', 'all'):
        for item in json.loads((ROOT / 'models/models.lock').read_text())['files']:
            path = acquire(item, destination)
            print('Verified', item['path'], flush=True)
            if item['group'] == 'vosk':
                browser_archive(path, browser_destination / 'vosk-model-small-es-0.42.tar.gz')
        for item in EMBEDDING_FILES:
            acquire(item, destination / 'multilingual-e5-small')
            print('Verified embedding', item['path'], flush=True)
    if group in ('llm', 'all'):
        acquire(LLM, destination / 'llama')
        print('Verified Qwen3-0.6B Q8_0 (Apache-2.0)', flush=True)
    print('Provisioning complete. Model inference requires a separate runtime check.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=['voice', 'llm', 'all'], default='voice')
    parser.add_argument('--destination', type=Path, default=Path('/models'))
    parser.add_argument('--browser-destination', type=Path, default=Path('/browser-models'))
    parser.add_argument('--accept-model-licenses', action='store_true', required=True,
                        help='Confirm review of docs/runbooks/docker-models.md model licenses')
    args = parser.parse_args()
    prepare(args.group, args.destination, args.browser_destination)


if __name__ == '__main__':
    main()
