import type { ReactNode } from 'react';

/**
 * Markdown ligero y seguro (sin dependencias, sin dangerouslySetInnerHTML):
 * - **negrita**, `código`, [links](url), párrafos, listas `-`/`*`/`1.`
 * - headers `#`/`##`/`###`, citas `>`, tablas `| |`, bloques ``` code
 * React escapa el texto por defecto, así que el HTML inyectado es inerte.
 */

function safeHref(href: string): string | null {
  const t = href.trim();
  if (/^(https?:\/\/|\/|#|mailto:)/i.test(t) && !/^javascript:/i.test(t)) return t;
  return null;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g);
  return parts.map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const href = safeHref(link[2]);
      if (!href) return <span key={key}>{link[1]}</span>;
      return (
        <a key={key} href={href} target="_blank" rel="noreferrer">
          {link[1]}
        </a>
      );
    }
    return <span key={key}>{part}</span>;
  });
}

function isTableSeparator(line: string): boolean {
  const cells = line.split('|').map((c) => c.trim()).filter(Boolean);
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

function splitRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').map((c) => c.trim());
}

function renderTable(lines: string[], key: string) {
  const header = splitRow(lines[0]);
  const body = lines.slice(2).map(splitRow);
  return (
    <div key={key} className="md-table-wrap">
      <table className="md-table">
        <thead>
          <tr>
            {header.map((h, i) => (
              <th key={i}>{renderInline(h || '—', `${key}-h${i}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r}>
              {header.map((_, c) => (
                <td key={c}>{renderInline(row[c] ?? '', `${key}-r${r}c${c}`)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MiniMarkdown({ text }: { text: string }) {
  // 1) Extrae bloques de código ``` para que no se toquen
  const codeBlocks: string[] = [];
  const withoutCode = text.replace(/```[\w-]*\n([\s\S]*?)(```|$)/g, (_m, code: string) => {
    codeBlocks.push(code.replace(/\n$/, ''));
    return `\n\n@@CODEBLOCK-${codeBlocks.length - 1}@@\n\n`;
  });

  const blocks = withoutCode.split(/\n{2,}/);
  const nodes: ReactNode[] = [];

  blocks.forEach((block, b) => {
    const key = `b${b}`;
    const trimmed = block.trim();
    if (!trimmed) return;

    const codePh = /^@@CODEBLOCK-(\d+)@@$/.exec(trimmed);
    if (codePh) {
      const code = codeBlocks[Number(codePh[1])] ?? '';
      nodes.push(
        <pre key={key} className="md-codeblock">
          <code>{code}</code>
        </pre>,
      );
      return;
    }

    const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return;

    // Header # ## ###
    const h = /^(#{1,3})\s+(.+)$/.exec(lines[0]);
    if (h && lines.length === 1) {
      const level = h[1].length;
      const body = h[2];
      if (level === 1) nodes.push(<h3 key={key} className="md-h">{renderInline(body, key)}</h3>);
      else nodes.push(<h4 key={key} className="md-h">{renderInline(body, key)}</h4>);
      return;
    }

    // Cita >
    if (lines.length > 0 && lines.every((l) => l.startsWith('>'))) {
      const inner = lines.map((l) => l.replace(/^>\s?/, '')).join('\n');
      nodes.push(
        <blockquote key={key} className="md-quote">
          {inner.split('\n').map((ln, i, arr) => (
            <span key={i}>
              {renderInline(ln, `${key}-q${i}`)}
              {i < arr.length - 1 && <br />}
            </span>
          ))}
        </blockquote>,
      );
      return;
    }

    // Tabla | |
    if (lines.length >= 2 && lines[0].includes('|') && isTableSeparator(lines[1])) {
      nodes.push(renderTable(lines, key));
      return;
    }

    // Lista
    const isList = lines.length > 0 && lines.every((l) => /^([-*]|\d+[.)])\s+/.test(l));
    if (isList) {
      const ordered = /^\d+[.)]\s+/.test(lines[0]);
      const items = lines.map((l) => l.replace(/^([-*]|\d+[.)])\s+/, ''));
      if (ordered) {
        nodes.push(
          <ol key={key}>
            {items.map((it, i) => (
              <li key={i}>{renderInline(it, `${key}-${i}`)}</li>
            ))}
          </ol>,
        );
      } else {
        nodes.push(
          <ul key={key}>
            {items.map((it, i) => (
              <li key={i}>{renderInline(it, `${key}-${i}`)}</li>
            ))}
          </ul>,
        );
      }
      return;
    }

    // Párrafos con salto simple conservado
    const joined = lines.join('\n');
    if (!joined) return;
    const inner = joined.split('\n').map((ln, i, arr) => (
      <span key={i}>
        {renderInline(ln, `b${b}l${i}`)}
        {i < arr.length - 1 && <br />}
      </span>
    ));
    nodes.push(<p key={key}>{inner}</p>);
  });

  return <>{nodes}</>;
}
