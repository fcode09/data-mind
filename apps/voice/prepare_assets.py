"""Explicitly render a fixed local acknowledgement after model/runtime setup."""
import argparse
from pathlib import Path
from .engine import LocalModels

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('apps/web/public/models/consulting.wav'))
    args = parser.parse_args()
    audio = LocalModels().synthesize('Déjame consultar.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(audio)
    print(f'Generated fixed acknowledgement: {args.output}')

if __name__ == '__main__':
    main()
