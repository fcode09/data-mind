import { useRef, useState } from 'react';

interface Props {
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

/**
 * Composer nunca se bloquea por `busy`: permite follow-up mientras llega
 * la respuesta. Cuando hay streaming muestra Detener + Enviar a la vez.
 */
export function Composer({ disabled, streaming, onSend, onStop }: Props) {
  const [value, setValue] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    setValue('');
    onSend(text);
    requestAnimationFrame(() => taRef.current?.focus());
  };

  return (
    <div className="composer-wrap">
      <label className="sr-only" htmlFor="composer">Escribe tu pregunta sobre incidentes</label>
      <textarea
        id="composer"
        ref={taRef}
        rows={1}
        value={value}
        placeholder={streaming ? 'Escribe un seguimiento… (puedes interrumpir la respuesta)' : 'Describe tu consulta… ej. ¿Cuántos incidentes hay por estado este mes?'}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onInput={(e) => {
          const el = e.currentTarget;
          el.style.height = 'auto';
          el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {streaming && (
        <button type="button" className="btn-send btn-stop" onClick={onStop} aria-label="Detener respuesta">
          ■ Detener
        </button>
      )}
      <button
        type="button"
        className="btn-send"
        onClick={submit}
        disabled={!value.trim() || disabled}
        aria-label="Enviar pregunta"
        title={streaming ? 'Enviar seguimiento (interrumpe la respuesta actual)' : 'Enviar pregunta'}
      >
        <span aria-hidden="true">↑</span> Enviar
      </button>
    </div>
  );
}
