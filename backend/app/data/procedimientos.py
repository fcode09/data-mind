"""SOP municipales (borrador) en DB propia `data_mind.procedimientos`.

Esquema: {subcategoria, categoria, pasos[{n, accion, responsable, plazo}],
          fuente, updated_at}
Retrieval tolerante: normaliza sin acentos, match exacto primero,
luego parcial (subcadena en ambos sentidos). Expone `fuente` para que
el agente diga "borrador por validar" y no lo presente como oficial.
"""

import unicodedata
from datetime import datetime, timezone

DB_NAME = "data_mind"
COLL = "procedimientos"

BORRADOR_FUENTE = "borrador-pendiente-validacion"


def _norm(text: str) -> str:
    t = (text or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def _get_db():
    from ..api.conversations import get_store_db
    return get_store_db()


def get_procedimiento(subcategoria: str | None) -> dict | None:
    """Recupera el SOP por subcategoría (tolerante a acentos/mayúsculas/parcial).

    Retorna el doc tal cual (con `fuente` para el flag borrador) o None.
    Nunca raisea.
    """
    if not subcategoria or not str(subcategoria).strip():
        return None
    try:
        db = _get_db()
        docs = list(db[COLL].find({}))
    except Exception:
        return None
    if not docs:
        return None
    nq = _norm(str(subcategoria))
    if not nq:
        return None
    # 1) exacto normalizado
    for d in docs:
        if _norm(str(d.get("subcategoria") or "")) == nq:
            return d
    # 2) parcial: subcadena en ambos sentidos (cubre "tala ilegal" vs
    # "actividad contra recursos naturales - tala ilegal", etc.)
    best = None
    best_len = -1
    for d in docs:
        nd = _norm(str(d.get("subcategoria") or ""))
        if not nd:
            continue
        if nq in nd or nd in nq:
            if len(nd) > best_len:
                best = d
                best_len = len(nd)
    if best is not None:
        return best
    # 3) token significativo (>4 chars) compartido, el más largo gana
    qtokens = [t for t in nq.split() if len(t) > 4]
    for d in docs:
        nd = _norm(str(d.get("subcategoria") or ""))
        for tok in qtokens:
            if tok in nd:
                if len(tok) > best_len:
                    best = d
                    best_len = len(tok)
                break
    return best


def list_subcategorias() -> list[str]:
    """Lista ordenada de subcategorías con SOP. Nunca raisea."""
    try:
        db = _get_db()
        docs = list(db[COLL].find({}, {"subcategoria": 1}))
        out = [str(d.get("subcategoria") or "").strip()
               for d in docs if (d.get("subcategoria") or "").strip()]
        return sorted(set(out))
    except Exception:
        return []


def seed_si_vacio(documentos: list[dict] | None = None) -> int:
    """Inserta `documentos` solo si la colección está vacía. Retorna nº insertados.

    Nunca raisea. Si no hay documentos que sembrar, retorna 0.
    Normaliza updated_at si falta.
    """
    try:
        db = _get_db()
        if db[COLL].estimated_document_count() > 0:
            return 0
        if not documentos:
            return 0
        now = datetime.now(timezone.utc)
        docs = []
        for d in documentos:
            dd = dict(d)
            dd.setdefault("updated_at", now)
            docs.append(dd)
        if not docs:
            return 0
        res = db[COLL].insert_many(docs)
        return len(res.inserted_ids or [])
    except Exception:
        return 0
