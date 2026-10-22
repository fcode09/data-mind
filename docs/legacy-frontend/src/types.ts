export interface SourceInfo {
  tool: string;
  args: Record<string, unknown>;
  documentos?: number | null;
  filtros?: unknown;
}

export interface ChartData {
  type: 'bar' | 'line';
  title: string;
  labels: string[];
  values: number[];
}

export interface JevVerdict {
  ok: boolean;
  fallos: string[];
}

/**
 * Bloque Jev con compat dual viejo ↔ nuevo (SIN cambiar API base):
 * - Viejo: { origen, intencion, confidence, verificacion: { ok, fallos } }
 * - Nuevo: { origen, ruta, confidence, veredicto_ok, fallos, detalle? }
 * Todos los campos de ruta/veredicto son opcionales para tolerar ambos.
 */
export interface JevInfo {
  origen: string;
  ruta?: string | null;
  intencion?: string | null;
  confidence: number;
  veredicto_ok?: boolean | null;
  ok?: boolean | null;
  fallos?: string[] | null;
  verificacion?: JevVerdict | null;
  detalle?: unknown;
}

/** Evento `progress` del stream (el backend nuevo lo emite; el viejo no). */
export interface ProgressEvent {
  stage: string;
  message?: string | null;
  docs?: number | null;
  label?: string | null;
}

export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceInfo[];
  chart?: ChartData | null;
  /** Bloque meta.jev del backend (nullable: sin Jev → null y no se muestra nada) */
  jev?: JevInfo | null;
  /** Progreso acumulado del stream (`progress` + síntesis desde meta). */
  progress?: ProgressEvent[];
  /** Texto original para reintentar (solo en mensajes de error). */
  retryQuestion?: string;
  /** Aún no llegó `meta`: mostramos timeline + skeletons */
  pendingMeta?: boolean;
  /** Siguen llegando deltas del stream */
  streaming?: boolean;
  /** Marcado cuando el contenido es un error humanizado */
  isError?: boolean;
  /** Respuesta detenida por el usuario (stop o follow-up que aborta). Estado neutro, sin reintentar. */
  interrupted?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    sources?: SourceInfo[];
    chart?: ChartData | null;
    jev?: JevInfo | null;
  }>;
}

/* ---------- Helpers de compat (usados por UI, no tocan la API) ---------- */

/** Ruta/intención normalizada: prefiere `ruta` (nuevo), cae a `intencion` (viejo). */
export function jevRuta(jev: JevInfo | null | undefined): string | null {
  if (!jev) return null;
  const r = (jev.ruta ?? jev.intencion ?? '') as string;
  const t = r.trim();
  return t ? t : null;
}

/** Veredicto OK normalizado: verificacion.ok → veredicto_ok → ok → true. */
export function jevOk(jev: JevInfo | null | undefined): boolean {
  if (!jev) return true;
  if (jev.verificacion != null) return !!jev.verificacion.ok;
  if (jev.veredicto_ok != null) return !!jev.veredicto_ok;
  if (jev.ok != null) return !!jev.ok;
  return true;
}

/** Fallos normalizados: verificacion.fallos → fallos → []. */
export function jevFallos(jev: JevInfo | null | undefined): string[] {
  if (!jev) return [];
  if (jev.verificacion?.fallos?.length) return jev.verificacion.fallos;
  if (Array.isArray(jev.fallos) && jev.fallos.length) return jev.fallos;
  return [];
}

/** Confianza 0..1 → etiqueta humana (nunca % crudo en la UI). */
export function jevConfianzaLabel(conf: number | null | undefined): 'Alta' | 'Media' | 'Baja' {
  const c = typeof conf === 'number' ? (conf <= 1 ? conf : conf / 100) : 0;
  if (c >= 0.8) return 'Alta';
  if (c >= 0.5) return 'Media';
  return 'Baja';
}

/**
 * Reportes base SIN suma doble: las tools se solapan (timeseries total +
 * list parcial cuentan los mismos docs). Usa el máximo, no la suma.
 * Ej: 30 (timeseries) + 20 (list) = 30 base, no 50.
 */
export function baseDocs(sources: SourceInfo[] | null | undefined): number {
  if (!sources || sources.length === 0) return 0;
  return sources.reduce(
    (acc, s) => Math.max(acc, typeof s.documentos === 'number' ? s.documentos : 0),
    0,
  );
}

/** La etiqueta Baja no se muestra al cliente (solo log interno). */
export function shouldShowConfidence(conf: number | null | undefined): boolean {
  return jevConfianzaLabel(conf) !== 'Baja';
}
