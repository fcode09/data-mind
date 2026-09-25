import type { ChatMsg } from '../types';
import { MiniMarkdown } from '../lib/markdown';
import { ChartView } from './ChartView';
import { SourcesPanel } from './SourcesPanel';
import { baseDocs, jevRuta } from '../types';

function humanStageLabel(stage: string): string {
  const s = stage.toLowerCase();
  if (s.includes('record')) return 'Recordando lo anterior…';
  if (s.includes('entend') || s.includes('ruta') || s.includes('clasif') || s.includes('understand')) return 'Entendí tu pregunta';
  if (s.includes('consult') || s.includes('docs') || s.includes('busc') || s.includes('mongo') || s.includes('tool')) return 'Consulté la base de datos';
  if (s.includes('grafic') || s.includes('chart')) return 'Graficando';
  if (s.includes('redact') || s.includes('escrib') || s.includes('llm') || s.includes('gener')) return 'Redactando respuesta';
  if (s.includes('verific') || s.includes('verify')) return 'Verificando cifras';
  return stage;
}

/**
 * Ruta Jev → etiqueta humana para el timeline.
 * Devuelve null cuando la ruta es técnica o vacía de significado
 * (ambigua, saludo, seguimiento, vacía): en esos casos el paso 1
 * muestra el genérico "Entendiendo tu pregunta…" / "Entendí tu pregunta".
 */
function humanRouteLabel(ruta: string | null): string | null {
  if (!ruta) return null;
  const key = ruta.trim().toLowerCase().replace(/[\s-]+/g, '_');
  // Genéricas: nunca muestran ruta cruda (evita "Entendí: ambigua").
  if (!key || key === 'ambigua' || key === 'ambiguo' || key === 'saludo' || key === 'seguimiento' || key === 'vacia' || key === 'vacía' || key === 'vacio' || key === 'vacío') {
    return null;
  }
  const mapa: Record<string, string> = {
    ultimo: 'último reporte',
    seguimiento_entidad: 'seguimiento',
    hoy: 'reportes de hoy',
    tiempo_transcurrido: 'tiempo transcurrido',
    procedimiento: 'procedimiento',
    conteo: 'conteo',
    ranking_tiempo: 'tiempos por grupo',
    detalle_ticket: 'detalle de tickets',
    tendencia: 'tendencia en el tiempo',
    fuera_de_alcance: 'tema fuera de alcance',
  };
  if (mapa[key]) return mapa[key];
  // Rutas con significado no mapeadas: se humanizan sin mostrar guiones bajos.
  return ruta.trim().replace(/_/g, ' ');
}

