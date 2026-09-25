"""Tools de SOLO LECTURA sobre gueo2021.incidents (+ users, vehicles, shifts, workgroups).

Cada tool devuelve {"data": ..., "meta": {...}} donde meta describe la fuente
(colección, filtros aplicados, nº documentos) para que el agente cite cifras.
"""

from datetime import datetime, timezone
from statistics import mean, median
from time import monotonic
from typing import Any

from pymongo.database import Database

from ..config import settings

INCIDENTS = "incidents"

# Cache en memoria 5min para distinct_values (dict + ttl).
# Clave: mongo_field -> (expire_monotonic, payload). Sin lock: GIL + tolerante.
_DISTINCT_CACHE: dict[str, tuple[float, dict]] = {}


def _distinct_cache_get(mongo_field: str) -> dict | None:
    entry = _DISTINCT_CACHE.get(mongo_field)
    if not entry:
        return None
    expire, payload = entry
    if monotonic() >= expire:
        _DISTINCT_CACHE.pop(mongo_field, None)
        return None
    return payload


def _distinct_cache_set(mongo_field: str, payload: dict) -> None:
    ttl = max(int(getattr(settings, "DISTINCT_CACHE_TTL_S", 300) or 300), 30)
    _DISTINCT_CACHE[mongo_field] = (monotonic() + ttl, payload)

# Campos permitidos para agrupar / distinct (whitelist = anti-inyección)
GROUPABLE_FIELDS = {
    "estado": "incident_state",
    "categoria": "category_name",
    "subcategoria": "subcategory_name",
    "prioridad": "incident_priority",
    "grupo": "workgroup_name",
    "grupo_operador": "operator_workgroup_name",
    "distrito": "incident_district",
    "turno": "shift_name",
    "origen": "origin",
    "canal": "incident_registered_from",
}

# Campos con datos personales: se enmascaran antes de salir del backend
SENSITIVE_FIELDS = {
    "taxpayer_dni",
    "taxpayer_cellphone",
    "operator_dni",
    "operator_contact_number",
    "workgroup_contact_number",
    "workgroup_responsable_dni",
    "incident_registered_for_dni",
}


def mask(value: Any) -> Any:
    if value is None or value == "":
        return value
    s = str(value)
    if len(s) <= 3:
        return "***"
    return "*" * (len(s) - 3) + s[-3:]


def mask_doc(doc: dict) -> dict:
    return {k: (mask(v) if k in SENSITIVE_FIELDS else v) for k, v in doc.items()}


DEFAULT_TZ = "America/Lima"

# Zona display por request (la fija main.py desde client_tz). ContextVar =
# seguro en async/threads; default Lima cuando nadie la fija (tests, scripts).
from contextvars import ContextVar as _ContextVar

_DISPLAY_TZ: _ContextVar[str] = _ContextVar("datamind_display_tz", default=DEFAULT_TZ)


def set_display_tz(tz_name: str | None) -> str:
    """Fija la zona display del request actual. Retorna la efectiva (Lima si inválida)."""
    cand = (tz_name or "").strip() or DEFAULT_TZ
    try:
        _tzinfo(cand)
    except Exception:
        cand = DEFAULT_TZ
    _DISPLAY_TZ.set(cand)
    return cand


def get_display_tz() -> str:
    try:
        return _DISPLAY_TZ.get() or DEFAULT_TZ
    except Exception:
        return DEFAULT_TZ


_MESES_ES = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")

# Campos datetime de Mongo que se convierten a hora Lima para el vecino.
_FECHA_FIELDS = ("incident_creation_date", "incident_in_progress_date",
                 "incident_resolved_date")


