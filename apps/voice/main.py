"""Internal local voice service. Run one Uvicorn worker, bound to 127.0.0.1."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .engine import MAX_TEXT, ProcessEngine, VoiceBusy, VoiceUnavailable

MAX_UPLOAD = 4 * 1024 * 1024
engine = ProcessEngine(timeout=90)

@asynccontextmanager
async def lifespan(app):
    yield
    engine.close()

app = FastAPI(title='Data Mind Local Voice', lifespan=lifespan)
from .embeddings import router as embedding_router
app.include_router(embedding_router)

class UploadLimit:
    """Bound the full streamed HTTP body before multipart parsing can spool to disk."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > MAX_UPLOAD + 65536:
                raise HTTPException(413, 'Request body too large')
            return message
        await self.app(scope, limited_receive, send)
app.add_middleware(UploadLimit)

def authorize(authorization: str = Header(default='')):
    token = os.getenv('VOICE_INTERNAL_TOKEN') or os.getenv('MCP_INTERNAL_TOKEN')
    if not token:
        raise HTTPException(503, 'Internal authentication is not configured')
    if not hmac.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'Unauthorized')

async def invoke(operation, payload):
    try:
        return await asyncio.to_thread(engine.invoke, operation, payload)
    except VoiceBusy as error:
        raise HTTPException(429, str(error), headers={'Retry-After': '2'}) from error
    except VoiceUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

@app.get('/health', dependencies=[Depends(authorize)])
def health():
    return {'status': 'service_ready', 'models': 'loaded_lazily', 'inference_verified': False}

@app.post('/transcribe', dependencies=[Depends(authorize)])
async def transcribe(file: UploadFile = File(...)):
    try:
        payload = await file.read(MAX_UPLOAD + 1)
    finally:
        await file.close()
    if not payload:
        raise HTTPException(422, 'Empty audio')
    if len(payload) > MAX_UPLOAD:
        raise HTTPException(413, 'Audio upload exceeds 4 MiB')
    return await invoke('transcribe', payload)

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)

@app.post('/synthesize', dependencies=[Depends(authorize)])
async def synthesize(request: SpeechRequest):
    if not request.text.strip():
        raise HTTPException(422, 'Empty text')
    audio = await invoke('synthesize', request.text)
    return Response(content=audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('apps.voice.main:app', host='127.0.0.1', port=8102, workers=1)
