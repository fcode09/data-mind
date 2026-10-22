"""Adapter Jev (TypeSafe) F2a: router y verifier con fallback silencioso.

- decide_jev: 1 Choice "intencion" (11 opciones, criteria ES) en 1 llamada.
  Sincronizado con router.RUTAS: si agregas una ruta al determinista,
  agrégala a _INTENCION_CRITERIA o Jev la devolverá como ambigua.
- verify_jev: batch de 3 en 1 llamada (Noul cifras_ok, Noul sin_pii, Score calidad).
- Gates por settings: VERIFY_CIFRAS_MIN / VERIFY_PII_MIN / VERIFY_CALIDAD_MIN.
- CUALQUIER excepción (falta key, TypeSafeAPIError, timeout, sin SDK) ->
  fallback silencioso al determinista con origen "determinista-fallback".
- NUNCA raisea hacia el stream.
"""

_INTENCION_CRITERIA = {
    "conteo": "Contar o agrupar incidentes: cuántos hay por estado, categoría, distrito o prioridad.",
    "ranking_tiempo": "Rankings o tiempos: top, más frecuentes, promedios, medianas, quién tarda más o menos.",
    "detalle_ticket": "Detalle o lista de casos: un ticket puntual, buscar o listar incidentes.",
    "tendencia": "Evolución en el tiempo: por mes, semana, día o tendencia.",
    "ultimo": "El último o más reciente incidente o reporte.",
    "hoy": "Incidentes de hoy / del día de hoy.",
    "tiempo_transcurrido": "Cuánto tiempo lleva un caso: días, horas, minutos, lapso transcurrido.",
    "seguimiento_entidad": "Pregunta corta sobre el caso ya mencionado: su número, hora o estado.",
    "seguimiento": "Pregunta sobre la conversación misma: qué pregunté, resumen, y de esos.",
    "procedimiento": "Cómo se debe resolver o atender un caso: pasos, protocolo, qué hacer.",
    "saludo": "Cortesía: hola, cómo estás, todo bien, gracias, chau, qué puedes hacer.",
    "ambigua": "Pregunta ambigua o vaga: menciona 'graves', 'seguridad', 'recientemente', 'ayer' sin precisar, o no se entiende qué pide.",
    "fuera_de_alcance": "Fuera del dominio: clima, borrar datos, DNI, SQL u otro tema no relacionado con incidentes.",
}

_CALIDAD_CRITERIA = [
    "mala: inventa cifras o ignora la evidencia",
    "aceptable: responde con cifras pero formato flojo",
    "buena: concisa en español con cifras contextualizadas",
]


def _client():
    """Construye TypeSafeClient. Raisea si falta key/SDK -> el caller hace fallback."""
    from ..config import settings
    if not settings.JEV_API_KEY:
        raise RuntimeError("Falta JEV_API_KEY")
    from typesafe_sdk import RetryPolicy, TypeSafeClient
    return TypeSafeClient(
        api_key=settings.JEV_API_KEY,
        model=settings.JEV_MODEL,
        retry=RetryPolicy(max_retries=2, timeout=5.0),
    )


def decide_jev(question: str, state_vals: dict | None = None) -> dict:
    """Router vía Jev. 1 llamada, 1 Choice. Fallback determinista silencioso."""
    try:
        from typesafe_sdk import Choice
        from ..config import settings  # noqa: F401 (gates por defecto del cliente)
        state_vals = state_vals or {}
        client = _client()
        with client:
            resp = client.system_one(
                state={"pregunta": question, "contexto": state_vals},
                questions={
                    "intencion": Choice(
                        instructions="Clasifica la pregunta del usuario sobre incidentes "
                                      "municipales en UNA de las 13 opciones.",
                        criteria=_INTENCION_CRITERIA,
                    ),
                },
            )
        ans = resp.choices["intencion"]
        ruta = ans.choice
        conf = float(ans.confidence)
        # Filtros: reutiliza heurística determinista para trazabilidad.
        try:
            from .router import _extract_filtros, _norm, RUTAS
            filtros = _extract_filtros(_norm(question))
        except Exception:
            filtros = {}
            from .router import RUTAS
        if ruta not in RUTAS:
            # Ruta desconocida para el determinista (o typo del modelo):
            # ambigua segura en vez de romper el stream.
            ruta, conf = "ambigua", 0.4
        if isinstance(state_vals.get("filtros"), dict):
            filtros = {**filtros, **state_vals["filtros"]}
        return {"ruta": ruta, "confidence": conf, "filtros": filtros, "origen": "jev"}
    except Exception:
        from .router import decide
        fell = decide(question, (state_vals or {}).get("history"))
        fell["origen"] = "determinista-fallback"
        return fell