def to_display(dt: Any, tz_name: str | None = None) -> str | None:
    """datetime (UTC o naive=UTC) -> '16 de septiembre de 2026, 10:54 pm' en tz.

    Formato 12h como el sistema origen Gueo/Delta. Nunca raisea (None si no hay dato).
    """
    if dt is None:
        return None
    try:
        from datetime import datetime as _dt
        tz = _tzinfo(tz_name or get_display_tz())
        if isinstance(dt, _dt):
            d = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        else:
            d = _dt.fromisoformat(str(dt).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        loc = d.astimezone(tz)
        h24, mi = loc.hour, loc.minute
        suffix = "am" if h24 < 12 else "pm"
        h12 = h24 % 12 or 12
        return (f"{loc.day} de {_MESES_ES[loc.month]} de {loc.year}, "
                f"{h12}:{mi:02d} {suffix}")
    except Exception:
        return None


def convert_doc_dates(doc: dict, tz_name: str | None = None) -> dict:
    """Reemplaza datetimes UTC por display Lima (saca el crudo del alcance del LLM).

    - incident_creation_date (y _in_progress/_resolved) -> '16 de septiembre de 2026, 10:54 pm'
    - El ISO crudo se elimina del payload: el LLM solo ve hora Lima.
    """
    tz = tz_name or get_display_tz()
    for f in _FECHA_FIELDS:
        if f in doc:
            disp = to_display(doc.get(f), tz)
            doc.pop(f, None)
            if disp:
                doc[f + "_lima"] = disp
    return doc


def _tzinfo(tz_name: str | None):
    """ZoneInfo con fallback UTC-5 (Lima no tiene horario de verano).

    En Windows sin paquete tzdata, ZoneInfo falla: se usa offset fijo -5,
    correcto para America/Lima todo el año.
    """
    from datetime import timedelta
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    cand = (tz_name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(cand)
    except Exception:
        try:
            return ZoneInfo(DEFAULT_TZ)
        except Exception:
            return timezone(timedelta(hours=-5))


def parse_date(value: str | None, tz_name: str | None = None) -> datetime | None:
    if not value:
        return None
    # Acepta YYYY-MM-DD o ISO completo.
    # Fecha sola (YYYY-MM-DD) = medianoche en la zona del cliente (Lima por
    # defecto), convertida a UTC para el $match. Antes era medianoche UTC,
    # lo que movía los bordes de día 5h.
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Fecha inválida: {value!r}. Usa YYYY-MM-DD.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tzinfo(tz_name)).astimezone(timezone.utc)
    return dt


def clamp_limit(limit: int | None) -> int:
    if not limit or limit <= 0:
        return settings.DEFAULT_LIMIT
    return min(limit, settings.MAX_LIMIT)


def base_match(
    state: str | None = None,
    category: str | None = None,
    workgroup: str | None = None,
    district: str | None = None,
    priority: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[dict, dict]:
    """Construye el $match y su descripción legible para meta/fuentes."""
    match: dict = {}
    desc: dict = {}
    if state:
        match["incident_state"] = state
        desc["estado"] = state
    if category:
        match["category_name"] = category
        desc["categoría"] = category
    if workgroup:
        match["workgroup_name"] = workgroup
        desc["grupo"] = workgroup
    if district:
        match["incident_district"] = district
        desc["distrito"] = district
    if priority:
        match["incident_priority"] = priority
        desc["prioridad"] = priority
    date_q: dict = {}
    fd, td = parse_date(from_date), parse_date(to_date)
    if fd:
        date_q["$gte"] = fd
        desc["desde"] = from_date
    if td:
        date_q["$lte"] = td
        desc["hasta"] = to_date
    if date_q:
        match["incident_creation_date"] = date_q
    return match, desc


def incidents_count(db: Database, group_by: str = "estado", **filters) -> dict:
    """Cuenta incidentes agrupados por un campo (conteos y filtros)."""
    field = GROUPABLE_FIELDS.get(group_by, GROUPABLE_FIELDS["estado"])
    match, desc = base_match(**filters)
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 100},
    ]
    rows = list(db[INCIDENTS].aggregate(
        pipeline, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS))
    buckets = [{"clave": r["_id"], "n": r["n"]} for r in rows]
    return {
        "data": {"total": sum(b["n"] for b in buckets), "grupos": buckets},
        "meta": {"coleccion": INCIDENTS, "agrupado_por": group_by, "filtros": desc,
                 "documentos": sum(b["n"] for b in buckets)},
    }


