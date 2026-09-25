import { useState } from 'react';
import type { ChartData } from '../types';

const W = 560;
const H = 250;
const PAD_L = 52;
const PAD_B = 34;
const PAD_T = 14;

const fmt = new Intl.NumberFormat('es-PE');

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * pow;
}

/** Truncado suave: solo si excede 18 caracteres (antes era 10/8). El full siempre va en <title> + tooltip. */
function softLabel(label: string, max = 18): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

/**
 * Gráfico SVG propio (sin dependencias): barras para conteos/rankings,
 * línea para series temporales. Con hover/tooltip, miles, subtítulo y empty-state.
 */
export function ChartView({ chart, docs }: { chart: ChartData; docs?: number | null }) {
  const [hover, setHover] = useState<number | null>(null);

  if (!chart.labels?.length || !chart.values?.length) {
    return (
      <figure className="chart chart-empty" role="img" aria-label={`${chart.title}: sin datos`}>
        <figcaption title={chart.title}>{chart.title}</figcaption>
        <p className="chart-empty-msg">Sin datos para graficar en esta consulta. Prueba con otra pregunta.</p>
      </figure>
    );
  }

  const max = niceMax(Math.max(...chart.values, 0));
  const innerW = W - PAD_L - 12;
  const innerH = H - PAD_T - PAD_B;
  const y = (v: number) => PAD_T + innerH - (v / max) * innerH;

  const ariaSummary = `${chart.title}: ${chart.labels.map((l, i) => `${l} ${fmt.format(chart.values[i])}`).join(', ')}`;
  const hoveredLabel = hover != null ? chart.labels[hover] : null;
  const hoveredValue = hover != null ? chart.values[hover] : null;

  return (
    <figure className="chart" role="img" aria-label={ariaSummary}>
      <figcaption title={chart.title}>{chart.title}</figcaption>
      {typeof docs === 'number' && docs > 0 && (
        <p className="chart-sub">Basado en {fmt.format(docs)} reportes</p>
      )}
      {hoveredLabel != null && hoveredValue != null && (
        <p className="chart-tooltip" role="status">
          <strong>{hoveredLabel}</strong> · {fmt.format(hoveredValue)}
        </p>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" aria-hidden="true">
        {[0, 0.5, 1].map((f) => {
          const v = max * f;
          const yy = y(v);
          return (
            <g key={f}>
              <line x1={PAD_L} y1={yy} x2={W - 8} y2={yy} className="chart-grid" />
              <text x={PAD_L - 6} y={yy + 4} textAnchor="end" className="chart-tick">
                {fmt.format(Number.isInteger(v) ? v : Math.round(v * 10) / 10)}
              </text>
            </g>
          );
        })}

        {chart.type === 'bar' ? (
          <g>
            {chart.labels.map((label, i) => {
              const n = chart.labels.length;
              const slot = innerW / n;
              const bw = Math.min(46, slot * 0.58);
              const x = PAD_L + slot * i + (slot - bw) / 2;
              const active = hover === i;
              return (
                <g
                  key={i}
                  opacity={hover == null || active ? 1 : 0.55}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover((h) => (h === i ? null : h))}
                >
                  <title>{`${label}: ${fmt.format(chart.values[i])}`}</title>
                  <rect
                    x={x}
                    y={y(chart.values[i])}
                    width={bw}
                    height={Math.max(2, PAD_T + innerH - y(chart.values[i]))}
                    rx={5}
                    className={`chart-bar${active ? ' active' : ''}`}
                    style={{ animationDelay: `${Math.min(i * 45, 500)}ms` }}
                  />
                  <text x={x + bw / 2} y={y(chart.values[i]) - 6} textAnchor="middle" className="chart-value">
                    {fmt.format(chart.values[i])}
                  </text>
                  <text x={x + bw / 2} y={H - 8} textAnchor="middle" className="chart-label">
                    {softLabel(label)}
                    <title>{label}</title>
                  </text>
                </g>
              );
            })}
          </g>
        ) : (
          <g>
            <polyline
              points={chart.labels.map((_, i) => `${PAD_L + (innerW * i) / Math.max(chart.labels.length - 1, 1)},${y(chart.values[i])}`).join(' ')}
              className="chart-line"
            />
            {chart.labels.map((label, i) => {
              const cx = PAD_L + (innerW * i) / Math.max(chart.labels.length - 1, 1);
              const every = Math.ceil(chart.labels.length / 8);
              const active = hover === i;
              return (
                <g
                  key={i}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover((h) => (h === i ? null : h))}
                >
                  <title>{`${label}: ${fmt.format(chart.values[i])}`}</title>
                  {/* área de hover generosa */}
                  <circle cx={cx} cy={y(chart.values[i])} r={10} fill="transparent" />
                  <circle
                    cx={cx}
                    cy={y(chart.values[i])}
                    r={active ? 5.5 : 3.5}
                    className={`chart-dot${active ? ' active' : ''}`}
                    style={{ animationDelay: `${Math.min(i * 40, 600)}ms` }}
                  />
                  {active && (
                    <text x={cx} y={y(chart.values[i]) - 12} textAnchor="middle" className="chart-value">
                      {fmt.format(chart.values[i])}
                    </text>
                  )}
                  {i % every === 0 && (
                    <text x={cx} y={H - 8} textAnchor="middle" className="chart-label">
                      {softLabel(label, 16)}
                      <title>{label}</title>
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        )}
      </svg>
    </figure>
  );
}
