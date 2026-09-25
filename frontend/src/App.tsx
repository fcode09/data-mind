import { useCallback, useEffect, useRef, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatMessage } from './components/ChatMessage';
import { Composer } from './components/Composer';
import { askStream, getConversation, getHealth, listConversations } from './lib/api';
import type { ChatMsg, ConversationSummary, ProgressEvent } from './types';
import { baseDocs } from './types';

/** 4 preguntas doradas: cubren las tools con gráfico (barras y línea). */
const GOLDEN_QUESTIONS = [
  '¿Cuántos incidentes hay por estado?',
  '¿Cuáles son las categorías con más incidentes?',
  '¿Cuál es la mediana del tiempo de resolución por grupo?',
  '¿Cómo evolucionaron los incidentes por mes?',
];

const LS_CONVO = 'dm-conversation-id';
const LS_THEME = 'dm-theme';

function uid(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    localStorage.getItem(LS_THEME) === 'dark' ? 'dark' : 'light',
  );
  const [conversationId, setConversationId] = useState<string | null>(() =>
    localStorage.getItem(LS_CONVO),
  );
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [histLoading, setHistLoading] = useState(true);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [convoLoading, setConvoLoading] = useState(false);
  const [sideOpen, setSideOpen] = useState(false);
  const [backendInfo, setBackendInfo] = useState<string>('Backend esperado en VITE_API_URL');

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  const refreshHistory = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch {
      /* el historial es secundario: el chat sigue usable */
    }
  }, []);

  useEffect(() => {
    (async () => {
      setHistLoading(true);
      await refreshHistory();
      setHistLoading(false);
      const h = await getHealth();
      if (h) {
        const parts = [
          h.router_version ? `router ${h.router_version}` : null,
          typeof h.incidents === 'number' ? `${h.incidents} reportes` : null,
          h.model ?? null,
        ].filter(Boolean);
        setBackendInfo(parts.length ? `Backend: ${parts.join(' · ')}` : 'Backend conectado');
      }
    })();
  }, [refreshHistory]);

  const openConversation = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setConvoLoading(true);
    setSideOpen(false);
    try {
      const detail = await getConversation(id);
      setConversationId(id);
      localStorage.setItem(LS_CONVO, id);
      setMessages(
        detail.messages.map((m) => ({
          id: uid(),
          role: m.role as 'user' | 'assistant',
          content: m.content,
          sources: m.sources,
          chart: m.chart ?? null,
          jev: m.jev ?? null,
        })),
      );
    } catch (err) {
      setMessages([
        {
          id: uid(),
          role: 'assistant',
          content: err instanceof Error ? err.message : 'No pude abrir la conversación.',
          isError: true,
        },
      ]);
    } finally {
      setConvoLoading(false);
    }
  }, []);

  // Restaura la conversación activa al cargar
  useEffect(() => {
    if (conversationId) void openConversation(conversationId);
    // solo al montar
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Autoscroll que respeta al lector: solo pega abajo si ya estaba cerca
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  };

  const patchAssistant = useCallback((id: string, patch: Partial<ChatMsg>, append?: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id
          ? { ...m, ...patch, content: append !== undefined ? m.content + append : (patch.content ?? m.content) }
          : m,
      ),
    );
  }, []);

  const appendProgress = useCallback((id: string, evt: ProgressEvent) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id ? { ...m, pendingMeta: false, progress: [...(m.progress ?? []), evt] } : m,
      ),
    );
  }, []);

  const send = useCallback(
    (text: string) => {
      const q = text.trim();
      if (!q || convoLoading) return;
      // Follow-up: no bloqueamos por `busy`; interrumpimos el stream anterior.
      // La burbuja abortada queda marcada como neutra (sin rojo ni reintento).
      abortRef.current?.abort();
      setMessages((prev) =>
        prev.map((m) => (m.streaming ? { ...m, streaming: false, pendingMeta: false, interrupted: true } : m)),
      );
      const ctl = new AbortController();
      abortRef.current = ctl;

      const hasHistory = !!conversationId || messages.length > 0;
      const initialProgress: ProgressEvent[] = hasHistory
        ? [{ stage: 'recordando', message: 'Recordando lo anterior…' }]
        : [{ stage: 'entendiendo', message: null }];

      const assistantId = uid();
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: 'user', content: q },
        { id: assistantId, role: 'assistant', content: '', pendingMeta: true, streaming: true, progress: initialProgress },
      ]);
      stickRef.current = true;
      setBusy(true);

      void askStream(
        q,
        conversationId,
        {
          onProgress: (p) => appendProgress(assistantId, { stage: p.stage, message: p.message ?? null, docs: p.docs ?? null, label: p.label ?? null }),
          onMeta: (meta) => {
            setConversationId(meta.conversation_id);
            localStorage.setItem(LS_CONVO, meta.conversation_id);
            const docsTotal = baseDocs(meta.sources);
            // Síntesis para timeline cuando el backend viejo no manda `progress`:
            // dejamos huella de "consulté" para que el timeline muestre N docs.
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      pendingMeta: false,
                      streaming: true,
                      sources: meta.sources,
                      chart: meta.chart,
                      jev: meta.jev ?? null,
                      progress: [
                        ...(m.progress ?? []),
                        { stage: 'consultando', message: null, docs: docsTotal },
                        ...(meta.chart ? [{ stage: 'graficando', message: null } as ProgressEvent] : []),
                      ],
                    }
                  : m,
              ),
            );
          },
          onDelta: (t) => patchAssistant(assistantId, { pendingMeta: false }, t),
          onDone: () => {
            patchAssistant(assistantId, { streaming: false, pendingMeta: false });
            setBusy(false);
            void refreshHistory();
          },
          onError: (message) => {
            patchAssistant(assistantId, {
              content: message,
              isError: true,
              streaming: false,
              pendingMeta: false,
              retryQuestion: q,
            });
            setBusy(false);
          },
        },
        ctl.signal,
      );
    },
    [convoLoading, conversationId, messages.length, patchAssistant, appendProgress, refreshHistory],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setBusy(false);
    // Marca visible y neutra: contenido parcial + "· respuesta detenida".
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false, pendingMeta: false, interrupted: true } : m)),
    );
  }, []);

  const newConversation = useCallback(() => {
    abortRef.current?.abort();
    setBusy(false);
    setConversationId(null);
    localStorage.removeItem(LS_CONVO);
    setMessages([]);
    setSideOpen(false);
  }, []);

  const streaming = messages.some((m) => m.streaming);
  void busy; // `busy` no bloquea el composer; se conserva para estado interno.

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        loading={histLoading}
        open={sideOpen}
        theme={theme}
        backendInfo={backendInfo}
        onSelect={(id) => void openConversation(id)}
        onNew={newConversation}
        onClose={() => setSideOpen(false)}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      />

      <main className="main">
        <header className="topbar">
          <button
            type="button"
            className="btn-icon"
            aria-label="Abrir historial"
            onClick={() => setSideOpen(true)}
          >
            ☰
          </button>
          <div className="topbar-brand">
            <span className="topbar-mark" aria-hidden="true">D</span>
            <div className="topbar-title">
              <strong>DataMind · Gestión municipal</strong>
              <span>Consulta de incidentes con evidencia verificada</span>
            </div>
          </div>
          <div className="topbar-status">
            <span className="status-pill" title={backendInfo}>
              <i aria-hidden="true" />
              <span className="status-text">API conectada</span>
            </span>
          </div>
        </header>

        <div ref={scrollRef} className="scroll" onScroll={handleScroll} role="log" aria-live="polite" aria-label="Conversación">
          {convoLoading && (
            <p className="thinking center" role="status">
              <span className="pulse-dots" aria-hidden="true"><i /><i /><i /></span>
              Abriendo conversación…
            </p>
          )}

          {!convoLoading && messages.length === 0 && (
            <section className="hero">
              <p className="hero-eyebrow">Gestión municipal · Incidentes</p>
              <h1>Consulta los incidentes con datos verificados</h1>
              <p className="hero-sub">
                Escribe tu pregunta en lenguaje natural. Cada respuesta incluye sus{' '}
                <strong>fuentes</strong> y, cuando aplica, un <strong>gráfico</strong>.
              </p>
              <div className="chips">
                {GOLDEN_QUESTIONS.map((q) => (
                  <button key={q} type="button" className="chip" onClick={() => send(q)} disabled={convoLoading}>
                    {q}
                  </button>
                ))}
              </div>
            </section>
          )}

          {messages.map((m) => (
            <ChatMessage key={m.id} msg={m} onRetry={send} />
          ))}
        </div>

        <footer className="footer">
          <Composer disabled={convoLoading} streaming={streaming} onSend={send} onStop={stop} />
          <p className="hint">Enter envía · Shift+Enter salta de línea · Las cifras siempre vienen de la base de datos.</p>
        </footer>
      </main>
    </div>
  );
}