def incidents_list(
    db: Database, limit: int | None = None, offset: int = 0, search: str | None = None, **filters
) -> dict:
    """Lista incidentes (resumen) con filtros y paginación."""
    match, desc = base_match(**filters)
    if search:
        match["$or"] = [
            {"incident_ticket_number": {"$regex": search, "$options": "i"}},
            {"incident_description": {"$regex": search, "$options": "i"}},
            {"referential_location": {"$regex": search, "$options": "i"}},
        ]
        desc["búsqueda"] = search
    limit = clamp_limit(limit)
    cursor = (
        db[INCIDENTS]
        .find(match, {"incident_logs": 0, "tracking_messages": 0},
              max_time_ms=settings.QUERY_TIMEOUT_MS)
        .sort("incident_creation_date", -1)
        .skip(max(offset, 0))
        .limit(limit)
    )
    rows = []
    for d in cursor:
        d["id"] = str(d.pop("_id"))
        rows.append(convert_doc_dates(mask_doc(d)))
    return {
        "data": {"incidentes": rows, "mostrados": len(rows)},
        "meta": {"coleccion": INCIDENTS, "filtros": desc, "documentos": len(rows),
                 "zona": get_display_tz()},
    }


def incident_detail(db: Database, ticket_number: str) -> dict:
    """Detalle completo de un incidente por su ticket (datos sensibles enmascarados)."""
    doc = db[INCIDENTS].find_one({"incident_ticket_number": ticket_number})
    if doc is None:
        return {"data": {"encontrado": False}, "meta": {"coleccion": INCIDENTS, "ticket": ticket_number}}
    doc["id"] = str(doc.pop("_id"))
    return {
        "data": {"encontrado": True, "incidente": convert_doc_dates(mask_doc(doc))},
        "meta": {"coleccion": INCIDENTS, "ticket": ticket_number, "documentos": 1,
                 "zona": get_display_tz()},
    }


def _sospechosos_tiempo(db: Database, match: dict,
                        umbral_min: float = 60.0) -> tuple[set, list]:
    """Docs cuyo incident_resolved_time contradice a sus fechas.

    Regla: sospechoso si |resolved_time − diff_fechas| > max(umbral, 10% del diff),
    con diff = $dateDiff(creation → resolved) en minutos. Sin fechas no se juzga
    (se conserva). Retorna (tickets_sospechosos, advertencias[]).
    Nunca raisea: ante error de aggregate retorna (set(), []).
    """
    try:
        pipe = [
            {"$match": match},
            {"$project": {
                "ticket": "$incident_ticket_number",
                "rt": "$incident_resolved_time",
                "diff": {"$dateDiff": {
                    "startDate": "$incident_creation_date",
                    "endDate": "$incident_resolved_date",
                    "unit": "minute"}},
            }},
            {"$limit": 2000},
        ]
        tickets: set = set()
        advs: list = []
        for r in db[INCIDENTS].aggregate(
                pipe, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS):
            rt, diff = r.get("rt"), r.get("diff")
            if not isinstance(rt, (int, float)) or not isinstance(diff, (int, float)):
                continue
            if diff < 0:
                continue  # fechas invertidas: otro error, no es este chequeo
            tol = max(float(umbral_min), 0.1 * abs(diff))
            if abs(float(rt) - float(diff)) > tol:
                t = str(r.get("ticket") or "")
                if t:
                    tickets.add(t)
                advs.append({
                    "ticket": t,
                    "campo": "incident_resolved_time",
                    "valor_min": rt,
                    "fechas_dan_min": diff,
                    "diferencia_min": round(abs(float(rt) - float(diff)), 1),
                })
        advs.sort(key=lambda a: a["diferencia_min"], reverse=True)
        return tickets, advs
    except Exception:
        return set(), []


