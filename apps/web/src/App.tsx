import { useEffect, useRef, useState } from "react";
import {
  addDay,
  columnLabel,
  displayValue,
  evidenceList,
  request,
  type Evidence,
  type Turn,
} from "./api";
import { LocalVoice, type VoiceState } from "./voice";
const number = new Intl.NumberFormat("es-PE");
type Item = { question: string; turn: Turn };
function EvidenceCard({ evidence }: { evidence: Evidence }) {
  const columns = [
    ...new Set(evidence.rows.flatMap((row) => Object.keys(row))),
  ];
  const metric = columns.find((column) =>
    ["count", "total", "incidents", "value"].includes(column),
  );
  const max = metric
    ? Math.max(1, ...evidence.rows.map((row) => Number(row[metric]) || 0))
    : 1;
  return (
    <details className="evidence" open>
      <summary>
        Evidencia verificable{" "}
        <span>{number.format(evidence.total_matching)} coincidencias</span>
      </summary>
      <div className="evidence-meta">
        <span>Consulta {evidence.query_id.slice(0, 12)}</span>
        <span>Versión {evidence.dataset_version}</span>
        <span>
          {evidence.aggregation_method === "exact"
            ? "Cálculo exacto"
            : evidence.aggregation_method === "full_text"
              ? "Búsqueda de texto"
              : evidence.aggregation_method}
        </span>
      </div>
      {metric && evidence.rows.length > 0 && evidence.rows.length <= 12 && (
        <div className="chart" aria-label="Distribución de resultados">
          {evidence.rows.map((row, index) => (
            <div className="bar-row" key={index}>
              <span>
                {displayValue(
                  row[columns.find((column) => column !== metric) || metric],
                )}
              </span>
              <div>
                <i
                  style={{
                    width: `${Math.max(1, (Number(row[metric]) / max) * 100)}%`,
                  }}
                />
              </div>
              <strong>{number.format(Number(row[metric]))}</strong>
            </div>
          ))}
        </div>
      )}
      {evidence.rows.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{columnLabel(column)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evidence.rows.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => (
                    <td key={column}>{displayValue(row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No hay filas para este alcance.</p>
      )}
      {evidence.truncated && (
        <p className="notice">
          Vista limitada a {evidence.returned_rows} filas. El total corresponde
          al conjunto completo.
        </p>
      )}
      {evidence.warnings?.map((warning) => (
        <p className="notice" key={warning}>
          {warning}
        </p>
      ))}
      <p className="muted">
        Datos hasta:{" "}
        {evidence.event_watermark
          ? new Date(evidence.event_watermark).toLocaleString("es-PE")
          : "Sin fecha disponible"}{" "}
        · Consultado: {new Date(evidence.as_of).toLocaleString("es-PE")}
      </p>
      {evidence.sources?.length > 0 && (
        <p className="muted">Fuentes: {evidence.sources.join(" · ")}</p>
      )}
    </details>
  );
}
export default function App() {
  const [token, setToken] = useState(""),
    [tenant, setTenant] = useState(1),
    [from, setFrom] = useState("2024-10-23"),
    [to, setTo] = useState("2026-10-22");
  const [status, setStatus] = useState<Record<string, unknown>>({}),
    [message, setMessage] = useState(""),
    [items, setItems] = useState<Item[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [phase, setPhase] = useState(""),
    [voiceState, setVoiceState] = useState<VoiceState>("off"),
    [feedback, setFeedback] = useState<Record<string, string>>({});
  const abort = useRef<AbortController | null>(null),
    currentTurn = useRef(""),
    voice = useRef<LocalVoice | null>(null),
    audio = useRef<HTMLAudioElement | null>(null),
    audioUrl = useRef(""),
    submitRef = useRef<(text: string) => void>(() => {}),
    tokenRef = useRef(""),
    busyRef = useRef(false),
    mounted = useRef(true);
  tokenRef.current = token;
  busyRef.current = busy;
  const stopAudio = () => {
    audio.current?.pause();
    audio.current = null;
    if (audioUrl.current) {
      URL.revokeObjectURL(audioUrl.current);
      audioUrl.current = "";
    }
  };
  const cancel = () => {
    busyRef.current = false;
    currentTurn.current = "";
    abort.current?.abort();
    stopAudio();
    setBusy(false);
    setPhase("Consulta cancelada.");
    voice.current?.setMuted(false);
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      abort.current?.abort();
      voice.current?.disable();
      stopAudio();
    };
  }, []);
  useEffect(() => {
    let active = true;
    setToken("");
    setItems([]);
    setStatus({});
    cancel();
    request<{ token: string }>("/api/session", "", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenant }),
    })
      .then((result) => {
        if (active) setToken(result.token);
      })
      .catch((reason) => {
        if (active) setError(String(reason.message));
      });
    return () => {
      active = false;
    };
  }, [tenant]);
  useEffect(() => {
    if (!token || !from || !to || from > to) return;
    const controller = new AbortController();
    request<Record<string, unknown>>(
      `/api/status?from_date=${from}&to_date_exclusive=${addDay(to)}`,
      token,
      { signal: controller.signal },
    )
      .then(setStatus)
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(reason.message);
      });
    return () => controller.abort();
  }, [token, from, to]);
  async function speak(turn: Turn, signal: AbortSignal) {
    if (!voice.current || voiceState === "off" || !turn.verified) return;
    try {
      const response = await fetch("/api/voice/speak", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ turn_id: turn.turn_id }),
        signal,
      });
      if (!response.ok)
        throw new Error(
          "La respuesta está lista; el servicio de voz no está disponible.",
        );
      const blob = await response.blob();
      if (currentTurn.current !== turn.turn_id || signal.aborted) return;
      stopAudio();
      audioUrl.current = URL.createObjectURL(blob);
      audio.current = new Audio(audioUrl.current);
      voice.current?.setMuted(true);
      audio.current.onended = () => {
        voice.current?.setMuted(false);
        setPhase(
          "Di «Hola asistente», espera a ver «Escuchando» y luego pregunta.",
        );
      };
      await audio.current.play();
    } catch (reason) {
      if (!signal.aborted) {
        setPhase(
          reason instanceof Error
            ? reason.message
            : "No se pudo reproducir el audio.",
        );
        voice.current?.setMuted(false);
      }
    }
  }
  async function submit(text: string) {
    if (!text.trim() || !token || busyRef.current) return;
    if (!from || !to || from > to) {
      setError("La fecha inicial debe ser anterior a la final.");
      return;
    }
    stopAudio();
    const turnId = crypto.randomUUID();
    currentTurn.current = turnId;
    const controller = new AbortController();
    abort.current = controller;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    setPhase("Déjame consultar…");
    voice.current?.setMuted(true);
    // This fixed local phrase acknowledges the submitted question, never a factual result.
    if (voiceState !== "off") {
      const acknowledgement = new Audio("/models/consulting.wav");
      audio.current = acknowledgement;
      acknowledgement.onerror = () => {
        if (currentTurn.current === turnId)
          setPhase("Déjame consultar… (aviso de voz local no disponible)");
      };
      void acknowledgement.play().catch(() => {
        if (currentTurn.current === turnId)
          setPhase("Déjame consultar… (audio bloqueado; continúa en texto)");
      });
    }
    try {
      const turn = await request<Turn>("/api/turns", token, {
        method: "POST",
        body: JSON.stringify({
          message: text,
          from_date: from,
          to_date_exclusive: addDay(to),
          turn_id: turnId,
        }),
        signal: controller.signal,
      });
      if (currentTurn.current !== turnId) return;
      if (!turn.verified && !turn.clarification)
        throw new Error(
          "No se pudo verificar esta respuesta. Intenta una consulta más concreta.",
        );
      setItems((previous) => [...previous, { question: text, turn }]);
      stopAudio();
      setPhase(
        turn.clarification
          ? "Necesito precisar tu consulta."
          : "Respuesta verificada.",
      );
      if (turn.verified && !turn.clarification)
        await speak(turn, controller.signal);
    } catch (reason) {
      if (
        currentTurn.current === turnId &&
        !(reason instanceof DOMException && reason.name === "AbortError")
      )
        setError(
          reason instanceof Error
            ? reason.message
            : "No se pudo completar la consulta.",
        );
    } finally {
      if (currentTurn.current === turnId) {
        setBusy(false);
        busyRef.current = false;
        if (!audio.current || audio.current.paused)
          voice.current?.setMuted(false);
      }
    }
  }
  submitRef.current = (text) => {
    void submit(text);
  };
  async function enableVoice() {
    if (voice.current) {
      stopAudio();
      voice.current.disable();
      voice.current = null;
      return;
    }
    setError("");
    voice.current = new LocalVoice(
      (state) => {
        if (mounted.current) setVoiceState(state);
      },
      async (wav) => {
        if (busyRef.current) return;
        const controller = new AbortController();
        abort.current = controller;
        setPhase("Transcribiendo tu pregunta…");
        setBusy(true);
        busyRef.current = true;
        voice.current?.setMuted(true);
        try {
          const form = new FormData();
          form.append("file", wav, "question.wav");
          const result = await request<{ text: string }>(
            "/api/voice/transcribe",
            tokenRef.current,
            { method: "POST", body: form, signal: controller.signal },
          );
          if (!controller.signal.aborted) {
            setBusy(false);
            busyRef.current = false;
            if (result.text.trim()) {
              submitRef.current(result.text);
            } else {
              voice.current?.setMuted(false);
              setPhase(
                "No detecté una pregunta. Di «Hola asistente» e inténtalo otra vez.",
              );
            }
          }
        } catch (reason) {
          if (abort.current !== controller) return;
          if (!controller.signal.aborted)
            setError(
              reason instanceof Error
                ? reason.message
                : "No se pudo transcribir.",
            );
          setBusy(false);
          busyRef.current = false;
          voice.current?.setMuted(false);
        }
      },
      (reason) => {
        setError(
          reason instanceof Error
            ? reason.message
            : "No se pudo activar el micrófono.",
        );
        voice.current = null;
      },
    );
    await voice.current.enable();
  }
  async function rate(turnId: string, rating: number) {
    try {
      await request("/api/feedback", token, {
        method: "POST",
        body: JSON.stringify({ turn_id: turnId, rating, note: "" }),
      });
      setFeedback((previous) => ({
        ...previous,
        [turnId]:
          "Gracias. Tu evaluación se revisará antes de aplicar mejoras.",
      }));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "No se pudo guardar tu evaluación.",
      );
    }
  }
  const rowCount =
    status.row_count ??
    status.total_rows ??
    status.total_incidents ??
    status.total_matching;
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="#">
          <span className="brand-mark">
            d<span>m</span>
          </span>
          <div>
            data mind<small>INTELIGENCIA CON EVIDENCIA</small>
          </div>
        </a>
        <div className="workspace-label">ESPACIO DE TRABAJO</div>
        <div className="nav-active">
          <span>◈</span> Asistente de datos <span className="nav-dot" />
        </div>
        <div className="scope">
          <h2>Alcance de la consulta</h2>
          <label>
            Organización ficticia
            <select
              value={tenant}
              onChange={(event) => setTenant(Number(event.target.value))}
              disabled={busy}
            >
              {[1, 2, 3, 4, 5].map((value) => (
                <option value={value} key={value}>
                  Organización {value.toString().padStart(2, "0")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Desde
            <input
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Hasta, incluido
            <input
              type="date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              disabled={busy}
            />
          </label>
          <p className="muted">
            Zona horaria: America/Lima.
            <br />
            El rango se aplica a cada consulta.
          </p>
        </div>
        <div className="privacy">
          <span>◇</span>
          <strong>Datos ficticios, control real</strong>
          <p>
            Las respuestas incluyen fuentes y alcance. No conectamos datos de
            producción.
          </p>
        </div>
        <div className="sidebar-footer">
          <i className={token ? "online" : "offline"} />{" "}
          {token ? "Sesión de demostración" : "Conectando con el servicio"}
        </div>
      </aside>
      <main>
        <header>
          <div>
            <span className="eyebrow">TU INFORMACIÓN, MÁS CLARA</span>
            <h1>Hablemos de tus datos.</h1>
            <p>Pregunta, explora y decide con evidencia verificable.</p>
          </div>
          <span className="demo-badge">DEMO · DATOS SINTÉTICOS</span>
        </header>
        <section className="stats" aria-label="Estado del conjunto de datos">
          <div>
            <span>Registros disponibles</span>
            <strong>
              {typeof rowCount === "number" ? number.format(rowCount) : "—"}
            </strong>
            <small>Según el estado del conjunto</small>
          </div>
          <div>
            <span>Organización activa</span>
            <strong>0{tenant}</strong>
            <small>Alcance separado por organización</small>
          </div>
          <div>
            <span>Periodo seleccionado</span>
            <strong className="date-metric">
              {from} → {to}
            </strong>
            <small>Fechas de la demo, no el reloj real</small>
          </div>
        </section>
        <section className="conversation" aria-label="Conversación">
          <div className="section-head">
            <h2>
              <span>✦</span> Asistente
            </h2>
            <span className="secure-label">
              Respuestas verificadas antes del audio
            </span>
          </div>
          <div className="messages" aria-live="polite">
            {items.length === 0 ? (
              <div className="welcome">
                <div className="orb">✦</div>
                <h3>De una pregunta a una respuesta clara.</h3>
                <p>
                  Consulta tendencias, cantidades o procedimientos.
                  <br />
                  Los números se calculan sobre los datos, no se inventan.
                </p>
                <div className="suggestions">
                  {[
                    "¿Cuántos incidentes hay por categoría?",
                    "Muéstrame la tendencia de incidentes",
                    "¿Cuál es el tiempo de resolución?",
                  ].map((text) => (
                    <button
                      key={text}
                      disabled={!token || busy}
                      onClick={() => void submit(text)}
                    >
                      {text} <span>↗</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              items.map(({ question, turn }) => (
                <article className="turn" key={turn.turn_id}>
                  <div className="question">{question}</div>
                  <div className="answer">
                    <span className="answer-icon">✦</span>
                    <div>
                      <span className="verified">
                        {turn.clarification
                          ? "PRECISA TU CONSULTA"
                          : "✓ RESPUESTA VERIFICADA"}
                      </span>
                      <p>{turn.answer}</p>
                      {!turn.clarification &&
                        evidenceList(turn.evidence).map((evidence) => (
                          <EvidenceCard
                            key={evidence.query_id}
                            evidence={evidence}
                          />
                        ))}
                      {turn.verified && (
                        <div className="feedback">
                          {feedback[turn.turn_id] || (
                            <>
                              <span>¿Te resultó útil?</span>
                              <button
                                onClick={() => void rate(turn.turn_id, 1)}
                              >
                                Sí
                              </button>
                              <button
                                onClick={() => void rate(turn.turn_id, -1)}
                              >
                                No
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
              <button aria-label="Cerrar aviso" onClick={() => setError("")}>
                ×
              </button>
            </div>
          )}
          <div className="composer">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit(message);
              }}
            >
              <textarea
                aria-label="Tu pregunta"
                placeholder="Escribe tu pregunta sobre los datos…"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                disabled={!token || busy}
                rows={2}
              />
              <div className="composer-controls">
                <button
                  type="button"
                  className={`voice-button ${voiceState !== "off" ? "active" : ""}`}
                  onClick={() => void enableVoice()}
                  disabled={!token}
                >
                  {voiceState === "loading"
                    ? "Cargando modelo local…"
                    : voiceState === "off"
                      ? "◉ Activar voz"
                      : "◉ Desactivar micrófono"}
                </button>
                {voiceState === "listening" && (
                  <button
                    type="button"
                    onClick={() => voice.current?.startQuestion()}
                    disabled={busy}
                  >
                    Hablar ahora
                  </button>
                )}
                {voiceState === "recording" && (
                  <button
                    type="button"
                    onClick={() => voice.current?.finishQuestion()}
                  >
                    Terminar pregunta
                  </button>
                )}
                {busy || audio.current ? (
                  <button type="button" className="stop" onClick={cancel}>
                    Detener
                  </button>
                ) : (
                  <button
                    type="submit"
                    className="send"
                    disabled={!message.trim() || !token}
                  >
                    Consultar ↗
                  </button>
                )}
              </div>
            </form>
            <p className="composer-note">
              {voiceState === "recording"
                ? "● Escuchando tu pregunta. Se enviará al servidor local al terminar."
                : voiceState === "listening" && !busy
                  ? "Di «Hola asistente», espera a ver «Escuchando» y luego pregunta. El audio en espera no sale de tu navegador."
                  : phase ||
                    "La voz requiere tu permiso. Puedes usar texto en cualquier momento."}
            </p>
          </div>
        </section>
        <footer>
          Data Mind · Procesamiento local configurable · Revisa siempre el
          alcance y las fuentes
        </footer>
      </main>
    </div>
  );
}
