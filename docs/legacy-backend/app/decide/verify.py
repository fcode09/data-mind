"""Verifier determinista F1: respuesta -> {ok, fallos, origen}.

Chequeos:
(a) cifras: cada entero citado debe aparecer en sources/chart o ser % derivado.
(b) PII: DNI 8 dígitos o celular PE 9 dígitos sin enmascarar -> pii_expuesto.
(c) ambigua sin supuesto declarado -> supuesto_no_declarado.
"""

import re
import unicodedata

_SUPUESTO_MARKERS = ("asumo", "supongo", "entendi", "quieres decir", "supuesto", "asumiendo")


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _collect_numbers(obj, out: set[int | float]) -> None:
    """Recolecta ints/floats de una estructura anidada (sources/chart)."""
    if obj is None:
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        out.add(obj)
        return
    if isinstance(obj, float):
        out.add(obj)
        if obj.is_integer():
            out.add(int(obj))
        return
    if isinstance(obj, str):
        # Filtros como "top 5" o documentos en strings: extrae enteros.
        for m in re.finditer(r"\d+", obj):
            try:
                out.add(int(m.group(0)))
            except ValueError:
                pass
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _collect_numbers(v, out)


def _add_time_derivatives(allowed: set) -> None:
    """Derivados días/horas desde minutos (ej. 20405 min -> 14 días, 4 h).

    Por cada cifra de minutos M añade: M/60, M/1440 (exacto + redondeo +
    truncado) y el desglose entero días/horas/minutos (M//1440,
    (M%1440)//60, M%60, M//60). Cubre el formato humano que exige el prompt
    ("20405 min ≈ 14 días 4 h") sin flaggear 14/4 como alucinación.
    """
    try:
        base = [v for v in list(allowed)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
    except Exception:
        return
    for v in base:
        try:
            f = float(v)
            for d in (f / 60.0, f / 1440.0):
                allowed.add(d)
                if float(d).is_integer():
                    allowed.add(int(d))
                else:
                    allowed.add(round(d))
                    allowed.add(int(d))
            if f.is_integer():
                m = int(f)
                if m >= 30:  # umbral: evita contaminar conteos pequeños
                    allowed.add(m // 60)
                    allowed.add(m // 1440)
                    allowed.add((m % 1440) // 60)
                    allowed.add(m % 60)
        except Exception:
            continue


def _add_group_sums(sources, chart, allowed: set) -> None:
    """Sumas derivadas: total = suma de grupos/puntos/valores.

    Cubre incidents_count (grupos), timeseries (puntos) y chart.values.
    Los totales explícitos ya entran vía _collect_numbers; aquí se añade
    la suma aunque el LLM la calcule y el total no venga en sources.
    """
    def _add_sum(vals: list) -> None:
        try:
            nums = [v for v in vals if isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if not nums:
                return
            s = sum(nums)
            allowed.add(s)
            if isinstance(s, float) and s.is_integer():
                allowed.add(int(s))
        except Exception:
            pass

    def _walk(obj) -> None:
        if isinstance(obj, dict):
            g = obj.get("grupos")
            if isinstance(g, list):
                _add_sum([x.get("n") for x in g
                          if isinstance(x, dict) and isinstance(x.get("n"), (int, float))])
            p = obj.get("puntos")
            if isinstance(p, list):
                _add_sum([x.get("n") for x in p
                          if isinstance(x, dict) and isinstance(x.get("n"), (int, float))])
            for key in ("values", "valores"):
                v = obj.get(key)
                if isinstance(v, list):
                    _add_sum(v)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, (list, tuple, set)):
            for v in obj:
                _walk(v)

    try:
        _walk(sources)
        _walk(chart)
    except Exception:
        pass


def _allowed_numbers(sources, chart) -> set:
    allowed: set = set()
    _collect_numbers(sources, allowed)
    _collect_numbers(chart, allowed)
    # Whitelist incident_detail: los tiempos del doc (asignado/resuelto y
    # stats) ya entran vía sources[].data resumida + _collect_numbers.
    # Suma del chart (ej. total = suma de grupos) como derivado obvio.
    try:
        if isinstance(chart, dict) and isinstance(chart.get("values"), list):
            vals = [v for v in chart["values"] if isinstance(v, (int, float))]
            if vals:
                s = sum(vals)
                allowed.add(s)
                if isinstance(s, float) and s.is_integer():
                    allowed.add(int(s))
    except Exception:
        pass
    _add_group_sums(sources, chart, allowed)
    _add_time_derivatives(allowed)
    # Redondeos ±1: el LLM suele redondear promedios/medianas y conteos.
    try:
        for n in list(allowed):
            if isinstance(n, bool):
                continue
            if isinstance(n, int):
                if n - 1 >= 0:
                    allowed.add(n - 1)
                allowed.add(n + 1)
            elif isinstance(n, float) and n.is_integer():
                i = int(n)
                if i - 1 >= 0:
                    allowed.add(i - 1)
                allowed.add(i + 1)
    except Exception:
        pass
    # Triviales: 0/1 (conteos vacíos, singular/plural) no son alucinación.
    allowed.add(0)
    allowed.add(1)
    return allowed


_TICKET_RE = re.compile(r"[A-Z]{1,5}-I\.\d+", re.IGNORECASE)
_NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_PII8_RE = re.compile(r"\b\d{8}\b")
_PII9_RE = re.compile(r"\b9\d{8}\b")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
# Fechas humanas citadas ("17 de septiembre", "24 de septiembre") y horas ("3:54").
_FECHA_HUMANA_RE = re.compile(r"\b\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?", re.IGNORECASE)
_HORA_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_PERIODO_RE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")


def _source_text_blob(sources, chart) -> str:
    """Todo el texto serializado de la evidencia (para comparar tickets/fechas)."""
    import json as _json
    try:
        return _json.dumps({"s": sources, "c": chart}, default=str).lower()
    except Exception:
        return str(sources).lower() + str(chart).lower()


def _tickets_in_blob(blob: str) -> set:
    return {m.group(0).upper() for m in _TICKET_RE.finditer(blob)}


def _fechas_in_blob(blob: str) -> set:
    out: set = set()
    for rx in (_FECHA_HUMANA_RE, _HORA_RE, _PERIODO_RE):
        for m in rx.finditer(blob):
            out.add(m.group(0).lower())
    return out


def _is_percentage(n_str: str, pos: int, text: str) -> bool:
    window = text[max(0, pos - 20):pos + len(n_str) + 20].lower()
    if "%" in window:
        return True
    if "por ciento" in window or "porciento" in window or "porcentaje" in window:
        return True
    return False


def verify(answer_text: str, sources, chart, intencion: str,
           today_hint: str | None = None) -> dict:
    """Verificación determinista pura. Nunca hace red ni raise.

    today_hint (YYYY-MM-DD Lima): cuando intencion==hoy, la fecha de hoy
    (en humano e ISO) se permite aunque timeseries no la traiga (0 reportes).
    """
    fallos: list[str] = []
    text = answer_text or ""
    try:
        allowed = _allowed_numbers(sources, chart)
        allowed_ints = {int(v) for v in allowed
                        if isinstance(v, int) or (isinstance(v, float) and v.is_integer())}
        allowed_floats = {float(v) for v in allowed if isinstance(v, (int, float))}
        # Fecha de hoy (ruta hoy): día/mes/año también valen como cifras.
        if (intencion or "") == "hoy" and today_hint:
            try:
                _yy, _mm, _dd = [int(x) for x in str(today_hint).split("-")]
                allowed_ints.update({_yy, _mm, _dd})
            except Exception:
                pass

        # (a) cifras: oculta tickets y enmascarados antes de extraer.
        scrubbed = _TICKET_RE.sub(" ", text)
        # Fragmentos con * son enmascarados: no cuentan como cifras citadas.
        scrubbed = re.sub(r"[*\d]*\*+[*\d]*", " ", scrubbed)
        for m in _NUM_RE.finditer(scrubbed):
            raw = m.group(0)
            # Normaliza "12,5"/"12.5" a float; miles "1,000" se trata como 1000 si es entero.
            try:
                if "," in raw or "." in raw:
                    val = float(raw.replace(",", "."))
                    is_int_like = val.is_integer()
                    ival = int(val) if is_int_like else None
                else:
                    ival = int(raw)
                    val = float(ival)
                    is_int_like = True
            except ValueError:
                continue
            if not is_int_like:
                # Decimales (promedios 20405.5, medianas): compara contra floats permitidos
                # con tolerancia de redondeo; si no hay floats, ignora para no flaggear.
                if val in allowed_floats:
                    continue
                # Redondeo a 1 decimal: acepta si algún permitido está a <1.0
                if any(abs(val - a) < 1.0 for a in allowed_floats):
                    continue
                # Sin evidencia numérica decimal disponible -> no flaggear (evita falsos
                # positivos en tiempos con decimales); el gate Jev cubre este caso.
                continue
            n_int = ival
            # Ignora años (2021, 2024...) y minutos-vs-días triviales ya cubiertos.
            if _YEAR_RE.match(str(n_int)):
                continue
            if n_int in allowed_ints:
                continue
            # Redondeo ±1 (conteos y tiempos redondeados por el LLM).
            if any(abs(n_int - a) <= 1 for a in allowed_ints):
                continue
            # Redondeo desde stats decimales (ej. promedio 123.4 -> "123").
            if any(abs(float(n_int) - a) < 1.0 for a in allowed_floats):
                continue
            if _is_percentage(raw, m.start(), text):
                continue
            fallos.append(f"cifra_no_sustentada:{n_int}")

        # (b) PII sin enmascarar (ignora texto con * cerca del match).
        if "*" not in text or True:
            for pat in (_PII9_RE, _PII8_RE):
                for m in pat.finditer(text):
                    ctx = text[max(0, m.start() - 10):m.end() + 10]
                    if "*" in ctx:
                        continue
                    fallos.append("pii_expuesto")
                    break
                if "pii_expuesto" in fallos:
                    break

        # (c) ambigua exige supuesto declarado.
        if (intencion or "") == "ambigua":
            nn = _norm(text)
            if not any(k in nn for k in _SUPUESTO_MARKERS):
                fallos.append("supuesto_no_declarado")

        # (d) anti-alucinación entidad/fecha: tickets y fechas citados deben
        # existir en la evidencia. Solo se chequea cuando hay evidencia con
        # la que comparar (sources no vacíos); fast-paths locales no pasan
        # por aquí. Tolerante: jamás rompe el stream.
        try:
            if sources:
                blob = _source_text_blob(sources, chart)
                blob_tickets = _tickets_in_blob(blob)
                # Tickets: solo si alguna fuente trae tickets (detail/list).
                # Conteos puros (sin tickets en evidencia) no se chequean.
                if blob_tickets:
                    for m in _TICKET_RE.finditer(text):
                        if m.group(0).upper() not in blob_tickets:
                            fallos.append(f"ticket_no_sustentado:{m.group(0).upper()}")
                            break
                # Fechas humanas y periodos: si la evidencia trae fechas
                # (timeseries/detail/list) la citada debe estar ahí.
                # Excepción: la fecha de HOY en ruta hoy (0 reportes no la traen).
                blob_fechas = _fechas_in_blob(blob)
                hoy_toks: set = set()
                if (intencion or "") == "hoy" and today_hint:
                    try:
                        from datetime import date as _date
                        y, mth, d = [int(x) for x in str(today_hint).split("-")]
                        _MESES = ("", "enero", "febrero", "marzo", "abril", "mayo",
                                  "junio", "julio", "agosto", "septiembre",
                                  "octubre", "noviembre", "diciembre")
                        hoy_toks = {str(today_hint).lower(),
                                    f"{d} de {_MESES[mth]}",
                                    f"{d} de {_MESES[mth]} de {y}"}
                    except Exception:
                        hoy_toks = {str(today_hint).lower()}
                if blob_fechas or hoy_toks:
                    for rx in (_FECHA_HUMANA_RE, _PERIODO_RE):
                        for m in rx.finditer(text):
                            tok = m.group(0).lower()
                            if tok in hoy_toks:
                                continue
                            if tok not in blob_fechas and not _YEAR_RE.match(tok):
                                fallos.append(f"fecha_no_sustentada:{m.group(0)}")
                                break
                        if any(f.startswith("fecha_no_sustentada") for f in fallos):
                            break
        except Exception:
            pass

        # (e) dato sospechoso: citar un ticket en advertencias como ranking
        # ("el que más demoró") sin mencionar la inconsistencia.
        try:
            if sources:
                warned: set = set()

                def _walk_adv(obj) -> None:
                    if isinstance(obj, dict):
                        adv = obj.get("advertencias")
                        if isinstance(adv, list):
                            for a in adv:
                                if isinstance(a, dict) and a.get("ticket"):
                                    warned.add(str(a["ticket"]).upper())
                        casos = obj.get("casos")
                        if isinstance(casos, list):
                            for c in casos:
                                if isinstance(c, dict) and c.get("ticket"):
                                    warned.add(str(c["ticket"]).upper())
                        for v in obj.values():
                            _walk_adv(v)
                    elif isinstance(obj, (list, tuple, set)):
                        for v in obj:
                            _walk_adv(v)

                _walk_adv(sources)
                if warned:
                    sup = _norm(text)
                    if any(k in sup for k in ("mas demoro", "mas tardo", "mas lento",
                                              "mayor tiempo", "maximo", "peor caso",
                                              "que mas se demoro")):
                        menciona = any(k in sup for k in ("inconsist", "advertencia",
                                                          "exclui", "sospechoso",
                                                          "error de registro"))
                        if not menciona:
                            for m in _TICKET_RE.finditer(text):
                                if m.group(0).upper() in warned:
                                    fallos.append(
                                        f"dato_sospechoso:{m.group(0).upper()}")
                                    break
        except Exception:
            pass
    except Exception as exc:
        # El verifier jamás rompe el stream: fallo tolerado y trazable.
        fallos.append(f"verifier_error:{exc}")

    # Dedup preservando orden.
    seen, uniq = set(), []
    for f in fallos:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return {"ok": len(uniq) == 0, "fallos": uniq, "origen": "determinista"}


def verify_routed(answer_text: str, sources, chart, intencion: str,
                  today_hint: str | None = None) -> dict:
    """Dispatcher: Jev si habilitado+configurado, si no determinista. Nunca raisea."""
    try:
        from ..config import settings
    except Exception:
        return verify(answer_text, sources, chart, intencion, today_hint)
    try:
        if settings.JEV_ENABLED and settings.JEV_API_KEY:
            try:
                from . import jev_adapter
                ev = {"sources": sources, "chart": chart, "intencion": intencion}
                if today_hint and (intencion or "") == "hoy":
                    ev["today_hint"] = today_hint
                return jev_adapter.verify_jev(answer, ev)
            except Exception:
                fell = verify(answer, sources, chart, intencion, today_hint)
                fell["origen"] = "determinista-fallback"
                return fell
    except Exception:
        pass
    return verify(answer_text, sources, chart, intencion, today_hint)
