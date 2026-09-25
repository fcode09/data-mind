import { useState } from 'react';
import type { JevInfo, SourceInfo } from '../types';
import { baseDocs, jevConfianzaLabel, jevFallos, jevOk, jevRuta, shouldShowConfidence } from '../types';

function humanTool(tool: string): string {
  const t = tool.toLowerCase();
  if (t.includes('incidents_count') || t === 'conteo') return 'conteo de incidentes';
  if (t.includes('resolution')) return 'tiempos de resolución';
  if (t.includes('timeseries') || t.includes('tendencia')) return 'evolución temporal';
  if (t.includes('distinct')) return 'catálogo de valores';
  if (t.includes('detail') || t.includes('ticket')) return 'detalle de tickets';
  return tool.replace(/_/g, ' ');
}

function humanRuta(ruta: string | null): string | null {
  if (!ruta) return null;
  const r = ruta.toLowerCase().trim();
  if (r === 'conteo') return 'conteo';
  if (r === 'ranking_tiempo') return 'tiempos por grupo';
  if (r === 'detalle_ticket') return 'detalle de tickets';
  if (r === 'tendencia') return 'tendencia en el tiempo';
  if (r === 'ambigua') return null;
  if (r === 'fuera_de_alcance') return 'tema fuera de alcance';
  if (r === 'saludo') return null;
  if (r === 'seguimiento') return 'seguimiento';
  if (r === 'ultimo') return 'último reporte';
  if (r === 'seguimiento_entidad') return 'seguimiento';
  if (r === 'hoy') return 'reportes de hoy';
  return ruta.replace(/_/g, ' ');
}

function humanOrigen(origen: string): string {
  const o = origen.toLowerCase();
  if (o.includes('determinista') || o.includes('regla')) return 'reglas';
  if (o.includes('jev')) return 'modelo de clasificación';
  return origen;
}

/** Nunca muestra el código crudo: lo traduce a frase humana. */
function humanFallo(fallo: string): string {
  const f = fallo.toLowerCase().trim();
  if (f.includes('cifra_no_sustentada') || f.includes('cifra')) return 'una cifra no pudo verificarse en la base';
  if (f.includes('ticket_no_sustentado') || f.includes('ticket')) return 'el número de reporte no coincide con la base';
  if (f.includes('dato_sospechoso') || f.includes('sospechoso')) return 'un dato parece inconsistente en origen; verificado con cautela';
  if (f.includes('fecha_no_sustentada') || f.includes('fecha')) return 'una fecha no coincide con los reportes';
  if (f.includes('supuesto_no_declarado') || f.includes('supuesto')) return 'falta declarar un supuesto de la pregunta';
  if (f.includes('verifier_error') || f.includes('verific')) return 'la verificación no pudo completarse';
  if (f.includes('pii')) return 'se omitió información sensible por privacidad';
  return fallo.replace(/_/g, ' ');
}

function confianzaHint(label: 'Alta' | 'Media' | 'Baja'): string {
  if (label === 'Alta') return 'Entendí tu pregunta con claridad';
  if (label === 'Media') return 'Entendí lo general; podría haber matices, revisa el detalle si dudas';
  return 'No estoy muy seguro de haber entendido; revisa cómo lo consulté abajo';
}

/**
 * Panel de evidencia en lenguaje humano.
 * - Frase visible: "Basado en N reportes" (N = máximo, nunca suma entre tools)
 *   + "Entendí: …" (solo rutas con significado) + "Confianza Alta/Media".
 * - La etiqueta Baja JAMÁS se muestra al cliente (solo log interno).
 * - Sin % crudo, sin códigos internos visibles, sin JSON a primera vista.
 * - Lo técnico (nombres de tools, filtros, JSON) vive dentro de <details>.
 * - Chip "Provisional" discreto solo cuando el veredicto es ok=false.
 */
export function SourcesPanel({ sources, jev }: { sources: SourceInfo[]; jev?: JevInfo | null }) {
  const [open, setOpen] = useState(false);
  const hasSources = !!sources && sources.length > 0;
  if (!hasSources && !jev) return null;

  const totalDocs = baseDocs(sources);
  const hasDocCount = totalDocs > 0;
  const panelId = hasSources
    ? `src-${sources.map((s) => s.tool).join('-').slice(0, 24)}`
    : 'src-jev';

  const ruta = jevRuta(jev ?? null);
  const rutaHum = humanRuta(ruta);
  const showConf = jev && shouldShowConfidence(jev.confidence);
  const confLabel = showConf ? jevConfianzaLabel(jev.confidence) : null;
  const ok = jevOk(jev ?? null);
  const fallos = jevFallos(jev ?? null);
  const fallosHuman = fallos.map(humanFallo).join('; ');

  const consultasTxt = hasSources
    ? `${sources.length} consulta${sources.length === 1 ? '' : 's'}`
    : null;

  return (
    <div className="sources">
      <p className="sources-human">
        {hasSources && hasDocCount && (
          <>Basado en <strong>{totalDocs.toLocaleString('es-PE')} reportes</strong></>
        )}
        {hasSources && !hasDocCount && <>Consulté la base de datos ({consultasTxt})</>}
        {jev && rutaHum && (
          <>{hasSources ? ' · ' : ''}Entendí: {rutaHum}</>
        )}
        {jev && confLabel && (
          <>
            {' · '}Confianza{' '}
            <span className="conf-label" title={confianzaHint(confLabel)}>
              {confLabel}
            </span>
          </>
        )}
        {jev && (
          <span className="sources-via" title={`Clasificado vía ${humanOrigen(jev.origen)}`}>
            {' '}· vía {humanOrigen(jev.origen)}
          </span>
        )}
        {!ok && (
          <span
            className="doc-chip chip-provisional"
            title={fallosHuman ? `Respuesta provisional: ${fallosHuman}. Tómala con cautela.` : 'Respuesta provisional: tómala con cautela.'}
          >
            Provisional
          </span>
        )}
      </p>

      {hasSources && (
        <>
          <button
            type="button"
            className="sources-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((v) => !v)}
          >
            <span className={`chev ${open ? 'open' : ''}`} aria-hidden="true">▸</span>
            {open ? 'Ocultar detalle' : 'Ver cómo lo consulté'}
            {hasDocCount && <span className="sources-docs">· {totalDocs.toLocaleString('es-PE')} docs</span>}
          </button>
          <div id={panelId} className={`sources-body ${open ? 'open' : ''}`}>
            <ol>
              {sources.map((s, i) => (
                <li key={i} className="source-item">
                  <span className="tool-chip" title={`Fuente técnica: ${s.tool}`}>
                    {humanTool(s.tool)}
                  </span>
                  {typeof s.documentos === 'number' && (
                    <span className="doc-chip" title="Reportes revisados en esta consulta">
                      {s.documentos.toLocaleString('es-PE')} reportes
                    </span>
                  )}
                  <details className="source-args">
                    <summary>Detalle técnico</summary>
                    <pre>{JSON.stringify({ herramienta: s.tool, filtros: s.filtros ?? null, args: s.args ?? {} }, null, 2)}</pre>
                  </details>
                </li>
              ))}
            </ol>
          </div>
        </>
      )}
    </div>
  );
}
