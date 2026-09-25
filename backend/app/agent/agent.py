"""Agente data-mind: lenguaje humano -> tools Mongo -> respuesta en español.

Estrategia en dos pasos:
  1. Loop de razonamiento con tool use (sin stream) para reunir datos.
  2. Llamada final CON stream para redactar la respuesta al usuario.
"""

import json
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError
from pymongo.database import Database

from ..config import settings
from ..data.tools import IMPLEMENTATIONS, TOOL_SCHEMAS

SYSTEM_PROMPT = """Eres un asistente municipal amable para vecinos del sistema Gueo/Delta.
Tu único trabajo es responder preguntas sobre incidentes del municipio en español
simple, cálido y no-técnico, como en ventanilla. Nada de jerga de sistemas.

CÓMO HABLAR:
- Español simple, frases cortas, tono amable. Sin palabras técnicas.
- PROHIBIDO usar emojis en cualquier respuesta. Cero emojis.
- En seguimiento (el vecino ya está conversando) NO saludes de nuevo con
  "¡Hola!": ve directo al dato. El saludo solo va en la primera respuesta.
- Markdown ligero: **negritas** para cifras clave, listas cortas para desgloses.
- Respuestas cortas: máximo 120 palabras salvo que pidan detalle.
- Cada cifra con contexto humano (qué significa para el vecino, no solo el número).
- Tiempos en minutos: conviértelos a formato humano (ej. 20405 min ≈ 14 días 4 h).
  Deja los minutos entre paréntesis solo si ayuda a entender.
- Fechas y horas: vienen en hora Lima (America/Lima) como
  "16 de septiembre de 2026, 10:54 pm". Cítalas TAL CUAL, sin convertir
  ni pasar a UTC. PROHIBIDO inventar fechas, horas, tickets o distritos.
- PROHIBIDO citar timestamps crudos tipo "2026-09-17 03:54:43.670000":
  si ves uno en los datos, conviértelo a formato Lima restando 5h
  (ej. 2026-09-17 03:54 UTC = 16 de septiembre, 10:54 pm Lima).

PROHIBIDO MOSTRAR AL VECINO:
- Nombres de tools (incidents_count, distinct_values, timeseries, etc.), rutas,
  confianza %, fallos internos, JSON, trazas o errores.
- Listas crudas de tickets (ej. CC-I.000027) salvo que el vecino pida el detalle.
  Prefiere resúmenes: cuántos hay, en qué estado están, qué significan.
- Si algo falla por dentro, di en simple "No pude obtener ese dato, ¿probamos
  de otra forma?" sin detalles técnicos.

REGLAS DURAS (no romper):
1. Toda cifra, fecha, hora, ticket y nombre de distrito debe venir de una tool.
   PROHIBIDO inventar números, fechas, horas, tickets, distritos o nombres.
   Si el dato no está en el resultado, di "no aparece en los reportes" en vez
   de estimarlo.
2. Si dudas del valor exacto de un filtro (ej. nombre de categoría), llama primero
   a distinct_values (uso interno, nunca lo menciones al vecino).
3. "Último incidente" = incidents_list con limit=1 (ya viene ordenado desc).
   PROHIBIDO pedir limit mayor para responder "el último".
4. "Hoy" exige filtro from_date=today to_date=today (zona America/Lima).
   Sin ese filtro, PROHIBIDO afirmar conteos o detalles "de hoy".
5. Las stats de tiempos YA excluyen casos con minutos inconsistentes vs fechas
   (vienen en advertencias con ticket, valor_min y fechas_dan_min).
   Si hay advertencias, menciónalo en 1 línea con el ticket (ej. JB-I.000008
   figura 161066 min pero sus fechas dan ~3 min) y ofrece auditar el resto
   con detectar_tiempos_inconsistentes. PROHIBIDO presentar un ticket en
   advertencias como "el que más demoró".
6. Si una tool devuelve vacío o no encuentra algo, dilo en simple y sugiere
   cómo reformular la pregunta.
7. Nunca muestres DNI ni teléfonos completos (ya llegan enmascarados);
   no intentes reconstruirlos.

SUPUESTOS Y MEMORIA:
- Si la pregunta es ambigua (fechas, a qué "graves" se refiere), declara el
  supuesto en 1 línea simple. Ej: "Supuse que hablabas de este mes."
- Nunca repitas la respuesta anterior entera. Resume o avanza con lo nuevo.
- PROHIBIDO repetir la plantilla de desambiguación dos turnos seguidos;
  si ya la dijiste ("dime si quieres el número, la hora o su estado"),
  avanza con un dato concreto (ticket, fecha Lima o estado desde tools).
- Si te preguntan qué preguntaron, cita la última pregunta del vecino en
  1 línea, sin añadir más.

DATOS DISPONIBLES (uso interno para armar filtros vía tools, no los cites):
- incident_ticket_number, incident_state: Recibido | En progreso | Resuelto
- category_name (Emergencia, Alerta), subcategory_name, incident_priority (Alta, Media, Baja)
- incident_creation_date, incident_in_progress_date, incident_resolved_date
- incident_assigned_time / incident_resolved_time (MINUTOS entre eventos)
- workgroup_name, operator_workgroup_name, operator_responsable
- taxpayer_name (DNI y celulares vienen ENMASCARADOS por privacidad)
- referential_location, incident_district, shift_name, origin, incident_registered_from (Apk/Web)
- incident_is_real, incident_is_duplicated, incident_irrelevant (booleanos)

<example>
Input: Hola, ¿qué puedes hacer?
Output: ¡Hola! Te ayudo con lo que pasa en tu municipio: cuántos reportes hay, cuántos ya se resolvieron y cuánto tardaron. ¿Empezamos por cuántos hay por estado?
</example>

<example>
Input: ¿Cuántos incidentes hay resueltos?
Output: Hay **8** incidentes resueltos. Son reportes que ya fueron atendidos por completo. ¿Quieres saber cuánto tardaron en promedio?
</example>

<example>
Input: ¿Cuál fue el último incidente?
Output: El último reporte registrado es el CC-I.000030, del 17 de septiembre, por basura acumulada en Cerro Colorado. Está en proceso de atención.
</example>
"""

