#!/usr/bin/env python3
"""Black-box synthetic-only Docker smoke. Requires a running core Compose stack.

No mocks, SDK packages, model downloads or credentials are needed. This checks
nginx -> Go API -> real MCP -> PostgreSQL through five tenant-bound sessions.
"""
import argparse
import json
import urllib.error
import urllib.request
import uuid


def request(base, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--rows", type=int, default=10000)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    with urllib.request.urlopen(base + "/", timeout=10) as response:
        html = response.read().decode()
        assert 'lang="es"' in html and "Data Mind" in html, "Spanish web build missing"
    assert request(base, "/api/health")["runtime"] == "go"
    try:
        request(base, "/api/status")
    except urllib.error.HTTPError as error:
        assert error.code == 401, "Unauthenticated API must reject access"
    else:
        raise AssertionError("Unauthenticated API request succeeded")
    totals = []
    for tenant in range(1, 6):
        session = request(base, "/api/session", {"tenant_id": tenant})
        token = session["token"]
        body = {
            "turn_id": str(uuid.uuid4()),
            "message": "Total de incidentes por categoría",
            "from_date": "2024-10-01",
            "to_date_exclusive": "2026-10-24",
        }
        turn = request(base, "/api/turns", body, token)
        assert turn["verified"] is True, "Turn was not verified"
        evidence = turn["evidence"]
        assert evidence["effective_scope"]["tenant_id"] == tenant, "Tenant scope leaked"
        assert evidence["query_id"] and evidence["dataset_version"] and evidence["sources"]
        assert evidence["truncated"] is False
        assert evidence["returned_rows"] == len(evidence["rows"])
        count = evidence["total_matching"]
        assert 0 < count < args.rows, "Expected a tenant-scoped synthetic subset"
        assert sum(row["count"] for row in evidence["rows"]) == count
        assert request(base, "/api/turns", body, token) == turn, "Retry changed stored turn"
        totals.append(count)
    assert sum(totals) == args.rows, f"Expected {args.rows} rows, got {sum(totals)}"
    print(json.dumps({"result": "passed", "path": "web -> API -> MCP -> PostgreSQL",
                      "tenant_totals": totals, "total_rows": sum(totals),
                      "verified": ["Spanish UI", "API health", "auth denial", "tenant scope",
                                   "evidence totals", "turn retry idempotency"]}, indent=2))


if __name__ == "__main__":
    main()
