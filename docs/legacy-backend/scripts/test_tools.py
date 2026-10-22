"""Smoke test de las tools contra el Mongo local (sin LLM)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data import tools  # noqa: E402
from app.db import get_db  # noqa: E402

db = get_db()

c = tools.incidents_count(db)
assert c["data"]["total"] == 30, c
por_estado = {g["clave"]: g["n"] for g in c["data"]["grupos"]}
assert por_estado == {"Recibido": 12, "Resuelto": 10, "En progreso": 8}, por_estado
print("counts por estado OK:", por_estado)

cat = tools.incidents_count(db, group_by="categoria")
assert cat["data"]["total"] == 30, cat
print("counts por categoria OK:", cat["data"]["grupos"])

lst = tools.incidents_list(db, limit=5, state="Resuelto")
assert lst["data"]["mostrados"] == 5, lst
print("list OK, primer ticket:", lst["data"]["incidentes"][0]["incident_ticket_number"])

ticket = lst["data"]["incidentes"][0]["incident_ticket_number"]
det = tools.incident_detail(db, ticket_number=ticket)
assert det["data"]["encontrado"] is True, det
print("detail OK:", ticket)

no = tools.incident_detail(db, ticket_number="NO-EXISTE-999")
assert no["data"]["encontrado"] is False
print("detail no-encontrado OK")

rt = tools.resolution_times(db)
print("resolution_times global:", rt["data"])
rtg = tools.resolution_times(db, group_by="grupo")
print("resolution_times por grupo:", rtg["data"])

ts = tools.timeseries(db, granularity="month")
assert ts["data"]["total"] == 30, ts
print("timeseries OK:", ts["data"]["puntos"])

dv = tools.distinct_values(db, field="estado")
assert set(dv["data"]["valores"]) == {"Recibido", "En progreso", "Resuelto"}, dv
print("distinct OK:", dv["data"]["valores"])

print("\nTODAS LAS TOOLS OK")
