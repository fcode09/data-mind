"""Persistencia de conversaciones en una DB PROPIA (`data_mind`).

Ojo: esto NO toca gueo2021 (que sigue siendo solo-lectura).
Son datos de nuestra app: historial del chat.
"""

from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId
from pymongo import MongoClient

from ..config import settings

DB_NAME = "data_mind"
COLL = "conversations"

# Slots conversacionales: memoria mínima por conversación (mismo doc).
# - ultima_pregunta: última pregunta de datos (no saludo/seguimiento)
# - ultimo_resumen: respuesta anterior truncada a 800 chars
# - ultimo_filtro: dict de filtros del router/tools
# - ultimo_total: int total de documentos de la última evidencia
# - ultimo_ticket: ticket del incidente mencionado (seguimiento_entidad, 0 DB)
# - ultimo_incidente_resumen: 1 línea humana del último incidente
# - ultima_fecha: fecha ISO del último incidente (para "a qué hora")
# - display_tz: zona del cliente usada (America/Lima por defecto)
MAX_RESUMEN_CHARS = 800

_SLOT_DEFAULTS = {
    "ultima_pregunta": None,
    "ultimo_resumen": None,
    "ultimo_filtro": {},
    "ultimo_total": None,
    "ultimo_ticket": None,
    "ultimo_incidente_resumen": None,
    "ultima_fecha": None,
    "display_tz": None,
    "updated_at": None,
}

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Cliente único de módulo (no uno por llamada). Thread-safe (pymongo)."""
    global _client
    if _client is None:
        _client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            retryWrites=True,
        )
    return _client


def close_store_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def get_store_db():
    return get_client()[DB_NAME]


def new_conversation(first_question: str) -> str:
    db = get_store_db()
    cid = str(uuid4())
    title = first_question.strip()[:60] or "Conversación"
    now = datetime.now(timezone.utc)
    db[COLL].insert_one({
        "_id": cid,
        "title": title,
        "created_at": now,
        "messages": [],
        # Slots conversacionales (memoria por conversación, mismo doc).
        "ultima_pregunta": None,
        "ultimo_resumen": None,
        "ultimo_filtro": {},
        "ultimo_total": None,
        "ultimo_ticket": None,
        "ultimo_incidente_resumen": None,
        "ultima_fecha": None,
        "display_tz": None,
        "updated_at": now,
    })
    return cid


def append_messages(cid: str, messages: list[dict]) -> None:
    db = get_store_db()
    db[COLL].update_one({"_id": cid}, {"$push": {"messages": {"$each": messages}}})


def list_conversations(limit: int = 30) -> list[dict]:
    db = get_store_db()
    cur = db[COLL].find({}, {"messages": 0}).sort("created_at", -1).limit(limit)
    out = []
    for d in cur:
        d["id"] = d.pop("_id")
        out.append(d)
    return out


def get_conversation(cid: str) -> dict | None:
    db = get_store_db()
    d = db[COLL].find_one({"_id": cid})
    if not d:
        # compatibilidad con ObjectIds antiguos si los hubiera
        try:
            d = db[COLL].find_one({"_id": ObjectId(cid)})
        except Exception:
            return None
    if not d:
        return None
    d["id"] = str(d.pop("_id"))
    return d


def get_slots(cid: str) -> dict:
    """Lee la memoria conversacional (1 lectura). Nunca raisea: retorna defaults."""
    defaults = dict(_SLOT_DEFAULTS)
    defaults["ultimo_filtro"] = {}
    if not cid:
        return defaults
    try:
        db = get_store_db()
        d = db[COLL].find_one(
            {"_id": cid},
            {"ultima_pregunta": 1, "ultimo_resumen": 1,
             "ultimo_filtro": 1, "ultimo_total": 1,
             "ultimo_ticket": 1, "ultimo_incidente_resumen": 1,
             "ultima_fecha": 1, "display_tz": 1, "updated_at": 1},
        )
        if not d:
            try:
                d = db[COLL].find_one(
                    {"_id": ObjectId(cid)},
                    {"ultima_pregunta": 1, "ultimo_resumen": 1,
                     "ultimo_filtro": 1, "ultimo_total": 1,
                     "ultimo_ticket": 1, "ultimo_incidente_resumen": 1,
                     "ultima_fecha": 1, "display_tz": 1, "updated_at": 1},
                )
            except Exception:
                d = None
        if not d:
            return defaults
        return {
            "ultima_pregunta": d.get("ultima_pregunta"),
            "ultimo_resumen": d.get("ultimo_resumen"),
            "ultimo_filtro": d.get("ultimo_filtro") or {},
            "ultimo_total": d.get("ultimo_total"),
            "ultimo_ticket": d.get("ultimo_ticket"),
            "ultimo_incidente_resumen": d.get("ultimo_incidente_resumen"),
            "ultima_fecha": d.get("ultima_fecha"),
            "display_tz": d.get("display_tz"),
            "updated_at": d.get("updated_at"),
        }
    except Exception:
        return defaults


def save_slots(cid: str, ultima_pregunta: str | None = None,
               ultimo_resumen: str | None = None,
               ultimo_filtro: dict | None = None,
               ultimo_total: int | None = None,
               ultimo_ticket: str | None = None,
               ultimo_incidente_resumen: str | None = None,
               ultima_fecha: str | None = None,
               display_tz: str | None = None) -> None:
    """Upsert de slots en el MISMO doc de conversación ($set, sin replace).

    Solo pisa los campos que vienen no-None. ultimo_resumen se trunca a 800 chars.
    Tolerante a caídas de data_mind y a ids efímeros (no raisea).
    """
    if not cid or cid.startswith("ephemeral-"):
        return
    try:
        update: dict = {"updated_at": datetime.now(timezone.utc)}
        if ultima_pregunta is not None:
            update["ultima_pregunta"] = ultima_pregunta
        if ultimo_resumen is not None:
            update["ultimo_resumen"] = (ultimo_resumen or "")[:MAX_RESUMEN_CHARS]
        if ultimo_filtro is not None:
            update["ultimo_filtro"] = ultimo_filtro or {}
        if ultimo_total is not None:
            update["ultimo_total"] = ultimo_total
        if ultimo_ticket is not None:
            update["ultimo_ticket"] = ultimo_ticket
        if ultimo_incidente_resumen is not None:
            update["ultimo_incidente_resumen"] = (ultimo_incidente_resumen or "")[:MAX_RESUMEN_CHARS]
        if ultima_fecha is not None:
            update["ultima_fecha"] = ultima_fecha
        if display_tz is not None:
            update["display_tz"] = display_tz
        db = get_store_db()
        db[COLL].update_one({"_id": cid}, {"$set": update}, upsert=True)
    except Exception:
        pass