def resolution_times(db: Database, group_by: str | None = None, **filters) -> dict:
    """Tiempos de resolución (min) sobre incidentes Resueltos: promedio, mediana, min, max.

    Optimizado: 1 solo aggregate (antes: distinct+count+find = 3 lecturas).
    El promedio/min/max lo calcula Mongo ($avg/$min/$max); la mediana se deriva
    en Python del array $push (1 roundtrip, sin distinct que pierde duplicados).

    Calidad de datos: los docs cuyo incident_resolved_time contradice a sus
    fechas (ej. JB-I.000008: 161066 min vs ~3 min por fechas) se EXCLUYEN de
    las stats y se devuelven en data.advertencias para citarlos con cautela.
    """
    match, desc = base_match(**filters)
    match["incident_state"] = "Resuelto"
    match["incident_resolved_time"] = {"$ne": None, "$gt": 0}
    desc["estado"] = "Resuelto"
    # Chequeo previo liviano (1 aggregate proyectado). Sin sospechosos no cambia nada.
    susp_tickets, advertencias = _sospechosos_tiempo(db, match)
    if susp_tickets:
        match = {**match, "incident_ticket_number": {"$nin": sorted(susp_tickets)}}
        desc["nota_calidad"] = (f"{len(susp_tickets)} caso(s) excluido(s) por "
                                f"tiempo inconsistente con sus fechas")
    if group_by:
        field = GROUPABLE_FIELDS.get(group_by)
        if not field:
            raise ValueError(f"group_by inválido: {group_by!r}")
        pipeline: list = [
            {"$match": match},
            {"$group": {
                "_id": f"${field}",
                "n": {"$sum": 1},
                "promedio_min": {"$avg": "$incident_resolved_time"},
                "min_min": {"$min": "$incident_resolved_time"},
                "max_min": {"$max": "$incident_resolved_time"},
                "tiempos": {"$push": "$incident_resolved_time"},
            }},
            {"$sort": {"_id": 1}},
            {"$limit": 100},
        ]
        out = []
        for r in db[INCIDENTS].aggregate(
                pipeline, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS):
            t = sorted(v for v in (r.get("tiempos") or [])
                       if isinstance(v, (int, float)) and v > 0)
            if not t:
                continue
            out.append({
                "clave": r["_id"], "n": len(t),
                "promedio_min": round(float(r.get("promedio_min") if isinstance(
                    r.get("promedio_min"), (int, float)) else mean(t)), 1),
                "mediana_min": round(median(t), 1),
                "min_min": t[0], "max_min": t[-1],
            })
        return {"data": {"grupos": out, "excluidos": len(susp_tickets),
                         "advertencias": advertencias[:20]},
                "meta": {"coleccion": INCIDENTS, "agrupado_por": group_by, "filtros": desc,
                         "documentos": sum(g["n"] for g in out),
                         "advertencias": len(advertencias)}}
    # Sin group_by: 1 solo aggregate global.
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "n": {"$sum": 1},
            "promedio_min": {"$avg": "$incident_resolved_time"},
            "min_min": {"$min": "$incident_resolved_time"},
            "max_min": {"$max": "$incident_resolved_time"},
            "tiempos": {"$push": "$incident_resolved_time"},
        }},
    ]
    rows = list(db[INCIDENTS].aggregate(
        pipeline, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS))
    if not rows or not rows[0].get("n"):
        stats: dict = {"n": 0, "excluidos": len(susp_tickets),
                       "advertencias": advertencias[:20]}
        return {"data": stats,
                "meta": {"coleccion": INCIDENTS, "filtros": desc, "documentos": 0,
                         "advertencias": len(advertencias)}}
    r = rows[0]
    vals = sorted(v for v in (r.get("tiempos") or [])
                  if isinstance(v, (int, float)) and v > 0)
    if not vals:
        stats = {"n": 0, "excluidos": len(susp_tickets),
                 "advertencias": advertencias[:20]}
        return {"data": stats,
                "meta": {"coleccion": INCIDENTS, "filtros": desc, "documentos": 0,
                         "advertencias": len(advertencias)}}
    avg = r.get("promedio_min")
    if not isinstance(avg, (int, float)):
        avg = mean(vals)
    stats = {"n": len(vals), "promedio_min": round(float(avg), 1),
             "mediana_min": round(median(vals), 1),
             "min_min": vals[0], "max_min": vals[-1],
             "excluidos": len(susp_tickets), "advertencias": advertencias[:20]}
    return {"data": stats, "meta": {"coleccion": INCIDENTS, "filtros": desc, "documentos": stats["n"],
                                    "advertencias": len(advertencias)}}