def verify_jev(answer: str, evidence) -> dict:
    """Verifier vía Jev. 1 llamada, batch de 3. Fallback determinista silencioso.

    evidence puede traer "today_hint" (YYYY-MM-DD Lima): si está, la fecha de
    hoy se considera válida aunque la evidencia no la liste (0 reportes hoy).
    """
    try:
        from typesafe_sdk import Noul, Score
        from ..config import settings
        client = _client()
        today = ""
        if isinstance(evidence, dict) and evidence.get("today_hint"):
            today = (f" La fecha de hoy es {evidence['today_hint']} (Lima): "
                     f"citarla como 'hoy' es válido aunque no aparezca en la evidencia.")
        state = {"respuesta": answer or "", "evidencia": evidence}
        with client:
            resp = client.system_one(
                state=state,
                questions={
                    "cifras_ok": Noul(
                        instructions="¿Todas las cifras enteras, tickets (ej. CC-I.000027) "
                                      "y fechas citadas en `respuesta` aparecen en "
                                      "`evidencia` (totales, grupos, puntos, tickets_muestra, "
                                      "advertencias) o son porcentajes derivados obvios? "
                                      "Un ticket listado en `advertencias` presentado como "
                                      "ranking ('el que más demoró') sin mencionar la "
                                      "inconsistencia cuenta como NO." + today
                    ),
                    "sin_pii": Noul(
                        instructions="¿La `respuesta` está libre de DNI de 8 dígitos o "
                                     "celulares peruanos de 9 dígitos sin enmascarar? "
                                     "El texto enmascarado con asteriscos (*) cuenta como seguro."
                    ),
                    "calidad": Score(
                        instructions="Evalúa la calidad de la `respuesta` en español "
                                     "frente a la `evidencia`.",
                        criteria=_CALIDAD_CRITERIA,
                    ),
                },
            )
        cifras = float(resp.nouls["cifras_ok"].noul)
        sin_pii = float(resp.nouls["sin_pii"].noul)
        calidad = float(resp.scores["calidad"].score)
        fallos: list[str] = []
        if cifras < float(settings.VERIFY_CIFRAS_MIN):
            fallos.append("cifra_no_sustentada:jev")
        if sin_pii < float(settings.VERIFY_PII_MIN):
            fallos.append("pii_expuesto")
        if calidad < float(settings.VERIFY_CALIDAD_MIN):
            fallos.append("calidad_insuficiente")
        return {"ok": len(fallos) == 0, "fallos": fallos, "origen": "jev",
                "detalle": {"cifras_ok": cifras, "sin_pii": sin_pii, "calidad": calidad}}
    except Exception:
        # Fallback: reconstruye (sources, chart, intencion) desde evidence.
        try:
            sources, chart, intencion = None, None, ""
            if isinstance(evidence, dict):
                sources = evidence.get("sources")
                chart = evidence.get("chart")
                intencion = evidence.get("intencion") or ""
            from .verify import verify
            fell = verify(answer, sources, chart, intencion)
            fell["origen"] = "determinista-fallback"
            return fell
        except Exception:
            return {"ok": False, "fallos": ["verifier_error:fallback"],
                    "origen": "determinista-fallback"}