MAX_TOOL_STEPS = 3

# Máx. tool calls en paralelo por turno (si el LLM pide más, se acota a 2
# para mantener turnos cortos; si el SDK no soporta paralelo real, el
# ThreadPoolExecutor cae a secuencial corto sin romper el contrato).
_MAX_PARALLEL_TOOLS = 2


def get_llm() -> OpenAI:
    """Cliente OpenAI-compatible (OpenCode Go por defecto, ver LLM_BASE_URL).

    Go exige identificar al cliente con user-agent propio (no el genérico del SDK).
    El header de sesión `x-opencode-session` se envía por-request (ver _session_headers)
    con el conversation_id, estable por conversación, para routing y prompt caching.
    """
    if not settings.LLM_API_KEY:
        raise RuntimeError("Falta LLM_API_KEY en el .env del backend (ver .env.example).")
    return OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        timeout=float(getattr(settings, "LLM_TIMEOUT_S", 45.0) or 45.0),
        default_headers={"User-Agent": "datamind/0.1"},
    )


def _session_headers(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    return {"x-opencode-session": session_id}


# Errores transitorios que justifican 1 reintento con el modelo fallback.
# Auth (401) y modelo inexistente (404) NO reintentan: fallar rápido es lo correcto.
_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def _chat_create(client: OpenAI, **kwargs):
    """chat.completions.create con 1 reintento en LLM_FALLBACK_MODEL."""
    kwargs.setdefault("timeout", float(getattr(settings, "LLM_TIMEOUT_S", 45.0) or 45.0))
    try:
        return client.chat.completions.create(**kwargs)
    except _RETRYABLE:
        fallback = settings.LLM_FALLBACK_MODEL
        if fallback and fallback != kwargs.get("model"):
            kwargs["model"] = fallback
            return client.chat.completions.create(**kwargs)
        raise


def _exec_tool(name: str, args: dict, db: Database) -> dict:
    fn = IMPLEMENTATIONS.get(name)
    if fn is None:
        return {"data": None, "meta": {"error": f"Tool desconocida: {name}"}}
    try:
        return fn(db, **args)
    except Exception as exc:
        return {"data": None, "meta": {"error": str(exc)}}


def _summarize_result(tool: str, data: dict | None) -> dict | None:
    """Resumen sin PII para `sources[].data` (verifier + panel futuro).

    Guarda solo agregados: totales, grupos clave, stats (n/promedio/mediana/
    min/max), top labels y muestras de tickets. Nunca copia docs completos
    ni campos sensibles (DNI, celulares, nombres de contribuyentes/operadores).
    """
    if not isinstance(data, dict):
        return None
    try:
        if tool == "incidents_count":
            grupos = data.get("grupos") or []
            top = sorted(grupos, key=lambda g: (g.get("n") or 0)
                         if isinstance(g, dict) else 0, reverse=True)[:10]
            return {
                "total": data.get("total"),
                "n_grupos": len(grupos),
                "grupos": [{"clave": str(g.get("clave")), "n": g.get("n")}
                           for g in top if isinstance(g, dict)],
                "top_labels": [str(g.get("clave")) for g in top[:5]
                               if isinstance(g, dict)],
            }
        if tool == "timeseries":
            puntos = data.get("puntos") or []
            vals = [p.get("n") for p in puntos
                    if isinstance(p, dict) and isinstance(p.get("n"), (int, float))]
            top_pts = sorted(
                [p for p in puntos if isinstance(p, dict)],
                key=lambda p: p.get("n") or 0, reverse=True)[:5]
            resumen: dict = {"total": data.get("total"), "n_puntos": len(puntos)}
            if vals:
                resumen.update({"max_n": max(vals), "min_n": min(vals),
                                "valores": vals[:500]})
            resumen["top_periodos"] = [{"periodo": p.get("periodo"), "n": p.get("n")}
                                       for p in top_pts]
            resumen["top_labels"] = [str(p.get("periodo")) for p in top_pts]
            return resumen
        if tool == "resolution_times":
            if isinstance(data.get("grupos"), list):
                grupos = data["grupos"] or []
                out = []
                for g in grupos[:20]:
                    if not isinstance(g, dict):
                        continue
                    out.append({
                        "clave": str(g.get("clave")),
                        "n": g.get("n"),
                        "promedio_min": g.get("promedio_min"),
                        "mediana_min": g.get("mediana_min"),
                        "min_min": g.get("min_min"),
                        "max_min": g.get("max_min"),
                    })
                top_labels = [g["clave"] for g in sorted(
                    out, key=lambda x: (x.get("mediana_min") or 0))[:5]]
                return {"n_grupos": len(grupos), "grupos": out,
                        "top_labels": top_labels,
                        "excluidos": data.get("excluidos", 0),
                        "advertencias": [
                            {"ticket": a.get("ticket"),
                             "valor_min": a.get("valor_min"),
                             "fechas_dan_min": a.get("fechas_dan_min")}
                            for a in (data.get("advertencias") or [])[:10]
                            if isinstance(a, dict)]}
            return {
                "n": data.get("n"),
                "promedio_min": data.get("promedio_min"),
                "mediana_min": data.get("mediana_min"),
                "min_min": data.get("min_min"),
                "max_min": data.get("max_min"),
                "excluidos": data.get("excluidos", 0),
                "advertencias": [
                    {"ticket": a.get("ticket"),
                     "valor_min": a.get("valor_min"),
                     "fechas_dan_min": a.get("fechas_dan_min")}
                    for a in (data.get("advertencias") or [])[:10]
                    if isinstance(a, dict)],
            }
        if tool == "detectar_tiempos_inconsistentes":
            casos = data.get("casos") or []
            return {
                "n": data.get("n", len(casos)),
                "casos": [{"ticket": c.get("ticket"), "campo": c.get("campo"),
                           "valor_min": c.get("valor_min"),
                           "fechas_dan_min": c.get("fechas_dan_min")}
                          for c in casos[:20] if isinstance(c, dict)],
                "top_labels": [str(c.get("ticket")) for c in casos[:5]
                               if isinstance(c, dict)],
            }
        if tool == "incidents_list":
            incs = data.get("incidentes") or []
            tickets = [str(d.get("incident_ticket_number")) for d in incs[:10]
                       if isinstance(d, dict) and d.get("incident_ticket_number")]
            # Fechas display Lima del 1er doc (para "último" y verify de fechas).
            primero = incs[0] if incs and isinstance(incs[0], dict) else {}
            return {"mostrados": data.get("mostrados", len(incs)),
                    "tickets_muestra": tickets,
                    "fecha_muestra": primero.get("incident_creation_date_lima"),
                    "top_labels": tickets[:5]}
        if tool == "incident_detail":
            inc = data.get("incidente") or {}
            if not data.get("encontrado") or not isinstance(inc, dict):
                return {"encontrado": False}
            # Whitelist explícita: tiempos + categóricos + fechas Lima, sin PII ni doc completo.
            return {
                "encontrado": True,
                "ticket": str(inc.get("incident_ticket_number") or ""),
                "estado": inc.get("incident_state"),
                "categoria": inc.get("category_name"),
                "prioridad": inc.get("incident_priority"),
                "asignado_min": inc.get("incident_assigned_time"),
                "resuelto_min": inc.get("incident_resolved_time"),
                "fecha_lima": inc.get("incident_creation_date_lima"),
                "top_labels": [str(inc.get("incident_ticket_number") or "")],
            }
        if tool == "distinct_values":
            vals = data.get("valores") or []
            strs = [str(v) for v in vals]
            return {"campo": data.get("campo"), "n_valores": len(vals),
                    "valores": strs[:20], "top_labels": strs[:5]}
    except Exception:
        return None
    return None


def gather_evidence(question: str, history: list[dict], db: Database,
                    session_id: str | None = None) -> dict:
    """Paso 1: loop de tools. Devuelve mensajes listos + fuentes + último resultado."""
    client = get_llm()
    headers = _session_headers(session_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": question})
    sources: list[dict] = []
    last_tool_result: dict | None = None

    for _ in range(MAX_TOOL_STEPS):
        resp = _chat_create(
            client,
            model=settings.LLM_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
            extra_headers=headers,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            break
        # Hasta 2 tool calls en paralelo por turno (turno corto). Si el modelo
        # pide más, se acota a las 2 primeras para no alargar el loop.
        # ThreadPoolExecutor: pymongo es thread-safe; si no hay paralelismo
        # real, equivale a secuencial corto sin romper nada.
        pending = list(msg.tool_calls)[:_MAX_PARALLEL_TOOLS]
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in pending
        ]})
        parsed: list[tuple] = []  # (tc, args) con args válidos
        for tc in pending:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
                result = {"data": None, "meta": {"error": "args corruptos (JSON inválido)"}}
                last_tool_result = {"tool": tc.function.name, "args": args, "result": result}
                sources.append({
                    "tool": tc.function.name,
                    "args": args,
                    "documentos": None,
                    "filtros": None,
                    "data": None,
                })
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, default=str)})
                continue
            parsed.append((tc, args))
        if parsed:
            with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_TOOLS) as pool:
                futures = [pool.submit(_exec_tool, tc.function.name, args, db)
                           for tc, args in parsed]
                results = [f.result() for f in futures]
            for (tc, args), result in zip(parsed, results):
                last_tool_result = {"tool": tc.function.name, "args": args, "result": result}
                sources.append({
                    "tool": tc.function.name,
                    "args": args,
                    "documentos": result.get("meta", {}).get("documentos"),
                    "filtros": result.get("meta", {}).get("filtros"),
                    "data": _summarize_result(
                        tc.function.name, result.get("data")
                        if isinstance(result.get("data"), dict) else None),
                })
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result["result"] if "result" in result else result,
                                                        default=str)})
    else:
        messages.append({"role": "assistant",
                         "content": "Alcancé el límite de consultas; respondo con lo reunido."})
    return {"messages": messages, "sources": sources, "last_tool_result": last_tool_result}