def detectar_tiempos_inconsistentes(db: Database, umbral_min: float = 60.0,
                                     limite: int = 100) -> dict:
    """Auditoría de calidad: casos cuyo tiempo en minutos contradice a sus fechas.

    Revisa Resueltos con incident_resolved_time y compara contra
    $dateDiff(creation → resolved). También revisa incident_assigned_time
    contra $dateDiff(creation → in_progress). Devuelve los casos ordenados
    por discrepancia desc. Solo lectura.
    """
    try:
        umbral = max(float(umbral_min or 60.0), 1.0)
        lim = max(min(int(limite or 100), 500), 1)
    except Exception:
        umbral, lim = 60.0, 100
    pipe = [
        {"$match": {"incident_state": "Resuelto"}},
        {"$project": {
            "ticket": "$incident_ticket_number",
            "estado": "$incident_state",
            "sub": "$subcategory_name",
            "rt": "$incident_resolved_time",
            "at": "$incident_assigned_time",
            "diff_res": {"$dateDiff": {
                "startDate": "$incident_creation_date",
                "endDate": "$incident_resolved_date", "unit": "minute"}},
            "diff_asg": {"$dateDiff": {
                "startDate": "$incident_creation_date",
                "endDate": "$incident_in_progress_date", "unit": "minute"}},
            "cre": "$incident_creation_date",
            "res": "$incident_resolved_date",
        }},
        {"$limit": 2000},
    ]
    casos: list = []
    tz = get_display_tz()
    try:
        rows = list(db[INCIDENTS].aggregate(
            pipe, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS))
    except Exception as exc:
        return {"data": {"casos": [], "n": 0},
                "meta": {"coleccion": INCIDENTS, "error": str(exc)}}
    for r in rows:
        t = str(r.get("ticket") or "")
        for campo, val, diff in (("incident_resolved_time", r.get("rt"), r.get("diff_res")),
                                 ("incident_assigned_time", r.get("at"), r.get("diff_asg"))):
            if not isinstance(val, (int, float)) or not isinstance(diff, (int, float)):
                continue
            if diff < 0:
                continue
            tol = max(umbral, 0.1 * abs(diff))
            disc = abs(float(val) - float(diff))
            if disc > tol:
                casos.append({
                    "ticket": t,
                    "campo": campo,
                    "valor_min": val,
                    "fechas_dan_min": diff,
                    "diferencia_min": round(disc, 1),
                    "subcategoria": r.get("sub"),
                    "creacion_lima": to_display(r.get("cre"), tz),
                    "resolucion_lima": to_display(r.get("res"), tz),
                })
    casos.sort(key=lambda c: c["diferencia_min"], reverse=True)
    casos = casos[:lim]
    return {"data": {"casos": casos, "n": len(casos), "umbral_min": umbral},
            "meta": {"coleccion": INCIDENTS, "filtros": {"estado": "Resuelto"},
                     "documentos": len(casos), "zona": tz}}


