"""API data-mind: chat sobre incidentes (LLM OpenAI-compatible + Mongo solo-lectura)."""

import json
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent.agent import build_chart, clean_answer, gather_evidence, stream_answer
from .api import conversations as store
from .config import settings
from .db import close_client, get_db
from .decide.router import route
from .decide.verify import verify_routed


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_client()
    try:
        store.close_store_client()
    except Exception:
        pass


app = FastAPI(title="DataMind API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    client_tz: str | None = None


DEFAULT_TZ = "America/Lima"


def _resolve_tz(raw: str | None) -> str:
    """IANA válida o America/Lima. Nunca raisea, nunca 500 por tz."""
    cand = (raw or "").strip() or DEFAULT_TZ
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(cand)
        return cand
    except Exception:
        return DEFAULT_TZ


def _today_in_tz(tz_name: str) -> str:
    """YYYY-MM-DD de hoy en la zona del cliente."""
    from datetime import datetime, timedelta, timezone as _tz
    try:
        from zoneinfo import ZoneInfo
        try:
            return datetime.now(ZoneInfo(tz_name)).date().isoformat()
        except Exception:
            pass
        try:
            from zoneinfo import ZoneInfo as _Z2
            return datetime.now(_Z2("America/Lima")).date().isoformat()
        except Exception:
            pass
    except Exception:
        pass
    return (datetime.now(_tz.utc) + timedelta(hours=-5)).date().isoformat()


@app.get("/health")
def health():
    try:
        from .decide.router import ROUTER_VERSION as _rv
    except Exception:
        _rv = "desconocida"
    try:
        db = get_db()
        n = db["incidents"].estimated_document_count()
        return {"status": "ok", "mongo_db": db.name, "incidents": n,
                "llm_configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL,
                "llm_base_url": settings.LLM_BASE_URL,
                "jev_configured": bool(settings.JEV_API_KEY),
                "jev_enabled": bool(settings.JEV_ENABLED),
                "router_version": _rv}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Mongo no disponible: {exc}")


def _history_for_llm(cid: str | None) -> list[dict]:
    """Últimos 6 turnos (texto) como contexto del agente. Tolerante a caídas de data_mind.

    Assistant truncado a 800 chars para acotar prompt sin perder hilo.
    """
    if not cid:
        return []
    try:
        convo = store.get_conversation(cid)
    except Exception:
        return []
    if not convo:
        return []
    out: list[dict] = []
    for m in convo.get("messages", [])[-6:]:
        if m["role"] not in ("user", "assistant"):
            continue
        content = m.get("content", "") or ""
        if m["role"] == "assistant" and len(content) > 800:
            content = content[:800]
        out.append({"role": m["role"], "content": content})
    return out


# ---------------------------------------------------------------------------
# Fast-paths conversacionales (funciones separadas: NO tocan verify/jev_block).
# 0 LLM / 0 tools. Saludo: 0 DB incidentes. Seguimiento: 1 lectura (slots).
# ---------------------------------------------------------------------------

def _norm_fast(text: str) -> str:
    import unicodedata
    t = (text or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _build_jev_block(origen: str, ruta: str, conf: float, veredicto: dict) -> dict:
    """Bloque jev unificado dual-compat.

    - `ruta` (contrato futuro) + `intencion=ruta` (compat front actual que lee
      `jev.intencion` en SourcesPanel).
    - `veredicto_ok` + `ok` (alias futuro).
    - `fallos` + `verificacion={ok,fallos}` (compat front actual que lee
      `jev.verificacion.ok/fallos` para el chip discreto).
    - `types.ts` NO se toca: el front ignora claves extra.
    """
    ok = bool(veredicto.get("ok", True))
    fallos = veredicto.get("fallos", []) or []
    block: dict = {
        "origen": veredicto.get("origen", origen),
        "ruta": ruta,
        "intencion": ruta,
        "confidence": conf,
        "veredicto_ok": ok,
        "ok": ok,
        "fallos": fallos,
        "verificacion": {"ok": ok, "fallos": fallos},
    }
    if "detalle" in veredicto:
        block["detalle"] = veredicto["detalle"]
    return block


def _fast_meta(cid: str, origen: str, ruta: str, conf: float) -> dict:
    return {"conversation_id": cid, "sources": [], "chart": None,
            "jev": _build_jev_block(
                origen, ruta, conf, {"ok": True, "fallos": [], "origen": origen})}


# Contador global para rotación de saludos: garantiza que dos saludos
# seguidos NO devuelvan texto idéntico (hash del minuto solo no basta
# porque dos llamadas en el mismo minuto colisionarían).
_SALUDO_SEQ = 0


def _fast_saludo_text(question: str) -> str:
    """Respuesta local humana (<50ms, 0 LLM/0 DB). Rota entre 3 variantes."""
    global _SALUDO_SEQ
    n = _norm_fast(question)
    if "gracias" in n:
        return ("¡De nada! Si quieres, seguimos con los incidentes: "
                "puedo darte conteos, rankings de tiempos, detalles o tendencias.")
    if "adios" in n or "chau" in n:
        return "¡Hasta luego! Aquí estaré cuando quieras analizar los incidentes."
    if "quien eres" in n or "que haces" in n or "que puedes hacer" in n or "ayuda" in n:
        return ("¡Hola! Soy DataMind, analista de incidentes del sistema municipal. "
                "Puedo ayudarte con conteos, rankings de tiempos, "
                "detalles de tickets y tendencias. ¿Por dónde empezamos?")
    # Saludo genérico (hola, cómo estás, qué tal, todo bien, ...): 3 variantes.
    import time as _t
    variantes = (
        # Corta.
        ("¡Hola! Soy DataMind. Puedo ayudarte con conteos, rankings de tiempos, "
         "detalles de tickets y tendencias de incidentes. ¿Qué analizamos?"),
        # Con ejemplos.
        ("¡Hola! Qué bueno verte por aquí. Trabajo con los incidentes municipales: "
         "dime por ejemplo cuántos hay por estado o cuál fue el último reporte, "
         "y lo revisamos."),
        # Con pregunta de arranque.
        ("¡Hola! Soy DataMind, tu analista de incidentes. ¿Empezamos por conteos, "
         "tiempos, un ticket o tendencias? Dime y lo vemos."),
    )
    minuto = int(_t.time() // 60)
    idx = (_SALUDO_SEQ + minuto) % len(variantes)
    _SALUDO_SEQ += 1
    return variantes[idx]


def _fast_seguimiento_text(question: str, slots: dict) -> str:
    """Respuesta local desde slots (0 tools, 0 LLM). Cita en 1 línea, sin tocho."""
    n = _norm_fast(question)
    ultima = (slots.get("ultima_pregunta") or "").strip()
    resumen = (slots.get("ultimo_resumen") or "").strip()
    total = slots.get("ultimo_total")
    if not ultima and not resumen:
        return ("Aún no tengo una pregunta previa en esta conversación. "
                "¿Empezamos por cuántos incidentes hay por estado?")
    # "resumen/resúmelo": devuelve el último resumen guardado (ya truncado a 800).
    if "resumen" in n or "resumelo" in n:
        if resumen:
            suffix = f" (total: {total})" if isinstance(total, int) else ""
            return f"Resumen de lo último{suffix}: {resumen}"
        short = ultima[:200]
        return f"Me preguntaste: «{short}». ¿Quieres que lo resuma por estado o por categoría?"
    # "qué te pregunté / qué dije": cita la última pregunta en 1 línea.
    if "que te pregunte" in n or "que me preguntaste" in n or "que dije" in n:
        short = ultima[:200] if ultima else resumen[:200]
        return f"Me preguntaste: «{short}»."
    # "y de esos/ellos, explícame más, por qué, detalla": ancla a la última pregunta.
    short = ultima[:200] if ultima else resumen[:200]
    return (f"Sobre lo que me preguntaste («{short}»): dime si quieres el detalle "
            f"por estado, categoría o distrito y lo vemos.")


def _looks_procedimiento_fast(n: str) -> bool:
    """¿Pide cómo resolver/atender/proceder? (fallthrough a slow con plan SOP).

    `n` ya viene normalizada sin acentos. Solo infinitivo/presente + frases
    de acción; el pasado (resolvio/resuelto/estado) NO es procedimiento.
    """
    if not n:
        return False
    for k in ("como resolver", "como resuelvo", "como lo resuelvo",
              "como puedo resolver", "como lo puedo resolver",
              "como atender", "como atiendo", "como proceder",
              "como procedo", "que debo hacer", "que tengo que hacer",
              "pasos", "protocolo", "procedimiento"):
        if k in n:
            return True
    if "como" in n and ("resolver" in n or "resuelvo" in n
                        or "atender" in n or "atiendo" in n
                        or "proceder" in n or "procedo" in n):
        return True
    return False


def _humanize_base(resumen: str) -> str:
    """Convierte 'Sub · Dist · Estado' en fragmento humano sin la tupla cruda.

    Nunca devuelve el literal con ' · ' (ej. 'Keeper pruebas · Municipalidad...').
    """
    r = (resumen or "").strip()
    if not r:
        return ""
    if "·" in r:
        parts = [p.strip() for p in r.split("·") if p.strip()]
        if len(parts) >= 3:
            return f", por {parts[0]} en {parts[1]} ({parts[2].lower()})"
        if len(parts) == 2:
            return f", {parts[0]} en {parts[1]}"
        return ", " + ", ".join(parts)
    return f" ({r})"


def _slow_entity_detail(ticket: str) -> str | None:
    """Ficha del ticket vía incident_detail directo, SIN loop LLM. 3 líneas.

    Nunca raisea: retorna None si no hay DB o no se encuentra.
    """
    t = (ticket or "").strip()
    if not t:
        return None
    try:
        from .data.tools import incident_detail as _detail
        db = get_db()
        res = _detail(db, ticket_number=t)
        data = (res or {}).get("data") or {}
        if not data.get("encontrado"):
            return (f"No encontré el reporte {t} en la base. "
                    f"¿Me confirmas el número?")
        inc = data.get("incidente") or {}
        estado = (inc.get("incident_state") or "sin estado").strip()
        sub = (inc.get("subcategory_name")
               or inc.get("category_name") or "reporte").strip()
        dist = (inc.get("incident_district") or "").strip()
        fecha = (inc.get("incident_creation_date_lima") or "").strip()
        prio = (inc.get("incident_priority") or "").strip()
        l1 = f"El reporte {t} es por {sub}" + (f" en {dist}" if dist else "") + "."
        l2 = (f"Está en estado **{estado}**"
              + (f" (registrado {fecha})" if fecha else "") + ".")
        l3 = (f"Es prioridad {prio} según la base." if prio
              else "Ese es su estado actual según la base.")
        return f"{l1}\n{l2}\n{l3}"
    except Exception:
        return None


def _fast_seguimiento_entidad_text(question: str, slots: dict) -> str | None:
    """Respuesta con intención desde slots (+1 DB solo para estado).

    - numero -> ticket de slots (sin 'dime si quieres').
    - hora -> fecha Lima de slots.
    - estado/resolvio/proceso -> CONSULTA REAL incident_detail (1 tool),
      responde el dato, prohibido preguntar de vuelta.
    - procedimiento/como -> None (fallthrough a slow path con plan SOP).
    - sin match -> plantilla humanizada (usa ultimo_incidente_resumen sin la
      tupla cruda con ' · '; NO cita '(Venía de:)' — eso es solo de seguimiento
      genérico). Retorna None si no hay entidad (fallthrough a DB).
    """
    import unicodedata
    n = (question or "").lower()
    n = unicodedata.normalize("NFD", n)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    ticket = ((slots or {}).get("ultimo_ticket") or "").strip()
    resumen = ((slots or {}).get("ultimo_incidente_resumen") or "").strip()
    fecha = ((slots or {}).get("ultima_fecha") or "").strip()
    if not ticket and not resumen:
        return None
    # Procedimiento: no responder plantilla, derivar al slow con SOP.
    if _looks_procedimiento_fast(n):
        return None
    base = _humanize_base(resumen)
    ref = f"El reporte {ticket}" if ticket else "El último reporte"
    if "numero" in n:
        if not ticket:
            return None
        return (f"{ref}{base} es el que veníamos siguiendo. "
                f"Guárdalo para pedir su estado o el tiempo transcurrido.")
    if "hora" in n:
        if fecha:
            return f"{ref} se registró {fecha}{base}."
        return (f"{ref}{base}. La hora exacta está en el detalle del reporte.")
    if "resolvio" in n or "resuelto" in n or "estado" in n or "proceso" in n:
        if ticket:
            real = _slow_entity_detail(ticket)
            if real is not None:
                return real
            # Sin DB: da el dato de slots, nunca repreguntes.
            est_hint = base or " según lo último visto"
            return (f"{ref}{est_hint}: ese es el último estado que tengo "
                    f"guardado.")
        return None
    return (f"Sobre {ref.lower()}{base}: dime si quieres el número, "
            f"la hora o su estado y lo vemos.")


def _build_tiempo_plan(cid: str) -> str:
    """Plan determinista para tiempo_transcurrido (lapso en Lima, a minuto).

    Nunca raisea. Trae el ticket de slots para guiar a incident_detail.
    """
    try:
        slots = store.get_slots(cid) or {}
        ticket = ((slots.get("ultimo_ticket") or "").strip())
    except Exception:
        ticket = ""
    if ticket:
        return (
            f"[contexto interno: preguntan CUÁNTO TIEMPO LLEVA el reporte {ticket}. "
            f"Llama UNA vez a incident_detail con ticket_number={ticket} "
            f"(si no existe, incidents_list limit=1). Calcula el lapso entre la "
            f"última actualización (incident_resolved_date o "
            f"incident_in_progress_date; si no hay, usa la hora actual en Lima) "
            f"y el inicio de atención (incident_creation_date), todo en Lima. "
            f"Redondea a MINUTO (ej. '3 días 4 h (aprox. 4560 min)'). PROHIBIDO "
            f"inventar segundos exactos o cifras sin tool. Responde en 2-3 líneas "
            f"con el lapso humano + la fecha Lima citada tal cual.]"
        )
    return (
        "[contexto interno: preguntan tiempo transcurrido sin ticket en memoria. "
        "Llama UNA vez a incidents_list limit=1 (el más reciente). Calcula el "
        "lapso última actualización − inicio atención en Lima, redondeo a MINUTO. "
        "PROHIBIDO segundos exactos inventados o cifras sin tool.]"
    )


def _build_procedimiento_plan(cid: str) -> str:
    """Plan determinista para procedimiento (SOP borrador o ficha+derivación).

    Intenta get_procedimiento(subcategoría de slots); si hay, instruye citar
    pasos + fuente (y avisar si es borrador). Si no, ficha + derivación al
    procedimiento oficial, sin inventar pasos. Nunca raisea.
    """
    subcat = ""
    try:
        slots = store.get_slots(cid) or {}
        resumen = (slots.get("ultimo_incidente_resumen") or "").strip()
        if "·" in resumen:
            subcat = resumen.split("·")[0].strip()
        else:
            subcat = resumen.strip()[:80]
    except Exception:
        subcat = ""
    sop = None
    try:
        if subcat:
            from .data.procedimientos import get_procedimiento as _get_sop
            sop = _get_sop(subcat)
    except Exception:
        sop = None
    if isinstance(sop, dict) and sop.get("pasos"):
        try:
            pasos = sop.get("pasos") or []
            txt = "; ".join(
                f"{p.get('n')}. {p.get('accion')} ({p.get('responsable') or 'Seguridad Ciudadana'})"
                for p in pasos[:5] if isinstance(p, dict))
            fuente = str(sop.get("fuente") or "")
            sub = str(sop.get("subcategoria") or subcat)
            borrador = "borrador" in fuente.lower() or "pendiente" in fuente.lower()
            aviso = (" Di explícitamente 'procedimiento borrador por validar, "
                     "no oficial'." if borrador else "")
            return (
                f"[contexto interno: piden PROCEDIMIENTO para '{sub}'. "
                f"SOP encontrado (fuente: {fuente}): {txt}."
                f" Cita los pasos tal cual en español simple (máx. 120 palabras), "
                f"con responsable.{aviso} PROHIBIDO inventar pasos fuera del SOP.]"
            )
        except Exception:
            pass
    label = f" para '{subcat}'" if subcat else ""
    return (
        f"[contexto interno: piden procedimiento{label} pero NO hay SOP en base. "
        f"Responde con la ficha del incidente (ticket, subcategoría, estado, "
        f"fecha Lima desde incident_detail o incidents_list limit=1) + derivación "
        f"al procedimiento oficial de Seguridad Ciudadana/Serenazgo. PROHIBIDO "
        f"inventar pasos, protocolos, plazos o responsables.]"
    )


def _extract_entity_for_slots(last_tool_result: dict | None) -> dict:
    """Ticket/fecha/resumen del último incidente para slots. Nunca raisea."""
    out: dict = {"ultimo_ticket": None, "ultimo_incidente_resumen": None,
                 "ultima_fecha": None}
    try:
        if not isinstance(last_tool_result, dict):
            return out
        res = last_tool_result.get("result") or {}
        data = res.get("data") or {}
        doc = None
        if isinstance(data.get("incidente"), dict):
            doc = data["incidente"]
        elif isinstance(data.get("incidentes"), list) and data["incidentes"]:
            doc = data["incidentes"][0]
        if not isinstance(doc, dict):
            return out
        ticket = doc.get("incident_ticket_number")
        if isinstance(ticket, str) and ticket.strip():
            out["ultimo_ticket"] = ticket.strip()
        fecha = (doc.get("incident_creation_date_lima")
                 or doc.get("incident_creation_date")
                 or doc.get("creation_date") or doc.get("fecha"))
        if fecha is not None:
            out["ultima_fecha"] = str(fecha)[:32]
        sub = (doc.get("subcategory_name") or doc.get("category_name") or "").strip()
        dist = (doc.get("incident_district") or "").strip()
        est = (doc.get("incident_state") or "").strip()
        parts = [p for p in (sub, dist, est) if p]
        if parts:
            out["ultimo_incidente_resumen"] = " · ".join(parts)[:200]
    except Exception:
        pass
    return out


def _extract_total_for_slots(last_tool_result: dict | None) -> int | None:
    """Total de documentos desde el último resultado (para slots). Nunca raisea."""
    try:
        if not isinstance(last_tool_result, dict):
            return None
        res = last_tool_result.get("result") or {}
        data = res.get("data") or {}
        meta = res.get("meta") or {}
        for key in ("total", "documentos", "n", "mostrados"):
            v = data.get(key)
            if isinstance(v, int) and v >= 0:
                return v
        v = meta.get("documentos")
        if isinstance(v, int) and v >= 0:
            return v
    except Exception:
        pass
    return None


@app.post("/ask")
def ask(req: AskRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Pregunta vacía.")
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Falta LLM_API_KEY. Crea backend/.env desde .env.example con tu API key de OpenCode Go (opencode.ai Zen → Go).",
        )
    try:
        cid = req.conversation_id or store.new_conversation(question)
    except Exception:
        # Si cae data_mind, seguimos con id efímero y sin persistir (append en try).
        cid = req.conversation_id or f"ephemeral-{uuid4()}"
    try:
        history = _history_for_llm(req.conversation_id)
    except Exception:
        history = []

    def event_stream():
        full_text = ""
        t0 = time.monotonic()
        deadline_s = float(getattr(settings, "ASK_DEADLINE_S", 90.0) or 90.0)

        def _check_deadline(stage: str) -> None:
            if time.monotonic() - t0 > deadline_s:
                raise TimeoutError(
                    f"Tiempo límite de /ask excedido en {stage} "
                    f"({deadline_s:.0f}s). Intenta con una pregunta más acotada.")

        def _progress(msg: str) -> str:
            # Evento ignorado por fronts viejos (api.ts solo maneja
            # meta/delta/done/error); no rompe el contrato.
            return f"event: progress\ndata: {json.dumps({'msg': msg}, default=str)}\n\n"

        try:
            # (a) Seam: router determinista/Jev ANTES del LLM.
            router_res = route(question, history)
            ruta = router_res.get("ruta", "ambigua")
            conf = router_res.get("confidence", 0.4)
            origen = router_res.get("origen", "determinista")
            try:
                from .decide.router import ROUTER_VERSION as _rv_log
            except Exception:
                _rv_log = "?"
            print(f"[ask] router={_rv_log} ruta={ruta} conf={conf:.2f} "
                  f"origen={origen} q={question[:80]!r}")
            tz_name = _resolve_tz(req.client_tz)
            today_str = _today_in_tz(tz_name)
            try:
                from .data.tools import set_display_tz as _set_dtz
                _set_dtz(tz_name)
            except Exception:
                pass

            if ruta == "saludo":
                # Fast-path: respuesta local humana, 0 LLM / 0 DB incidentes.
                meta = _fast_meta(cid, origen, ruta, conf)
                yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
                full_text = _fast_saludo_text(question)
                yield f"event: delta\ndata: {json.dumps({'text': full_text})}\n\n"
                try:
                    store.append_messages(cid, [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": full_text,
                         "sources": [], "chart": None, "jev": meta["jev"]},
                    ])
                except Exception:
                    pass
                yield "event: done\ndata: {}\n\n"
                return

            if ruta == "seguimiento":
                # Fast-path: 0 tools / 0 LLM, 1 lectura (slots). Sin consultar DB.
                try:
                    slots = store.get_slots(cid)
                except Exception:
                    slots = {"ultima_pregunta": None, "ultimo_resumen": None,
                             "ultimo_filtro": {}, "ultimo_total": None}
                meta = _fast_meta(cid, origen, ruta, conf)
                yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
                full_text = _fast_seguimiento_text(question, slots)
                yield f"event: delta\ndata: {json.dumps({'text': full_text})}\n\n"
                try:
                    store.append_messages(cid, [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": full_text,
                         "sources": [], "chart": None, "jev": meta["jev"]},
                    ])
                except Exception:
                    pass
                yield "event: done\ndata: {}\n\n"
                return

            if ruta == "seguimiento_entidad":
                # Slots (+1 DB solo para estado); si no hay dato, cae al slow.
                # Procedimiento/como devuelve None a propósito (fallthrough a SOP).
                try:
                    slots = store.get_slots(cid)
                except Exception:
                    slots = {"ultimo_ticket": None,
                             "ultimo_incidente_resumen": None,
                             "ultima_fecha": None, "ultima_pregunta": None}
                fast = _fast_seguimiento_entidad_text(question, slots)
                if fast is not None:
                    meta = _fast_meta(cid, origen, ruta, conf)
                    yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
                    full_text = fast
                    yield f"event: delta\ndata: {json.dumps({'text': full_text})}\n\n"
                    try:
                        store.append_messages(cid, [
                            {"role": "user", "content": question},
                            {"role": "assistant", "content": full_text,
                             "sources": [], "chart": None, "jev": meta["jev"]},
                        ])
                    except Exception:
                        pass
                    try:
                        store.save_slots(cid, ultima_pregunta=question)
                    except Exception:
                        pass
                    yield "event: done\ndata: {}\n\n"
                    return
                # Sin entidad o pedido de procedimiento: sigue al slow path.

            if ruta == "ambigua":
                # REGLA DURA: instantaneo, 0 DB / 0 tools / 0 LLM loop.
                # Va junto a saludo/seguimiento, ANTES de abrir DB: nunca slow path.
                # Aclaración personalizada con memoria: si veníamos de tiempos o
                # de un ticket, se ofrece eso primero en vez del genérico.
                try:
                    _slots_amb = store.get_slots(cid)
                except Exception:
                    _slots_amb = {}
                _up = ((_slots_amb.get("ultima_pregunta") or "")
                       + " " + (_slots_amb.get("ultimo_resumen") or "")).lower()
                _tick = (_slots_amb.get("ultimo_ticket") or "").strip()
                if any(k in _up for k in ("tiempo", "promedio", "resolu", "demor",
                                          "tard", "mediana", "cuanto lleva")):
                    full_text = ("¿Te refieres al promedio de tiempos de resolución? "
                                 "Dime si lo quieres general o por grupo y lo reviso.")
                elif _tick:
                    full_text = (f"¿Hablamos del reporte {_tick} o de otro tema? "
                                 f"Puedo darte conteos, tiempos, detalles o tendencias.")
                else:
                    full_text = ("¿De qué quieres hablar? ¿Me hablas de conteos, "
                                 "tiempos, un ticket o tendencias? Dime y lo reviso.")
                meta = _fast_meta(cid, origen, ruta, conf)
                yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
                yield f"event: delta\ndata: {json.dumps({'text': full_text})}\n\n"
                try:
                    store.append_messages(cid, [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": full_text,
                         "sources": [], "chart": None, "jev": meta["jev"]},
                    ])
                except Exception:
                    pass
                yield "event: done\ndata: {}\n\n"
                return

            if ruta == "fuera_de_alcance":
                meta = {"conversation_id": cid, "sources": [], "chart": None,
                        "jev": _build_jev_block(
                            origen, ruta, conf,
                            {"ok": True, "fallos": [], "origen": origen})}
                yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
                full_text = ("Lo siento, eso está fuera de mi alcance. "
                             "Puedo ayudarte con conteos, rankings de tiempos, "
                             "detalles de tickets y tendencias de incidentes. "
                             "¿Empezamos por cuántos incidentes hay por estado?")
                yield f"event: delta\ndata: {json.dumps({'text': full_text})}\n\n"
                try:
                    store.append_messages(cid, [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": full_text,
                         "sources": [], "chart": None, "jev": meta["jev"]},
                    ])
                except Exception:
                    pass
                yield "event: done\ndata: {}\n\n"
                return

            # --- Slow path: streaming real (sin buffer total) ---
            # Anti-desync: si el cliente aborta (GeneratorExit/ClientDisconnect),
            # NO persistir parcial (ni append ni save_slots) y re-lanzar limpio.
            # Solo persiste si el stream terminó normal (slow_completed=True).
            # Fast-paths (saludo/seguimiento/ambigua/seguimiento_entidad/
            # fuera_de_alcance) son atómicos y sí persisten.
            slow_completed = False
            # 1) Meta provisional INMEDIATA: TTFB <100ms sin DB ni LLM.
            #    El front hace last-wins en onMeta, así que la 2ª meta final
            #    sobrescribe sources/chart sin romper nada.
            prov_jev = _build_jev_block(
                origen, ruta, conf, {"ok": True, "fallos": [], "origen": origen})
            meta_prov = {"conversation_id": cid, "sources": [], "chart": None,
                         "jev": prov_jev, "provisional": True}
            yield f"event: meta\ndata: {json.dumps(meta_prov, default=str)}\n\n"
            yield _progress(f"Entendí: ruta={ruta} (confianza {conf:.2f}). Consultando datos…")
            _check_deadline("router")

            db = get_db()
            # Contexto determinista: zona + plan. Guía al LLM al tool correcto
            # en el 1er turno (1 tool en vez de 2-3) y fija "hoy" en Lima.
            plan_note = None
            if ruta == "ultimo":
                plan_note = ("[contexto interno: el usuario pide el ÚLTIMO incidente. "
                             "Llama UNA vez a incidents_list con limit=1 (orden ya es "
                             "desc por fecha). No llames timeseries ni distinct.]")
            elif ruta == "hoy":
                plan_note = (f"[contexto interno: zona {tz_name}, hoy es {today_str}. "
                             f"Para 'hoy' usa from_date={today_str} to_date={today_str} "
                             f"en incidents_list (limit 10). No afirmes nada de hoy "
                             f"sin ese filtro.]")
            elif ruta == "seguimiento_entidad":
                # Si en realidad pide procedimiento ("cómo resolver..."), usa plan SOP.
                try:
                    _nq = _norm_fast(question)
                except Exception:
                    _nq = ""
                if _looks_procedimiento_fast(_nq):
                    plan_note = _build_procedimiento_plan(cid)
                else:
                    plan_note = ("[contexto interno: seguimiento del incidente ya mencionado. "
                                 "Si hay ticket en el historial úsalo con incident_detail; "
                                 "si no, incidents_list limit=1. Máximo 1 tool.]")
            elif ruta == "tiempo_transcurrido":
                plan_note = _build_tiempo_plan(cid)
            elif ruta == "procedimiento":
                plan_note = _build_procedimiento_plan(cid)
            ev_history = (history + [{"role": "user", "content": plan_note}]
                          if plan_note else history)
            evidence = gather_evidence(question, ev_history, db, session_id=cid)
            _check_deadline("tools")
            n_docs = sum((s.get("documentos") or 0)
                         if isinstance(s.get("documentos"), int) else 0
                         for s in evidence.get("sources", []))
            n_tools = len(evidence.get("sources", []))
            yield _progress(f"Consulté {n_tools} fuente(s), {n_docs} docs. Armado respuesta…")

            chart = build_chart(evidence["last_tool_result"])
            # 2) Meta final con fuentes reales (sobrescribe la provisional).
            meta_final = {"conversation_id": cid, "sources": evidence["sources"],
                          "chart": chart, "jev": prov_jev,
                          "display_tz": tz_name, "today": today_str}
            yield f"event: meta\ndata: {json.dumps(meta_final, default=str)}\n\n"
            if chart:
                yield _progress("Graficando resultados…")
            else:
                yield _progress("Redactando respuesta…")

            # 3) Deltas REALES: se emiten a medida que llegan (sin list()).
            for delta in stream_answer(evidence["messages"], session_id=cid):
                _check_deadline("stream")
                if not delta:
                    continue
                full_text += delta
                yield f"event: delta\ndata: {json.dumps({'text': delta})}\n\n"

            # 4) Veredicto POST-streaming (no bloquea TTFB): evento aparte +
            #    payload en done. Fronts viejos ignoran ambos sin romperse.
            full_text = clean_answer(full_text)
            veredicto = verify_routed(full_text, evidence["sources"], chart, ruta,
                                       today_hint=today_str if ruta == "hoy" else None)
            jev_block = _build_jev_block(origen, ruta, conf, veredicto)
            if not jev_block["veredicto_ok"]:
                # Sin prefijo visible: el veredicto vive solo en jev para el
                # chip discreto del front. Log a consola para trazabilidad.
                print(f"[verify] provisional ruta={ruta} "
                      f"fallos={','.join(jev_block['fallos'])}")
            yield f"event: verdict\ndata: {json.dumps({'jev': jev_block}, default=str)}\n\n"
            # Anti-desync: el stream llegó al final sin abortar -> marcar completo.
            # Solo entonces se permite persistir (append + save_slots).
            slow_completed = True
            if slow_completed:
                try:
                    store.append_messages(cid, [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": full_text,
                         "sources": evidence["sources"], "chart": chart, "jev": jev_block},
                    ])
                except Exception:
                    pass
            if slow_completed:
                try:
                    # Memoria conversacional (misma colección, sin tocar verify/jev_block).
                    ent = _extract_entity_for_slots(evidence.get("last_tool_result"))
                    store.save_slots(
                        cid,
                        ultima_pregunta=question,
                        ultimo_resumen=full_text,
                        ultimo_filtro=router_res.get("filtros") or {},
                        ultimo_total=_extract_total_for_slots(evidence.get("last_tool_result")),
                        ultimo_ticket=ent.get("ultimo_ticket"),
                        ultimo_incidente_resumen=ent.get("ultimo_incidente_resumen"),
                        ultima_fecha=ent.get("ultima_fecha"),
                        display_tz=tz_name,
                    )
                except Exception:
                    pass
            done_payload = {"conversation_id": cid, "sources": evidence["sources"],
                            "chart": chart, "jev": jev_block,
                            "display_tz": tz_name}
            yield f"event: done\ndata: {json.dumps(done_payload, default=str)}\n\n"
        except GeneratorExit:
            # Cliente abortó el stream: NO persistir parcial, cierre limpio.
            raise
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/conversations")
def conversations():
    return {"conversations": store.list_conversations()}


@app.get("/conversations/{cid}")
def conversation(cid: str):
    convo = store.get_conversation(cid)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    return convo
