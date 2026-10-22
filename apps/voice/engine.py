"""Local-only inference with bounded decoding and a restartable process deadline."""
import io
import multiprocessing as mp
import os
from pathlib import Path
import re
import threading
import wave

MAX_SECONDS = 30
MAX_TEXT = 1200

class VoiceUnavailable(RuntimeError):
    pass

class VoiceBusy(RuntimeError):
    pass

class LocalModels:
    def __init__(self):
        # Never let a library silently download a model while handling user audio.
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        self.root = Path(os.getenv('MODEL_DIR', 'models/cache')).resolve()
        self.stt = None
        self.tts = None

    def transcribe(self, data):
        import av
        import numpy as np
        from faster_whisper import WhisperModel
        path = self.root / 'whisper-small'
        if not (path / 'model.bin').is_file():
            raise VoiceUnavailable('Whisper model missing; run the explicit model download command')
        # Decode incrementally to stop compressed audio bombs before materializing them.
        frames, samples = [], 0
        with av.open(io.BytesIO(data)) as container:
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples += converted.samples
                    if samples > MAX_SECONDS * 16000:
                        raise ValueError('Audio exceeds 30 seconds')
                    frames.append(converted.to_ndarray().flatten())
            for converted in resampler.resample(None):
                samples += converted.samples
                if samples > MAX_SECONDS * 16000:
                    raise ValueError('Audio exceeds 30 seconds')
                frames.append(converted.to_ndarray().flatten())
        if samples < 1600:
            raise ValueError('Audio must contain at least 100 milliseconds')
        audio = np.concatenate(frames).astype(np.float32) / 32768.0
        if self.stt is None:
            self.stt = WhisperModel(str(path), device=os.getenv('VOICE_DEVICE', 'cpu'),
                                   compute_type=os.getenv('WHISPER_COMPUTE_TYPE', 'int8'), local_files_only=True)
        segments, _ = self.stt.transcribe(audio, language='es', beam_size=1,
                                         condition_on_previous_text=False, vad_filter=False)
        return {'text': ' '.join(segment.text.strip() for segment in segments).strip()}

    def synthesize(self, text):
        import numpy as np
        from kokoro import KModel, KPipeline
        path = self.root / 'kokoro'
        required = ['config.json', 'kokoro-v1_0.pth', 'ef_dora.pt']
        if not all((path / name).is_file() for name in required):
            raise VoiceUnavailable('Kokoro Spanish model missing; run the explicit model download command')
        if self.tts is None:
            model = KModel(repo_id='hexgrad/Kokoro-82M', config=str(path / 'config.json'),
                           model=str(path / 'kokoro-v1_0.pth')).to(os.getenv('VOICE_DEVICE', 'cpu')).eval()
            self.tts = KPipeline(lang_code='e', model=model, repo_id='hexgrad/Kokoro-82M')
        # Spanish Kokoro can truncate long phoneme sequences. Keep each chunk short.
        chunks = []
        for sentence in re.split(r'(?<=[.!?;])\s+|\n+', text):
            words, current = sentence.split(), ''
            for word in words:
                if len(current) + len(word) > 100:
                    chunks.append(current)
                    current = ''
                current += (' ' if current else '') + word
            if current:
                chunks.append(current)
        audio_parts, samples = [], 0
        for chunk in chunks:
            for _, _, audio in self.tts(chunk, voice=str(path / 'ef_dora.pt')):
                if audio is None:
                    raise VoiceUnavailable('TTS did not produce audio')
                array = audio.cpu().numpy()
                samples += len(array)
                if samples > 120 * 24000:
                    raise ValueError('Generated audio exceeds 120 seconds')
                audio_parts.append(array)
        if not audio_parts:
            raise ValueError('No text to synthesize')
        pcm = (np.clip(np.concatenate(audio_parts), -1, 1) * 32767).astype('<i2')
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm.tobytes())
        return output.getvalue()


def _run(connection):
    models = LocalModels()
    while True:
        try:
            operation, payload = connection.recv()
        except EOFError:
            return
        try:
            result = getattr(models, operation)(payload)
            connection.send(('ok', result))
        except (ValueError, EOFError):
            connection.send(('invalid', 'Unsupported, empty, or oversized audio/text'))
        except Exception:
            # Do not expose host paths, model details or user audio in error logs.
            connection.send(('unavailable', 'Local inference unavailable; check installed models and runtime dependencies'))


class ProcessEngine:
    def __init__(self, timeout=90):
        self.timeout = timeout
        self.lock = threading.Lock()
        self.process = None
        self.connection = None

    def close(self):
        # Closing the parent pipe lets an idle worker exit normally and release
        # inference-library semaphores. An active/hung worker is still killed.
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None:
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=3)
            self.process = None

    def invoke(self, operation, payload):
        if operation not in {'transcribe', 'synthesize'}:
            raise ValueError('Unknown operation')
        if not self.lock.acquire(blocking=False):
            raise VoiceBusy('Voice worker is busy')
        try:
            if self.process is None or not self.process.is_alive():
                self.close()
                context = mp.get_context('spawn')
                self.connection, child = context.Pipe()
                self.process = context.Process(target=_run, args=(child,), daemon=True)
                self.process.start()
                child.close()
            self.connection.send((operation, payload))
            if not self.connection.poll(self.timeout):
                self.close()
                raise VoiceUnavailable('Local inference deadline exceeded')
            status, result = self.connection.recv()
            if status == 'invalid':
                raise ValueError(result)
            if status != 'ok':
                raise VoiceUnavailable(result)
            return result
        except (EOFError, BrokenPipeError, OSError) as error:
            self.close()
            raise VoiceUnavailable('Local inference process stopped') from error
        finally:
            self.lock.release()
