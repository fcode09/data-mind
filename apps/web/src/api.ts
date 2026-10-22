export interface Evidence {
  query_id: string;
  dataset_version: string;
  effective_scope: {
    tenant_id: number;
    from_date: string;
    to_date_exclusive: string;
    timezone: string;
  };
  as_of: string;
  event_watermark?: string | null;
  total_matching: number;
  returned_rows: number;
  truncated: boolean;
  rows: Record<string, unknown>[];
  aggregation_method: string;
  sources: string[];
  warnings: string[];
}
export interface Turn {
  turn_id: string;
  answer: string;
  evidence: Evidence | Evidence[] | null;
  clarification?: boolean;
  verified: boolean;
}
export async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {
      /* Non-JSON failures remain sanitized. */
    }
    throw new Error(detail || `La solicitud falló (${response.status}).`);
  }
  return response.json();
}
export function evidenceList(evidence: Turn["evidence"]): Evidence[] {
  return evidence === null
    ? []
    : Array.isArray(evidence)
      ? evidence
      : [evidence];
}
export function displayValue(value: unknown): string {
  return value === null || value === undefined
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
}
export function addDay(isoDate: string): string {
  const date = new Date(`${isoDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Backend identifiers stay stable; visible headings are localized. */
export function columnLabel(column: string): string {
  const labels: Record<string, string> = {
    label: "Grupo",
    count: "Cantidad",
    category: "Categoría",
    status: "Estado",
    sector: "Sector",
    day: "Día",
    id: "Identificador",
    synthetic_id: "Código ficticio",
    event_at: "Fecha del incidente",
    resolved_at: "Fecha de resolución",
    description: "Descripción",
    matched_count: "Coincidencias",
    resolved_count: "Resueltos",
    mean_seconds: "Promedio (s)",
    median_seconds: "Mediana (s)",
    min_seconds: "Mínimo (s)",
    max_seconds: "Máximo (s)",
    title: "Título",
    content: "Contenido",
    version: "Versión",
    section: "Sección",
    effective_at: "Vigente desde",
    score: "Relevancia",
    first_event: "Primer evento",
    last_event: "Último evento",
    total: "Total",
    value: "Valor",
  };
  return labels[column] || column.replaceAll("_", " ");
}