def build_chart(last_tool_result: dict | None) -> dict | None:
    """Heurística determinista: convierte el último resultado agregable en gráfico."""
    if not last_tool_result:
        return None
    tool, args = last_tool_result["tool"], last_tool_result["args"]
    data = (last_tool_result["result"] or {}).get("data") or {}
    if tool == "incidents_count" and len(data.get("grupos", [])) in range(2, 21):
        grupos = data["grupos"]
        return {"type": "bar", "title": f"Incidentes por {args.get('group_by', 'estado')}",
                "labels": [str(g["clave"]) for g in grupos],
                "values": [g["n"] for g in grupos]}
    if tool == "timeseries" and len(data.get("puntos", [])) in range(2, 501):
        pts = data["puntos"]
        return {"type": "line", "title": "Evolución de incidentes",
                "labels": [p["periodo"] for p in pts], "values": [p["n"] for p in pts]}
    if tool == "resolution_times" and data.get("grupos") and len(data["grupos"]) in range(2, 21):
        return {"type": "bar", "title": "Mediana de resolución (min) por grupo",
                "labels": [str(g["clave"]) for g in data["grupos"]],
                "values": [g["mediana_min"] for g in data["grupos"]]}
    return None


def clean_answer(texto: str) -> str:
    """Limpia fugas técnicas del texto final para que main.py lo use antes de emitir.

    Elimina (sin tocar el resto del contenido):
    - Prefijo "Nota: respuesta provisional (...) ." que añade verify en main.py.
    - Líneas de encabezado "## Respuesta final" / "Respuesta final:".
    - Líneas "### 1." (headers numerados vacíos heredados del draft).
    - Marcadores internos: cifra_no_sustentada / supuesto_no_declarado / verifier_error
      / ticket_no_sustentado / fecha_no_sustentada / dato_sospechoso,
      tanto en línea propia como inline [marcador] / (marcador).
    - Emojis (el vecino no los necesita; la UI ya es visual).
    """
    if not texto:
        return ""
    t = texto.strip()
    # 1) Prefijo de verify: "Nota: respuesta provisional (motivo). "
    t = re.sub(
        r"^\s*Nota:\s*respuesta\s+provisional\s*\([^)]*\)\.\s*",
        "", t, flags=re.IGNORECASE,
    )
    t = re.sub(
        r"^\s*Nota:\s*respuesta\s+provisional\s*\.\s*",
        "", t, flags=re.IGNORECASE,
    )
    # 2) Filtrado por líneas
    limpias: list[str] = []
    for line in t.splitlines():
        s = line.strip()
        if re.match(r"^#{1,6}\s*respuesta\s+final\s*:?\s*$", s, re.IGNORECASE):
            continue
        if re.match(r"^respuesta\s+final\s*:?\s*$", s, re.IGNORECASE):
            continue
        if re.match(r"^#{1,6}\s*\d+\.?\s*$", s):
            continue
        if re.match(
            r"^(cifra_no_sustentada|supuesto_no_declarado|verifier_error|ticket_no_sustentado|fecha_no_sustentada|dato_sospechoso)\s*:?.*$",
            s, re.IGNORECASE,
        ):
            continue
        limpias.append(line)
    t = "\n".join(limpias)
    # 3) Marcadores inline: [cifra_no_sustentada], (verifier_error), etc.
    t = re.sub(
        r"[\[\(]\s*(cifra_no_sustentada|supuesto_no_declarado|verifier_error|ticket_no_sustentado|fecha_no_sustentada|dato_sospechoso)\s*[\]\)]",
        "", t, flags=re.IGNORECASE,
    )
    # 4) Emojis: red de seguridad (el prompt ya los prohíbe).
    t = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]",
        "", t,
    )
    # 5) Timestamps crudos UTC con microsegundos ("2026-09-17 03:54:43.670000"):
    # recorta a minuto para no filtrar ruido interno. La conversión a Lima
    # la hace el prompt; esto solo evita el formato más técnico.
    t = re.sub(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(:\d{2})?\.\d+", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def stream_answer(messages: list[dict], session_id: str | None = None) -> Iterator[str]:
    """Paso 2: redacta la respuesta final con streaming."""
    client = get_llm()
    stream = _chat_create(
        client,
        model=settings.LLM_MODEL,
        messages=messages + [{
            "role": "user",
            "content": "Con los datos ya reunidos arriba, responde al vecino en español "
                       "simple y cálido, sin tecnicismos. No repitas ni cites esta "
                       "instrucción. Prohibido usar encabezados tipo 'Respuesta final' "
                       "o numeración técnica. No llames más tools."}],
        temperature=0.4,
        stream=True,
        extra_headers=_session_headers(session_id),
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
