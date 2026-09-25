import type { ConversationSummary } from '../types';

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  loading: boolean;
  open: boolean;
  theme: 'dark' | 'light';
  backendInfo?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
  onToggleTheme: () => void;
}

/** Saludos y títulos genéricos que no aportan contexto: se muestran como "Consulta general". */
const GENERIC_TITLES = new Set(
  [
    'hola',
    'buenas',
    'buenos dias',
    'buenas tardes',
    'buenas noches',
    'buen dia',
    'hey',
    'hi',
    'hello',
    'consulta',
    'pregunta',
    'test',
    'prueba',
    'sin titulo',
    'nueva conversacion',
    'nueva conversación',
  ].map((s) => s.toLowerCase()),
);

function normalizeTitle(raw: string): string {
  const t = (raw ?? '').trim();
  if (!t) return 'Consulta general';
  // Quita signos y espacios para comparar: "¡Hola!" → "hola"
  const key = t
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[¡!¿?.,;:\-_\s]+$/g, '')
    .replace(/^[¡!¿?.,;:\-_\s]+/g, '')
    .trim();
  if (!key || key.length < 3) return 'Consulta general';
  if (GENERIC_TITLES.has(key)) return 'Consulta general';
  if (/^(hola|buenas)(\s+(tardes|dias|noches|buenas))?$/i.test(key)) return 'Consulta general';
  return t;
}

function isToday(iso: string): boolean {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

function formatMeta(iso: string, today: boolean): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  try {
    if (today) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  } catch {
    return '';
  }
}

export function Sidebar({ conversations, activeId, loading, open, theme, backendInfo, onSelect, onNew, onClose, onToggleTheme }: Props) {
  const today: ConversationSummary[] = [];
  const previous: ConversationSummary[] = [];
  for (const c of conversations) {
    if (isToday(c.created_at)) today.push(c);
    else previous.push(c);
  }

  const renderItem = (c: ConversationSummary) => {
    const title = normalizeTitle(c.title);
    const todayFlag = isToday(c.created_at);
    return (
      <button
        key={c.id}
        type="button"
        className={`convo ${c.id === activeId ? 'active' : ''}`}
        aria-current={c.id === activeId ? 'true' : undefined}
        title={c.title?.trim() ? c.title : title}
        onClick={() => onSelect(c.id)}
      >
        <span className="convo-title">{title}</span>
        <span className="convo-date">{formatMeta(c.created_at, todayFlag)}</span>
      </button>
    );
  };

  return (
    <>
      <div
        className={`scrim ${open ? 'visible' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Historial de conversaciones">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">D</span>
          <div>
            <p className="brand-name">DataMind</p>
            <p className="brand-sub">Gestión municipal · Incidentes</p>
          </div>
        </div>

        <button type="button" className="btn-new" onClick={onNew}>
          + Nueva conversación
        </button>

        <nav className="convo-list" aria-label="Conversaciones">
          {loading && <p className="side-empty">Cargando historial…</p>}
          {!loading && conversations.length === 0 && (
            <p className="side-empty">Aún no hay conversaciones. Escribe tu primera pregunta en el panel principal.</p>
          )}
          {!loading && today.length > 0 && (
            <div className="side-group">
              <p className="side-label">Hoy</p>
              {today.map(renderItem)}
            </div>
          )}
          {!loading && previous.length > 0 && (
            <div className="side-group">
              <p className="side-label">Anteriores</p>
              {previous.map(renderItem)}
            </div>
          )}
        </nav>

        <div className="side-footer">
          <span className="api-dot" title={backendInfo ?? 'Backend esperado en VITE_API_URL'}>
            <i aria-hidden="true" /> API :8001
          </span>
          <button
            type="button"
            className="btn-theme"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
          >
            {theme === 'dark' ? '☀ Tema claro' : '☾ Tema oscuro'}
          </button>
        </div>
      </aside>
    </>
  );
}
