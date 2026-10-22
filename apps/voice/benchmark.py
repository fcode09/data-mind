"""Real local synthetic speech round trip, not a microphone or latency SLA test."""
import argparse
import io
import json
import time
import wave
from pathlib import Path
from .engine import LocalModels

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    models = LocalModels()
    result = {'fixture': 'Déjame consultar.', 'kind': 'synthetic_tts_stt_round_trip',
              'microphone_tested': False, 'browser_wake_tested': False}
    for state in ('cold', 'warm'):
        started = time.perf_counter()
        audio = models.synthesize(result['fixture'])
        result[f'tts_{state}_seconds'] = time.perf_counter() - started
    with wave.open(io.BytesIO(audio)) as wav:
        result['audio_seconds'] = wav.getnframes() / wav.getframerate()
    for state in ('cold', 'warm'):
        started = time.perf_counter()
        transcript = models.transcribe(audio)
        result[f'stt_{state}_seconds'] = time.perf_counter() - started
        result[f'transcript_{state}'] = transcript['text']
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding='utf-8')

if __name__ == '__main__':
    main()