def timeseries(db: Database, granularity: str = "month", tz: str | None = None, **filters) -> dict:
    """Serie temporal de creación de incidentes por día/semana/mes.

    Buckets en la zona del cliente (America/Lima por defecto). Sin timezone
    Mongo agrupa en UTC y un reporte de las 22:00 Lima cae al día siguiente.
    """
    match, desc = base_match(**filters)
    tz_name = tz or get_display_tz()
    try:
        _tzinfo(tz_name)
    except Exception:
        tz_name = DEFAULT_TZ
    fmt = {"day": "%Y-%m-%d", "week": "%Y-W%V", "month": "%Y-%m"}.get(granularity)
    if not fmt:
        raise ValueError("granularity debe ser day, week o month")
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        {"$group": {"_id": {"$dateToString": {"format": fmt, "date": "$incident_creation_date",
                                              "timezone": tz_name}},
                    "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
        {"$limit": 500},
    ]
    rows = [{"periodo": r["_id"], "n": r["n"]}
            for r in db[INCIDENTS].aggregate(
                pipeline, allowDiskUse=True, maxTimeMS=settings.QUERY_TIMEOUT_MS)]
    return {"data": {"puntos": rows, "total": sum(r["n"] for r in rows)},
            "meta": {"coleccion": INCIDENTS, "granularidad": granularity, "filtros": desc,
                     "documentos": sum(r["n"] for r in rows), "zona": tz_name}}


def distinct_values(db: Database, field: str) -> dict:
    """Valores distintos de un campo (para validar filtros: estados, categorías, etc.).

    Cache en memoria 5min por campo (dict + ttl): los valores cambian poco y
    el LLM suele pedirlos antes de cada filtro. 1er call va a Mongo, resto RAM.
    """
    mongo_field = GROUPABLE_FIELDS.get(field)
    if not mongo_field:
        raise ValueError(f"Campo inválido: {field!r}. Opciones: {sorted(GROUPABLE_FIELDS)}")
    cached = _distinct_cache_get(mongo_field)
    if cached is not None:
        return cached
    vals = sorted(v for v in db[INCIDENTS].distinct(
        mongo_field, maxTimeMS=settings.QUERY_TIMEOUT_MS) if v is not None)
    payload = {"data": {"campo": field, "valores": vals},
               "meta": {"coleccion": INCIDENTS, "documentos": len(vals)}}
    _distinct_cache_set(mongo_field, payload)
    return payload


# ---------------------------------------------------------------------------
# Definiciones OpenAI-compatible para el tool use de Groq
# ---------------------------------------------------------------------------
FILTER_PROPS = {
    "state": {"type": "string", "description": "Estado: Recibido, En progreso, Resuelto"},
    "category": {"type": "string", "description": "Categoría, ej. Emergencia, Alerta"},
    "workgroup": {"type": "string", "description": "Grupo de trabajo, ej. Seguridad Ciudadana"},
    "district": {"type": "string", "description": "Distrito / municipalidad"},
    "priority": {"type": "string", "description": "Prioridad: Alta, Media, Baja"},
    "from_date": {"type": "string", "description": "Desde (YYYY-MM-DD)"},
    "to_date": {"type": "string", "description": "Hasta (YYYY-MM-DD)"},
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "incidents_count",
        "description": "Cuenta incidentes agrupados por un campo. Úsalo para 'cuántos', distribuciones y comparaciones.",
        "parameters": {"type": "object", "properties": {
            "group_by": {"type": "string", "description": "estado, categoria, subcategoria, prioridad, grupo, grupo_operador, distrito, turno, origen, canal", "default": "estado"},
            **FILTER_PROPS}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "incidents_list",
        "description": "Lista incidentes (resumen) con filtros, búsqueda por texto y paginación.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "Máximo a devolver (default 50, max 500)"},
            "offset": {"type": "integer", "description": "Desde qué posición paginar"},
            "search": {"type": "string", "description": "Texto libre: ticket, descripción o ubicación"},
            **FILTER_PROPS}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "incident_detail",
        "description": "Detalle completo de UN incidente por su número de ticket.",
        "parameters": {"type": "object", "properties": {
            "ticket_number": {"type": "string", "description": "Número de ticket exacto"}}, "required": ["ticket_number"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "resolution_times",
        "description": "Estadísticas de tiempo de resolución en minutos (solo Resueltos). Excluye automáticamente casos con tiempo inconsistente vs fechas (van en advertencias). Opcionalmente agrupado.",
        "parameters": {"type": "object", "properties": {
            "group_by": {"type": "string", "description": "Opcional: mismo vocabulario que incidents_count"},
            **FILTER_PROPS}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "detectar_tiempos_inconsistentes",
        "description": "Auditoría de calidad: lista casos Resueltos cuyo tiempo en minutos contradice a sus fechas (error de registro en origen). Úsala si preguntan por datos sospechosos o si resolution_times trae advertencias.",
        "parameters": {"type": "object", "properties": {
            "umbral_min": {"type": "number", "description": "Tolerancia en minutos (default 60)", "default": 60},
            "limite": {"type": "integer", "description": "Máximo de casos (default 100)", "default": 100}}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "timeseries",
        "description": "Evolución temporal de incidentes creados por día, semana o mes. Para tendencias.",
        "parameters": {"type": "object", "properties": {
            "granularity": {"type": "string", "description": "day, week o month", "default": "month"},
            "tz": {"type": "string", "description": "Zona IANA del cliente, ej. America/Lima (default)"},
            **FILTER_PROPS}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "distinct_values",
        "description": "Valores existentes de un campo. Úsalo ANTES de filtrar si dudas del valor exacto.",
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string", "description": "estado, categoria, subcategoria, prioridad, grupo, distrito, turno, origen, canal"}}, "required": ["field"], "additionalProperties": False}}},
]

IMPLEMENTATIONS = {
    "incidents_count": incidents_count,
    "incidents_list": incidents_list,
    "incident_detail": incident_detail,
    "resolution_times": resolution_times,
    "detectar_tiempos_inconsistentes": detectar_tiempos_inconsistentes,
    "timeseries": timeseries,
    "distinct_values": distinct_values,
}
