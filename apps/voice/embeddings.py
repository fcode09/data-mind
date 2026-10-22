"""Local E5 embeddings for synthetic SOP retrieval; no network fallback."""
import asyncio
import hmac
import hashlib
import os
from pathlib import Path
import threading
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, StringConstraints, field_validator

MODEL_ID = 'intfloat/multilingual-e5-small'
REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
DIMENSIONS = 384
PINNED_FILES = {'1_Pooling/config.json': '987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0', 'config.json': '69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959', 'model.safetensors': '1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477', 'modules.json': 'c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04', 'sentence_bert_config.json': '948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529', 'sentencepiece.bpe.model': 'cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865', 'special_tokens_map.json': 'd05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7', 'tokenizer.json': '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39', 'tokenizer_config.json': 'a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b'}
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]

class EmbeddingRequest(BaseModel):
    texts: list[Text] = Field(min_length=1, max_length=32)
    kind: Literal['query', 'passage']

    @field_validator('texts')
    @classmethod
    def nonempty(cls, texts):
        if any(not text.strip() for text in texts):
            raise ValueError('Texts cannot be blank')
        return texts

class LocalEmbeddings:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def encode(self, texts, kind):
        if kind not in ('query', 'passage') or not 1 <= len(texts) <= 32:
            raise ValueError('Invalid embedding request')
        if any(not text.strip() or len(text) > 2000 for text in texts):
            raise ValueError('Invalid embedding text')
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Embedding worker is busy')
        try:
            root = Path(os.getenv('EMBEDDING_MODEL_DIR', 'models/cache/multilingual-e5-small'))
            if not (root / 'model.safetensors').is_file():
                raise FileNotFoundError('Embedding model is not provisioned')
            if self.model is None:
                for name, expected in PINNED_FILES.items():
                    path = root / name
                    if not path.is_file():
                        raise FileNotFoundError('Embedding model files are incomplete')
                    checksum = hashlib.sha256()
                    with path.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            checksum.update(chunk)
                    if checksum.hexdigest() != expected:
                        raise ValueError('Embedding model integrity check failed')
                os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['TRANSFORMERS_OFFLINE'] = '1'
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(str(root.resolve()), device='cpu', local_files_only=True, trust_remote_code=False)
                self.model.max_seq_length = 512
            vectors = self.model.encode([f'{kind}: {text.strip()}' for text in texts], normalize_embeddings=True, batch_size=8, convert_to_numpy=True)
            import numpy as np
            if vectors.shape != (len(texts), DIMENSIONS) or not np.isfinite(vectors).all():
                raise ValueError('Invalid embedding output')
            return {'vectors': vectors.tolist(), 'dimensions': DIMENSIONS, 'model': MODEL_ID, 'revision': REVISION, 'normalized': True, 'kind': kind}
        finally:
            self.lock.release()

engine = LocalEmbeddings()
router = APIRouter()

def authorize(authorization: str = Header(default='')):
    token = os.getenv('MODEL_INTERNAL_TOKEN') or os.getenv('VOICE_INTERNAL_TOKEN') or os.getenv('MCP_INTERNAL_TOKEN')
    if not token:
        raise HTTPException(503, 'Internal model authentication is not configured')
    if not hmac.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'Unauthorized')

@router.post('/embed', dependencies=[Depends(authorize)])
async def embed(request: EmbeddingRequest):
    try:
        return await asyncio.to_thread(engine.encode, request.texts, request.kind)
    except BlockingIOError:
        raise HTTPException(429, 'Embedding worker is busy', headers={'Retry-After': '1'})
    except FileNotFoundError:
        raise HTTPException(503, 'Local embedding model is not provisioned')
    except Exception:
        raise HTTPException(503, 'Local embedding inference failed')
