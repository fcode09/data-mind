"""Introspección de la base gueo2021: calibra al agente con datos reales.

Uso:  backend\\.venv\\Scripts\\python backend\\scripts\\introspect.py
Solo ejecuta operaciones de LECTURA (count, distinct, aggregate).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db  # noqa: E402


def top(field: str, coll, limit: int = 15):
    return list(
        coll.aggregate(
            [
                {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": limit},
            ],
            allowDiskUse=True,
        )
    )


def main() -> None:
    db = get_db()
    print(f"DB: {db.name}")
    print(f"Colecciones: {sorted(db.list_collection_names())}")

    inc = db["incidents"]
    total = inc.estimated_document_count()
    print(f"\nincidents.total = {total}")
    if total == 0:
        print("Colección vacía: no hay nada que calibrar.")
        return

    sample = inc.find_one()
    print(f"\nCampos del documento ejemplo:\n{sorted(sample.keys())}")

    for field in [
        "incident_state",
        "incident_priority",
        "category_name",
        "subcategory_name",
        "workgroup_name",
        "operator_workgroup_name",
        "incident_district",
        "shift_name",
        "origin",
        "incident_registered_from",
    ]:
        print(f"\nTop {field}:")
        for row in top(field, inc):
            print(f"  {row['_id']!r}: {row['n']}")

    rango = list(
        inc.aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "min": {"$min": "$incident_creation_date"},
                        "max": {"$max": "$incident_creation_date"},
                    }
                }
            ]
        )
    )
    print(f"\nRango incident_creation_date: {rango}")

    # Flags booleanos
    for flag in ["incident_is_real", "incident_is_duplicated", "incident_irrelevant"]:
        vals = list(
            inc.aggregate(
                [{"$group": {"_id": f"${flag}", "n": {"$sum": 1}}}],
            )
        )
        print(f"{flag}: {vals}")

    # Otras colecciones con conteo rápido
    for name in ["users", "vehicles", "units", "shifts", "workgroups"]:
        try:
            print(f"{name}.total = {db[name].estimated_document_count()}")
        except Exception as exc:  # colección inexistente, etc.
            print(f"{name}: no disponible ({exc})")

    print("\nOK introspección completa.")


if __name__ == "__main__":
    main()
