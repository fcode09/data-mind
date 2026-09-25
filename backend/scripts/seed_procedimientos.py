"""Seed BORRADOR de SOP municipales en `data_mind.procedimientos`.

Uso:  backend\\.venv\\Scripts\\python backend\\scripts\\seed_procedimientos.py [--force]
Solo escribe en data_mind (nunca en gueo2021). Idempotente sin --force:
si la colección ya tiene docs, no hace nada.

Cada entrada: 3-5 pasos genéricos municipales con responsable
(Seguridad Ciudadana / Serenazgo) y fuente="borrador-pendiente-validacion".
El retrieval expone ese flag para que el agente diga
"procedimiento borrador por validar" y no lo presente como oficial.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.procedimientos import (  # noqa: E402
    BORRADOR_FUENTE,
    COLL,
    get_procedimiento,
    list_subcategorias,
)

SC = "Seguridad Ciudadana"
SER = "Serenazgo"


def _pasos(*tuplas):
    return [{"n": i + 1, "accion": a, "responsable": r, "plazo": p}
            for i, (a, r, p) in enumerate(tuplas)]


SEED_BORRADOR: list[dict] = [
    {
        "subcategoria": "Persona en estado de ebriedad",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar el reporte y verificar la ubicación del vecino.", SC, "inmediato"),
            ("Desplazar patrulla de Serenazgo para resguardo y verificación en campo.", SER, "15 min"),
            ("Brindar contención básica y coordinar apoyo (salud/PNP) si hay riesgo.", SER, "30 min"),
            ("Registrar la atención y cerrar el reporte en el sistema.", SC, "1 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Persona en estado de abandono",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar el reporte y verificar la ubicación de la persona.", SC, "inmediato"),
            ("Desplazar Serenazgo para verificación y resguardo en el lugar.", SER, "15 min"),
            ("Coordinar con apoyo social/salud para la atención del caso.", SC, "1 h"),
            ("Registrar la atención y derivar el seguimiento al área social.", SC, "2 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Ambulancia-Paramédicos",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar la emergencia y confirmar ubicación y estado del paciente.", SC, "inmediato"),
            ("Coordinar el despacho de ambulancia/paramédicos al punto.", SC, "10 min"),
            ("Asegurar la zona con Serenazgo hasta el arribo del apoyo médico.", SER, "15 min"),
            ("Registrar tiempos de atención y cerrar el reporte.", SC, "1 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Robo a persona",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar el reporte y verificar lugar, hora y descripción.", SC, "inmediato"),
            ("Desplazar patrulla de Serenazgo a la zona para búsqueda y resguardo.", SER, "15 min"),
            ("Coordinar con la PNP para denuncia e intervención según corresponda.", SC, "30 min"),
            ("Registrar la atención y orientar al vecino sobre la denuncia.", SC, "1 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Persona sospechosa",
        "categoria": "Alerta",
        "pasos": _pasos(
            ("Recepcionar el reporte con descripción y ubicación.", SC, "inmediato"),
            ("Desplazar Serenazgo para verificación preventiva sin confrontación.", SER, "15 min"),
            ("Coordinar con la PNP si se confirma riesgo o ilícito.", SC, "30 min"),
            ("Registrar lo observado y cerrar el reporte.", SC, "1 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Ocupación de espacios públicos",
        "categoria": "Alerta",
        "pasos": _pasos(
            ("Verificar el reporte y la zona ocupada.", SC, "30 min"),
            ("Desplazar Serenazgo para diálogo y ordenamiento del espacio.", SER, "1 h"),
            ("Coordinar con fiscalización/desarrollo urbano si persiste la ocupación.", SC, "2 h"),
            ("Registrar la intervención y programar seguimiento.", SC, "mismo día"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Abuso de autoridad",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar el reporte con datos de lugar, hora y personas involucradas.", SC, "inmediato"),
            ("Registrar el caso y derivarlo al órgano competente para evaluación.", SC, "1 h"),
            ("Brindar orientación al vecino sobre el canal formal de denuncia.", SC, "mismo día"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Tala ilegal",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Recepcionar el reporte de actividad contra recursos naturales con ubicación.", SC, "30 min"),
            ("Desplazar Serenazgo para verificación en campo y resguardo de la zona.", SER, "1 h"),
            ("Coordinar con el área ambiental/fiscalización para constatación.", SC, "mismo día"),
            ("Registrar evidencia y derivar el caso al procedimiento ambiental oficial.", SC, "24 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
    {
        "subcategoria": "Basura acumulada",
        "categoria": "Emergencia",
        "pasos": _pasos(
            ("Verificar el punto de acumulación reportado.", SC, "1 h"),
            ("Coordinar con limpieza pública el recojo del punto.", SC, "mismo día"),
            ("Desplazar Serenazgo para verificación del recojo si se requiere.", SER, "24 h"),
            ("Registrar la atención y cerrar el reporte.", SC, "24 h"),
        ),
        "fuente": BORRADOR_FUENTE,
    },
]


def main() -> None:
    force = "--force" in sys.argv[1:]
    from app.api.conversations import get_store_db
    db = get_store_db()
    now = datetime.now(timezone.utc)
    if force:
        db[COLL].delete_many({})
        print("colección limpiada (--force).")
    n = db[COLL].estimated_document_count()
    if n > 0 and not force:
        print(f"ya hay {n} SOP, no se siembra (usa --force para resembrar).")
        print("subcategorías:", list_subcategorias())
        return
    docs = []
    for d in SEED_BORRADOR:
        dd = dict(d)
        dd["updated_at"] = now
        docs.append(dd)
    res = db[COLL].insert_many(docs)
    print(f"seed OK: {len(res.inserted_ids)} SOP borrador.")
    print("subcategorías:", list_subcategorias())
    # demo retrieval tolerante
    for q in ["ebriedad", "TALA ILEGAL", "basura", "ambulancia paramedicos"]:
        hit = get_procedimiento(q)
        print(f"  demo {q!r} -> {(hit or {}).get('subcategoria')} "
              f"[fuente={(hit or {}).get('fuente')}]")


if __name__ == "__main__":
    main()
