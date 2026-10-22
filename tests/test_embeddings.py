import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.voice import embeddings

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('MODEL_INTERNAL_TOKEN', 'embedding-test-token')
    app = FastAPI()
    app.include_router(embeddings.router)
    return TestClient(app)

def test_auth_and_bounds(client):
    assert client.post('/embed',json={'texts':['hola'],'kind':'query'}).status_code == 401
    headers={'Authorization':'Bearer embedding-test-token'}
    for body in ({'texts':[''] ,'kind':'query'}, {'texts':['x']*33,'kind':'query'}, {'texts':['x'*2001],'kind':'query'}, {'texts':['x'],'kind':'bad'}):
        assert client.post('/embed',headers=headers,json=body).status_code == 422

def test_missing_model_is_explicit(client, monkeypatch, tmp_path):
    monkeypatch.setenv('EMBEDDING_MODEL_DIR',str(tmp_path/'absent'))
    assert client.post('/embed',headers={'Authorization':'Bearer embedding-test-token'},json={'texts':['hola'],'kind':'query'}).status_code == 503

def test_busy_is_bounded(client, monkeypatch):
    def busy(*args): raise BlockingIOError()
    monkeypatch.setattr(embeddings.engine,'encode',busy)
    assert client.post('/embed',headers={'Authorization':'Bearer embedding-test-token'},json={'texts':['hola'],'kind':'query'}).status_code == 429
