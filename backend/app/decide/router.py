"""Router determinista F1: pregunta ES -> {ruta, confidence, filtros, origen}.

Rutas: conteo | ranking_tiempo | detalle_ticket | tendencia | ambigua | fuera_de_alcance
       | saludo | seguimiento | ultimo | seguimiento_entidad | hoy
       | tiempo_transcurrido | procedimiento
Heurística por keywords (normalizada sin acentos). Sin LLM, sin red.
Orden: saludo > seguimiento > hoy > ultimo > tiempo_transcurrido
       > procedimiento > seguimiento_entidad > resto.
"""

import re
import unicodedata

# Versión del router: se expone en GET /health para detectar backends
# corriendo código viejo. BUMPEARLA con cada cambio de intents/keywords.
ROUTER_VERSION = "2026-09-25.6"

RUTAS = ("conteo", "ranking_tiempo", "detalle_ticket", "tendencia", "ambigua",
         "fuera_de_alcance", "saludo", "seguimiento",
         "ultimo", "seguimiento_entidad", "hoy",
         "tiempo_transcurrido", "procedimiento")

CONF_CLARO = 0.85
CONF_AMBIGUA = 0.4
CONF_SALUDO = 0.95
CONF_SEGUIMIENTO = 0.9
CONF_ULTIMO = 0.9
CONF_SEGUIMIENTO_ENTIDAD = 0.9
CONF_HOY = 0.9
CONF_TIEMPO_TRANSCURRIDO = 0.9
CONF_PROCEDIMIENTO = 0.9


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# -- fast-paths conversacionales (ya normalizados, sin acentos) -------------------
# Se evalúan ANTES que cualquier keyword de dominio (ver decide paso 0).
_SALUDO_PHRASES = (
    "buenos dias", "buenas tardes", "buenas noches", "buen dia",
    "que puedes hacer", "que sabes hacer",
    "quien eres", "que haces",
    "que es datamind", "que es data mind",
    "como estas", "todo bien", "que tal",
    "que cuentas", "todo tranquilo",
    "muchas gracias",
)

# Palabras sueltas con \b para no matchear subcadenas ("hey" dentro de otra voz, etc.).
_SALUDO_WORD_RE = re.compile(
    r"\b(hola|buenas|hey|gracias|adios|chau|ayuda)\b"
)

_SEGUIMIENTO = (
    "que te pregunte", "que me preguntaste", "que dije",
    "resumelo", "resumen",
    "y de esos", "y de ellos",
    "explicame mas", "por que", "detalla",
)

# -- nuevas rutas anti-alucinación (antes de ambigua/dominio) ------------------
_ULTIMO = (
    "ultimo", "ultima",
    "mas reciente", "mas nuevo",
    "reciente incidente", "ultimo reporte", "ultimo incidente",
)

_HOY = (
    "hoy", "el dia de hoy", "esta manana", "esta tarde", "esta noche",
    "tengo incidentes", "incidentes hoy", "reportes hoy",
)

# Seguimiento sobre la entidad ya mencionada (usa slots, 0-1 DB).
_SEGUIMIENTO_ENTIDAD = (
    "y el numero", "y su numero", "el numero de",
    "numero de incidente", "numero de reporte", "numero del reporte",
    "a que hora", "a que hora fue", "hora del reporte", "hora fue",
    "ya se resolvio", "ya esta resuelto", "ya lo resolvieron",
    "sigue en proceso", "cual es su estado", "su estado",
    "ese reporte", "ese incidente", "ese caso",
    "del reporte", "del incidente",
)

# Tiempo transcurrido sobre la entidad (cuánto lleva / lapso en Lima).
_TIEMPO_FRASES = (
    "cuanto lleva", "cuanto tiempo lleva",
    "tiempo transcurrido", "tiempo pasado",
    "cuanto ha pasado", "cuanto paso",
)

# Procedimiento / cómo resolver (deriva a SOP, nunca a seguimiento_entidad).
_PROCEDIMIENTO = (
    "como resolver", "como resuelvo", "como lo resuelvo",
    "como puedo resolver", "como atender", "como atiendo",
    "como proceder", "como procedo", "como se resuelve",
    "como se atiende", "como lo puedo resolver",
    "que debo hacer", "que tengo que hacer", "que hago para",
    "pasos", "protocolo", "procedimiento",
)


def _is_hoy(n: str) -> bool:
    if not n or not n.strip():
        return False
    return any(k in n for k in _HOY)


def _is_ultimo(n: str) -> bool:
    if not n or not n.strip():
        return False
    return any(k in n for k in _ULTIMO)


def _is_seguimiento_entidad(n: str) -> bool:
    if not n or not n.strip():
        return False
    return any(k in n for k in _SEGUIMIENTO_ENTIDAD)


