"""Local synthetic demonstration API. Production identity must replace demo sessions."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from datetime import date
from uuid import UUID
from typing import Literal
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
import httpx
from data_mind.contracts import Scope
from data_mind.orchestrator import answer
from data_mind.mcp_client import call_tool

app = FastAPI(title="Data Mind", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class Sessions(BaseModel):
    tenant_id: int = Field(ge=1, le=5)


class Turn(BaseModel):
    turn_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    from_date: date
    to_date_exclusive: date


class Feedback(BaseModel):
    turn_id: UUID
    rating: Literal[-1, 1]
    note: str = Field(default="", max_length=1000)


class Speak(BaseModel):
    turn_id: UUID


# A restart invalidates sessions when no explicit persistent demo secret was set.
secret = os.getenv("API_SESSION_SECRET", secrets.token_hex(32)).encode()
inflight: set[tuple[str, str]] = set()


def db():
    path = Path(os.getenv("API_STATE_PATH", "artifacts/api-state.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS turns (session TEXT, id TEXT, result TEXT, created REAL, PRIMARY KEY(session,id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feedback (session TEXT, turn_id TEXT, rating INTEGER, note TEXT, created REAL, PRIMARY KEY(session,turn_id))"
    )
    conn.execute("DELETE FROM turns WHERE created < ?", (time.time() - 30 * 86400,))
    conn.execute("DELETE FROM feedback WHERE created < ?", (time.time() - 30 * 86400,))
    conn.commit()
    return conn


def authenticate(authorization: str = Header(default="")):
    try:
        body, signature = authorization.removeprefix("Bearer ").split(".")
        expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if value["expires"] < time.time() or value["tenant_id"] not in range(1, 6):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Sesión inválida o caducada")


@app.get("/health")
def health():
    return {"status": "ok", "data": "synthetic-only"}


@app.post("/api/session")
def session(value: Sessions):
    if os.getenv("DEMO_MODE") != "true":
        raise HTTPException(
            403, "El inicio de sesión de demostración está deshabilitado"
        )
    payload = {
        "tenant_id": value.tenant_id,
        "id": secrets.token_urlsafe(18),
        "expires": int(time.time() + 28800),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    token = body + "." + hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return {
        "token": token,
        "tenant_id": value.tenant_id,
        "expires": payload["expires"],
        "demo": True,
    }


@app.get("/api/status")
async def status(
    from_date: date, to_date_exclusive: date, identity=Depends(authenticate)
):
    try:
        scope = Scope(
            tenant_id=identity["tenant_id"],
            from_date=from_date,
            to_date_exclusive=to_date_exclusive,
        )
        return await call_tool("dataset_status", scope)
    except Exception:
        raise HTTPException(503, "No se pudo consultar el estado de los datos")


@app.post("/api/turns")
async def turns(value: Turn, identity=Depends(authenticate)):
    key = (identity["id"], str(value.turn_id))
    with db() as conn:
        row = conn.execute(
            "SELECT result FROM turns WHERE session=? AND id=?", key
        ).fetchone()
    if row:
        return json.loads(row[0])
    if key in inflight:
        raise HTTPException(409, "Este turno ya está en curso")
    if len(inflight) >= 16:
        raise HTTPException(429, "Hay demasiadas consultas; vuelve a intentarlo")
    inflight.add(key)
    try:
        scope = Scope(
            tenant_id=identity["tenant_id"],
            from_date=value.from_date,
            to_date_exclusive=value.to_date_exclusive,
        )
        async with asyncio.timeout(25):
            result = await answer(value.message, scope)
        result["turn_id"] = str(value.turn_id)
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO turns VALUES(?,?,?,?)",
                (*key, json.dumps(result, ensure_ascii=False), time.time()),
            )
        return result
    except Exception:
        raise HTTPException(
            503, "No pude verificar la consulta. No se generó una respuesta con datos."
        )
    finally:
        inflight.discard(key)


@app.post("/api/feedback")
def feedback(value: Feedback, identity=Depends(authenticate)):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM turns WHERE session=? AND id=?",
            (identity["id"], str(value.turn_id)),
        ).fetchone():
            raise HTTPException(404, "Turno no encontrado")
        conn.execute(
            "INSERT OR REPLACE INTO feedback VALUES(?,?,?,?,?)",
            (identity["id"], str(value.turn_id), value.rating, value.note, time.time()),
        )
    return {"saved": True, "automatic_training": False}


def voice_headers():
    token = os.getenv("VOICE_INTERNAL_TOKEN", os.getenv("MCP_INTERNAL_TOKEN", ""))
    if not token:
        raise HTTPException(503, "Servicio de voz no configurado")
    return {"Authorization": "Bearer " + token}


@app.post("/api/voice/transcribe")
async def transcribe(file: UploadFile = File(...), identity=Depends(authenticate)):
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Audio demasiado largo")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                os.getenv("VOICE_URL", "http://127.0.0.1:8102") + "/transcribe",
                headers=voice_headers(),
                files={"file": ("question.wav", data, "audio/wav")},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError:
        raise HTTPException(
            503,
            "El modelo local de voz no está disponible; puedes escribir tu consulta",
        )


@app.post("/api/voice/speak")
async def speak(value: Speak, identity=Depends(authenticate)):
    with db() as conn:
        row = conn.execute(
            "SELECT result FROM turns WHERE session=? AND id=?",
            (identity["id"], str(value.turn_id)),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Turno no encontrado")
    result = json.loads(row[0])
    if not result["verified"]:
        raise HTTPException(409, "La respuesta no tiene evidencia verificada")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                os.getenv("VOICE_URL", "http://127.0.0.1:8102") + "/synthesize",
                headers=voice_headers(),
                json={"text": result["answer"]},
            )
            response.raise_for_status()
            return Response(response.content, media_type="audio/wav")
    except httpx.HTTPError:
        raise HTTPException(
            503, "La voz local no está disponible; la respuesta está en pantalla"
        )