function ProgressTimeline({ msg }: { msg: ChatMsg }) {
  const events = msg.progress ?? [];
  const hasMeta = !msg.pendingMeta;
  const docsTotal = baseDocs(msg.sources);
  const ruta = jevRuta(msg.jev ?? null);
  const rutaHumana = humanRouteLabel(ruta);

  // Pasos canónicos: Entendí → Consulté → Graficando/Redactando
  const step1Done = hasMeta || events.some((e) => /entend|ruta|clasif|record/i.test(e.stage));
  const step2Done = hasMeta && (msg.sources?.length ?? 0) > 0;
  const step3Done = !!msg.chart || (!!msg.content && !msg.streaming);
  // Paso 1 sin jerga: solo rutas con significado se muestran traducidas;
  // ambigua / saludo / seguimiento / vacía → genérico.
  const step1Text = rutaHumana
    ? `Entendí: ${rutaHumana}`
    : step1Done ? 'Entendí tu pregunta' : 'Entendiendo tu pregunta…';

  return (
    <div className="timeline" role="status" aria-live="polite">
      {events.filter((e) => /record/i.test(e.stage)).length > 0 && (
        <p className="tl-hint">Recordando lo anterior…</p>
      )}
      <ol className="tl-steps">
        <li className={`tl-step ${step1Done ? 'done' : 'active'}`}>
          <span aria-hidden="true">{step1Done ? '✓' : '◌'}</span>
          {step1Text}
        </li>
        <li className={`tl-step ${step2Done ? 'done' : step1Done ? 'active' : ''}`}>
          <span aria-hidden="true">{step2Done ? '✓' : step1Done ? '◌' : '○'}</span>
          {step2Done
            ? docsTotal > 0
              ? `Basado en ${docsTotal.toLocaleString('es-PE')} reportes`
              : `Consulté la base (${msg.sources?.length ?? 0} consultas)`
            : 'Consultando la base…'}
        </li>
        <li className={`tl-step ${step3Done ? 'done' : hasMeta ? 'active' : ''}`}>
          <span aria-hidden="true">{step3Done ? '✓' : hasMeta ? '◌' : '○'}</span>
          {msg.chart ? 'Graficando resultados…' : 'Redactando respuesta…'}
        </li>
      </ol>
      {/* Eventos crudos del backend nuevo, en humano y sin tecnicismos */}
      {events.filter((e) => !/record/i.test(e.stage)).slice(0, 4).map((e, i) => (
        e.message ? <p key={i} className="tl-hint">{humanStageLabel(e.stage)} — {e.message}</p> : null
      ))}
      <div className="skeleton-wrap" aria-hidden="true">
        <div className="skeleton sk-line" />
        <div className="skeleton sk-line short" />
      </div>
    </div>
  );
}

export function ChatMessage({ msg, onRetry }: { msg: ChatMsg; onRetry?: (question: string) => void }) {
  if (msg.role === 'user') {
    return (
      <div className="msg msg-user msg-enter">
        <div className="bubble bubble-user">
          <MiniMarkdown text={msg.content} />
        </div>
      </div>
    );
  }

  const docsTotal = baseDocs(msg.sources);
  // Estado neutro: respuesta detenida por el usuario. Sobrio, sin rojo ni reintento.
  const interrupted = !!msg.interrupted && !msg.isError;

  return (
    <div className={`msg msg-assistant msg-enter ${msg.isError ? 'msg-error' : ''} ${interrupted ? 'msg-interrupted' : ''}`}>
      <div className={`bubble bubble-assistant ${interrupted ? 'interrupted' : ''}`}>
        {msg.pendingMeta && !interrupted ? (
          <ProgressTimeline msg={msg} />
        ) : (
          <>
            {/* Si hay progreso pero aún no hay texto, conserva el timeline compacto */}
            {msg.streaming && !interrupted && !msg.content && (msg.progress?.length || !msg.chart) && (
              <ProgressTimeline msg={{ ...msg, pendingMeta: false }} />
            )}
            {msg.content ? (
              <div className={msg.streaming && !interrupted ? 'streaming' : undefined}>
                <MiniMarkdown text={msg.content} />
                {msg.streaming && !interrupted && <span className="caret" aria-hidden="true" />}
              </div>
            ) : (
              !msg.isError && !msg.streaming && !interrupted && (
                <p className="thinking" role="status" aria-live="polite">
                  <span className="pulse-dots" aria-hidden="true">
                    <i /><i /><i />
                  </span>
                  Redactando respuesta…
                </p>
              )
            )}
            {msg.isError && (
              <div className="error-block">
                <MiniMarkdown text={msg.content} />
                {msg.retryQuestion && onRetry && (
                  <button
                    type="button"
                    className="btn-ghost btn-retry"
                    onClick={() => onRetry(msg.retryQuestion!)}
                  >
                    ↻ Reintentar
                  </button>
                )}
              </div>
            )}
            {msg.chart && <ChartView chart={msg.chart} docs={docsTotal > 0 ? docsTotal : null} />}
            {(msg.sources?.length || msg.jev) && <SourcesPanel sources={msg.sources ?? []} jev={msg.jev} />}
            {interrupted && (
              <p className="interrupted-note" role="status">
                · respuesta detenida
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
