"""Unit/HTTP contract tests with explicit fake inference, NOT real model tests."""
import io
import wave
from fastapi.testclient import TestClient
from apps.voice import main
from apps.voice.engine import ProcessEngine, VoiceBusy
import pytest

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('VOICE_INTERNAL_TOKEN', 'unit-test-only-token')
    return TestClient(main.app)

AUTH = {'Authorization': 'Bearer unit-test-only-token'}

def test_auth_closed(client, monkeypatch):
    assert client.get('/health').status_code == 401
    monkeypatch.delenv('VOICE_INTERNAL_TOKEN')
    monkeypatch.delenv('MCP_INTERNAL_TOKEN', raising=False)
    assert client.get('/health', headers=AUTH).status_code == 503

def test_transcription_contract(client, monkeypatch):
    monkeypatch.setattr(main.engine, 'invoke', lambda operation, payload: {'text': 'Consulta de prueba'})
    response = client.post('/transcribe', files={'file': ('sample.webm', b'fake-audio', 'audio/webm')}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {'text': 'Consulta de prueba'}

def test_empty_and_large_audio(client):
    assert client.post('/transcribe', files={'file': ('x.wav', b'')}, headers=AUTH).status_code == 422
    response = client.post('/transcribe', files={'file': ('x.wav', b'x'*(main.MAX_UPLOAD+1))}, headers=AUTH)
    assert response.status_code == 413

def test_tts_wav_contract(client, monkeypatch):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(b'\0\0'*240)
    monkeypatch.setattr(main.engine, 'invoke', lambda operation, payload: output.getvalue())
    response = client.post('/synthesize', json={'text': 'Prueba'}, headers=AUTH)
    assert response.status_code == 200
    assert response.content[:4] == b'RIFF'
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/synthesize', json={'text': ' '*3}, headers=AUTH).status_code == 422
    assert client.post('/synthesize', json={'text': 'x'*1201}, headers=AUTH).status_code == 422

def test_busy_rejected(client, monkeypatch):
    def busy(*args): raise VoiceBusy('Busy')
    monkeypatch.setattr(main.engine, 'invoke', busy)
    assert client.post('/synthesize', json={'text': 'Prueba'}, headers=AUTH).status_code == 429

def test_engine_lock():
    engine = ProcessEngine()
    engine.lock.acquire()
    try:
        with pytest.raises(VoiceBusy): engine.invoke('transcribe', b'a')
    finally:
        engine.lock.release()

def test_archive_rejects_traversal(tmp_path):
    import zipfile
    from scripts.download_models import browser_archive
    source = tmp_path / 'bad.zip'
    with zipfile.ZipFile(source, 'w') as archive: archive.writestr('../bad', 'bad')
    with pytest.raises(ValueError): browser_archive(source, tmp_path/'model.tar.gz')

def test_digest_verification(tmp_path):
    from scripts.download_models import acquire
    source = tmp_path/'source'
    source.write_bytes(b'bad')
    with pytest.raises(ValueError):
        acquire({'path':'model.bin','url':source.as_uri(),'size':3,'sha256':'0'*64}, tmp_path/'out')
    assert not (tmp_path/'out/model.bin').exists()

def _slow_worker(connection):
    import time
    time.sleep(30)

def test_worker_deadline_terminates_process(monkeypatch):
    from apps.voice import engine as module
    monkeypatch.setattr(module, '_run', _slow_worker)
    engine = ProcessEngine(timeout=0.1)
    try:
        with pytest.raises(module.VoiceUnavailable, match='deadline'):
            engine.invoke('transcribe', b'fake')
        assert engine.process is None
        assert engine.connection is None
        assert not engine.lock.locked()
    finally:
        engine.close()

def test_browser_archive_expected_layout(tmp_path):
    import zipfile, tarfile
    from scripts.download_models import browser_archive
    source = tmp_path/'model.zip'
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('vosk-model-small-es-0.42/am/final.mdl', 'fixture')
    output = tmp_path/'model.tar.gz'
    browser_archive(source,output)
    with tarfile.open(output) as archive:
        assert archive.getnames() == ['model/am/final.mdl']
