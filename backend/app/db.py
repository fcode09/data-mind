"""Conexión MongoDB en modo SOLO LECTURA.

El agente jamás escribe: solo find/aggregate/count/distinct.
Se usa un cliente con timeout y `retryWrites=false` como cinturón extra.
"""

from pymongo import MongoClient
from pymongo.database import Database

from .config import settings

_client: MongoClient | None = None
_indexes_ensured: bool = False

# Índices de lectura para gueo2021.incidents (filtros + sort + ticket).
INCIDENT_INDEXES: list[tuple[str, int]] = [
    ("incident_state", 1),
    ("category_name", 1),
    ("workgroup_name", 1),
    ("incident_district", 1),
    ("incident_creation_date", -1),
    ("incident_ticket_number", 1),
]


def ensure_incident_indexes(db=None) -> dict:
    """Crea índices faltantes de forma tolerante (nunca raisea).

    Pensado para llamarse al arrancar o desde scripts/ensure_indexes.py.
    Devuelve {"created": [...], "skipped": [...]}.
    """
    global _indexes_ensured
    created: list[str] = []
    skipped: list[str] = []
    try:
        target = db if db is not None else get_db()
        coll = target["incidents"]
        try:
            info = coll.index_information()
            existing = set(info.keys())
            # Campos ya cubiertos por un índice simple (cualquier nombre):
            # evita el error 85 IndexOptionsConflict al re-crear con otro nombre.
            covered = set()
            for spec in info.values():
                key = spec.get("key") or []
                if len(key) == 1:
                    covered.add(key[0][0])
        except Exception:
            existing = set()
            covered = set()
        for field, direction in INCIDENT_INDEXES:
            name = f"idx_{field}"
            if name in existing or field in covered:
                skipped.append(name)
                continue
            try:
                coll.create_index([(field, direction)], name=name, background=True)
                created.append(name)
            except Exception:
                # Índice ya existe con otro nombre/opciones, o sin permiso: tolerar.
                skipped.append(name)
    except Exception:
        pass
    _indexes_ensured = True
    return {"created": created, "skipped": skipped}


def get_client() -> MongoClient:
    global _client, _indexes_ensured
    if _client is None:
        _client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=settings.QUERY_TIMEOUT_MS,
            retryWrites=False,  # refuerza el modo solo-lectura
        )
        # Ping para fallar rápido si Mongo no está disponible
        _client.admin.command("ping")
        # Best-effort: asegurar índices sin bloquear ni romper si falla.
        try:
            ensure_incident_indexes(_client[settings.MONGO_DB])
        except Exception:
            pass
    return _client


def get_db() -> Database:
    return get_client()[settings.MONGO_DB]


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
