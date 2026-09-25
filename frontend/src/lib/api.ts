import type { ChartData, ConversationDetail, ConversationSummary, JevInfo, ProgressEvent, SourceInfo } from '../types';

/**
 * Base del backend. Si VITE_API_URL está vacío usamos rutas relativas,
 * que en `dev` pasan por el proxy de Vite hacia http://127.0.0.1:8001.
 */
const RAW_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8001';
export const API_BASE = RAW_BASE.replace(/\/$/, '');

const url = (path: string) => (API_BASE ? `${API_BASE}${path}` : path);

export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(url('/conversations'));
  if (!res.ok) throw new Error(`No pude cargar el historial (HTTP ${res.status}).`);
  const data = await res.json();
  return data.conversations ?? [];
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const res = await fetch(url(`/conversations/${encodeURIComponent(id)}`));
  if (res.status === 404) throw new Error('Esa conversación ya no existe.');
  if (!res.ok) throw new Error(`No pude abrir la conversación (HTTP ${res.status}).`);
  return res.json();
}

export interface BackendHealth {
  status: string;
  incidents?: number;
  model?: string;
  jev_enabled?: boolean;
  router_version?: string;
}

export async function getHealth(): Promise<BackendHealth | null> {
  try {
    const res = await fetch(url('/health'));
    if (!res.ok) return null;
    return (await res.json()) as BackendHealth;
  } catch {
    return null;
  }
}

export interface AskMeta {
  conversation_id: string;
  sources: SourceInfo[];
  chart: ChartData | null;
  jev: JevInfo | null;
}

/** Progreso en lenguaje de UI (lo que el backend mande en `progress`). */
export type AskProgress = ProgressEvent & { [k: string]: unknown };

export interface AskHandlers {
  onMeta: (meta: AskMeta) => void;
  onDelta: (text: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
  /** Opcional: el backend viejo no lo emite; si no existe se sintetiza en App. */
  onProgress?: (p: AskProgress) => void;
}

/**
 * POST /ask con lectura manual del stream SSE (EventSource no soporta POST).
 * Parsea eventos `meta` → N × `progress` → N × `delta` → `done` | `error`.
 * Los eventos desconocidos se ignoran para compat hacia adelante.
 */
export async function askStream(
  question: string,
  conversationId: string | null,
  handlers: AskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  const clientTz = (() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Lima';
    } catch {
      return 'America/Lima';
    }
  })();
  try {
    res = await fetch(url('/ask'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ question, conversation_id: conversationId, client_tz: clientTz }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') return;
    handlers.onError('No pude conectar con el backend. Revisa que esté corriendo en http://127.0.0.1:8001.');
    return;
  }

  if (!res.ok || !res.body) {
    let detail = '';
    try {
      const data = await res.json();
      detail = typeof data?.detail === 'string' ? data.detail : '';
    } catch {
      /* cuerpo no-JSON */
    }
    handlers.onError(humanizeHttpError(res.status, detail));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (rawEvent: string) => {
    // rawEvent: "event: delta\ndata: {...}"
    let name = '';
    const dataLines: string[] = [];
    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event:')) name = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!name) return;
    const data = dataLines.join('\n');
    try {
      if (name === 'meta') handlers.onMeta(JSON.parse(data));
      else if (name === 'delta') handlers.onDelta(JSON.parse(data).text ?? '');
      else if (name === 'progress') {
        if (!handlers.onProgress) return;
        let raw: Record<string, unknown> = {};
        try {
          raw = JSON.parse(data || '{}');
        } catch {
          return;
        }
        const stage = String(
          (raw.stage as string) ?? (raw.estado as string) ?? (raw.step as string) ?? 'avance',
        );
        const message =
          (raw.message as string) ?? (raw.mensaje as string) ?? (raw.text as string) ?? null;
        const docsRaw = (raw.docs as unknown) ?? (raw.documentos as unknown) ?? null;
        const docs = typeof docsRaw === 'number' ? docsRaw : null;
        const label = (raw.label as string) ?? null;
        handlers.onProgress({ stage, message, docs, label, ...raw });
      } else if (name === 'done') handlers.onDone();
      else if (name === 'error') handlers.onError(humanizeBackendError(JSON.parse(data).error ?? ''));
      // desconocidos (heartbeat, ping, log, etc.): se ignoran sin romper el stream
    } catch {
      // fragmento JSON corrupto: se ignora sin romper el stream
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        dispatch(raw);
      }
    }
    if (buffer.trim()) dispatch(buffer);
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      handlers.onError('Se cortó la conexión mientras llegaba la respuesta. Intenta de nuevo.');
    }
  } finally {
    reader.releaseLock();
  }
}

function humanizeHttpError(status: number, detail: string): string {
  if (status === 400) return 'Tu pregunta llegó vacía. Escribe algo e intenta de nuevo.';
  if (status === 500 && (detail.includes('LLM_API_KEY') || detail.includes('GROQ_API_KEY')))
    return 'Al backend le falta la clave LLM_API_KEY. Avísale a quien lo opere (backend/.env, proveedor OpenCode Go).';
  if (status === 503 || detail.includes('Mongo'))
    return 'La base de datos no está respondiendo ahora mismo. Intenta en unos minutos.';
  return detail
    ? `El backend devolvió un error: ${detail}`
    : `El backend devolvió HTTP ${status}. Intenta de nuevo.`;
}

/** Traduce errores técnicos del evento `error` a mensaje humano, sin ocultar el detalle. */
export function humanizeBackendError(raw: string): string {
  if (!raw) return 'Ocurrió un error consultando los datos. Intenta de nuevo.';
  if (raw.includes('LLM_API_KEY') || raw.includes('GROQ_API_KEY')) return 'Al backend le falta la clave LLM_API_KEY. Avísale a quien lo opere (backend/.env, proveedor OpenCode Go).';
  if (/mongo|timed out|ServerSelection/i.test(raw))
    return 'La base de datos no está respondiendo ahora mismo. Intenta en unos minutos.';
  if (/groq|model|rate limit|429/i.test(raw))
    return 'El modelo de lenguaje no respondió a tiempo. Intenta de nuevo en unos segundos.';
  return `Ocurrió un error consultando los datos: ${raw}`;
}