def _is_tiempo_transcurrido(n: str) -> bool:
    """Cuánto lleva / lapso transcurrido (redondeo a minuto, nunca segundos exactos).

    Dispara si hay frase directa ("cuanto lleva", "tiempo transcurrido", ...)
    o si hay unidad temporal (dia/hora/minuto/segundo) + contexto
    (lleva/transcurrido/pasado/lapso/exacto). "cuanto tardan" (ranking) no
    entra porque no trae lleva/transcurr/pasado/lapso/exacto.
    """
    if not n or not n.strip():
        return False
    if any(k in n for k in _TIEMPO_FRASES):
        return True
    if "cuanto" in n and ("lleva" in n or "transcurr" in n
                          or "pasad" in n or "lapso" in n):
        return True
    if "transcurr" in n or "lapso" in n:
        return True
    has_unidad = bool(re.search(
        r"\b(dia(s)?|hora(s)?|minuto(s)?|segundo(s)?)\b", n))
    has_ctx = ("lleva" in n or "transcurr" in n or "pasad" in n
               or "lapso" in n or "exacto" in n)
    if has_unidad and has_ctx:
        return True
    return False


def _is_procedimiento(n: str) -> bool:
    """Cómo resolver/atender/proceder, pasos, protocolo, qué debo hacer.

    No matchea pasado ("ya se resolvio", "resuelto", "estado") para no robar
    la ruta seguimiento_entidad-estado. Solo infinitivo/presente + frases
    de acción.
    """
    if not n or not n.strip():
        return False
    if any(k in n for k in _PROCEDIMIENTO):
        return True
    if "como" in n and ("resolver" in n or "resuelvo" in n
                        or "atender" in n or "atiendo" in n
                        or "proceder" in n or "procedo" in n):
        return True
    return False


def _is_saludo(n: str) -> bool:
    if not n or not n.strip():
        return False
    if _SALUDO_WORD_RE.search(n):
        return True
    return any(p in n for p in _SALUDO_PHRASES)


def _is_seguimiento(n: str) -> bool:
    if not n or not n.strip():
        return False
    return any(k in n for k in _SEGUIMIENTO)


# -- keywords (ya normalizados, sin acentos) ---------------------------------
_FUERA = (
    "clima", "weather", "lluvia", "temperatura",
    "borrar", "borra", "elimina", "eliminar", "delete", "drop",
    "dni", "sql", "select ", "insert ", "update ",
)

_AMBIGUA_TRIGGERS = (
    "grave", "graves", "gravedad",
    "seguridad",
    "recientemente", "reciente",
    "ayer",
)

_CONTEO = (
    "cuantos", "cuantas", "cantidad", "total",
    "por estado", "por categoria", "por district", "por distrito",
    "distrito", "prioridad", "categoria", "cuenta",
)

_RANKING = (
    "top", "mas frecuentes", "mas frecuente", "frecuentes",
    "promedio", "mediana", "media",
    "promedio de respuesta", "tiempo de respuesta", "media de respuesta",
    "demor", "tard", "lent", "rapid",
    "tardan", "tarda", "rapido", "rapidos", "lento", "lentos",
    "resolucion", "demora", "demoran",
)

_DETALLE = (
    "ticket", "detalle", "busca", "buscar", "lista", "listar",
    "listame", "muestra", "muestrame", "dame",
)

_TENDENCIA = (
    "evoluci", "tendencia", "mes", "meses", "mensual",
    "semana", "semanal", "dia", "dias", "diario",
)


def _extract_filtros(n: str) -> dict:
    """Extracción ligera de filtros para trazabilidad (no valida contra DB)."""
    filtros: dict = {}
    if "recibido" in n:
        filtros["estado"] = "Recibido"
    elif "en progreso" in n or "enprogreso" in n.replace(" ", ""):
        filtros["estado"] = "En progreso"
    elif "resuelto" in n or "resueltos" in n:
        filtros["estado"] = "Resuelto"
    if "alta" in n and "prioridad" in n:
        filtros["prioridad"] = "Alta"
    elif "media" in n and "prioridad" in n:
        filtros["prioridad"] = "Media"
    elif "baja" in n and "prioridad" in n:
        filtros["prioridad"] = "Baja"
    if "emergencia" in n:
        filtros["categoria"] = "Emergencia"
    elif "alerta" in n:
        filtros["categoria"] = "Alerta"
    m = re.search(r"\btop\s*(\d{1,3})\b", n)
    if m:
        filtros["top_n"] = int(m.group(1))
    return filtros


def decide(question: str, history: list[dict] | None = None) -> dict:
    """Clasificación determinista pura. Nunca hace red ni raise."""
    n = _norm(question)
    filtros = _extract_filtros(n)

    # 0. Fast-paths conversacionales (antes de cualquier keyword de dominio).
    if _is_saludo(n):
        return {"ruta": "saludo", "confidence": CONF_SALUDO,
                "filtros": filtros, "origen": "determinista"}
    if _is_seguimiento(n):
        return {"ruta": "seguimiento", "confidence": CONF_SEGUIMIENTO,
                "filtros": filtros, "origen": "determinista"}
    # 0b. Rutas anti-alucinación: plan determinista, alta confianza.
    if _is_hoy(n):
        return {"ruta": "hoy", "confidence": CONF_HOY,
                "filtros": filtros, "origen": "determinista",
                "tool_plan": {"tool": "incidents_list", "limit": 10,
                              "from": "today"}}
    if _is_ultimo(n):
        return {"ruta": "ultimo", "confidence": CONF_ULTIMO,
                "filtros": filtros, "origen": "determinista",
                "tool_plan": {"tool": "incidents_list", "limit": 1}}
    if _is_tiempo_transcurrido(n):
        return {"ruta": "tiempo_transcurrido", "confidence": CONF_TIEMPO_TRANSCURRIDO,
                "filtros": filtros, "origen": "determinista",
                "tool_plan": {"tool": "slot_reuse", "need": "incident_detail"}}
    if _is_procedimiento(n):
        return {"ruta": "procedimiento", "confidence": CONF_PROCEDIMIENTO,
                "filtros": filtros, "origen": "determinista",
                "tool_plan": {"tool": "slot_reuse", "need": "sop"}}
    if _is_seguimiento_entidad(n):
        return {"ruta": "seguimiento_entidad", "confidence": CONF_SEGUIMIENTO_ENTIDAD,
                "filtros": filtros, "origen": "determinista",
                "tool_plan": {"tool": "slot_reuse"}}

    # 1. Fuera de alcance (seguridad primero).
    if any(k in n for k in _FUERA):
        return {"ruta": "fuera_de_alcance", "confidence": CONF_CLARO,
                "filtros": filtros, "origen": "determinista"}

    # 2. Ambigua por triggers explícitos (aunque matchee otra ruta).
    if any(k in n for k in _AMBIGUA_TRIGGERS):
        return {"ruta": "ambigua", "confidence": CONF_AMBIGUA,
                "filtros": filtros, "origen": "determinista"}

    # 3. Rutas específicas (orden: tendencia > ranking > detalle > conteo).
    # Tendencia antes que conteo porque "por mes" contiene "por..." pero es temporal.
    # Guarda anti-tiempo: "dias"+"horas/minutos" con lleva/exactos NO es tendencia.
    if any(k in n for k in _TENDENCIA):
        if any(k in n for k in ("horas", "minutos", "segundos", "exactos", "lleva")):
            pass  # no es tendencia: cae a ranking/detalle/conteo o ambigua
        # "mes" es subcadena común (ej. "mismo"); exige palabra o contexto temporal.
        elif (re.search(r"\bmes(es)?\b", n) or re.search(r"\bsemana(s)?\b", n)
                or re.search(r"\bdia(s)?\b", n) or "evoluci" in n
                or "tendencia" in n or "mensual" in n or "semanal" in n or "diario" in n):
            return {"ruta": "tendencia", "confidence": CONF_CLARO,
                    "filtros": filtros, "origen": "determinista"}
    if any(k in n for k in _RANKING):
        return {"ruta": "ranking_tiempo", "confidence": CONF_CLARO,
                "filtros": filtros, "origen": "determinista"}
    if any(k in n for k in _DETALLE):
        return {"ruta": "detalle_ticket", "confidence": CONF_CLARO,
                "filtros": filtros, "origen": "determinista"}
    if any(k in n for k in _CONTEO):
        return {"ruta": "conteo", "confidence": CONF_CLARO,
                "filtros": filtros, "origen": "determinista"}

    # 4. Sin match -> ambigua.
    return {"ruta": "ambigua", "confidence": CONF_AMBIGUA,
            "filtros": filtros, "origen": "determinista"}


def route(question: str, history: list[dict] | None = None) -> dict:
    """Dispatcher F1/F2a: usa Jev si está habilitado+configurado, si no determinista.

    Cortesía y seguimiento conversacional NUNCA van a Jev: son locales,
    instantáneos y gratis (un "hola" no debe pagar 1 llamada al modelo).
    Nunca raisea: cualquier fallo de Jev cae a determinista-fallback.
    """
    try:
        n = _norm(question)
        if _is_saludo(n):
            return {"ruta": "saludo", "confidence": CONF_SALUDO,
                    "filtros": _extract_filtros(n), "origen": "determinista"}
        if _is_seguimiento(n):
            return {"ruta": "seguimiento", "confidence": CONF_SEGUIMIENTO,
                    "filtros": _extract_filtros(n), "origen": "determinista"}
    except Exception:
        pass
    try:
        from ..config import settings
    except Exception:
        return decide(question, history)
    try:
        if settings.JEV_ENABLED and settings.JEV_API_KEY:
            try:
                from . import jev_adapter
                return jev_adapter.decide_jev(question, {"history": history or []})
            except Exception:
                fell = decide(question, history)
                fell["origen"] = "determinista-fallback"
                return fell
    except Exception:
        pass
    return decide(question, history)
