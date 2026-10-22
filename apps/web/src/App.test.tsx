// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";
const voiceHarness = vi.hoisted(() => ({
  ready: null as null | ((wav: Blob) => Promise<void>),
  setMuted: vi.fn(),
}));
vi.mock("./voice", () => ({
  LocalVoice: class {
    constructor(
      private state: (value: string) => void,
      ready: (wav: Blob) => Promise<void>,
    ) {
      voiceHarness.ready = ready;
    }
    async enable() {
      this.state("listening");
    }
    disable() {
      this.state("off");
    }
    setMuted = voiceHarness.setMuted;
  },
}));

const evidence = {
  query_id: "test-query",
  dataset_version: "seed-42",
  effective_scope: {
    tenant_id: 1,
    from_date: "2024-10-23",
    to_date_exclusive: "2026-10-23",
    timezone: "America/Lima",
  },
  as_of: "2026-10-22T15:00:00Z",
  total_matching: 120,
  returned_rows: 2,
  truncated: false,
  rows: [
    { category: "red", count: 80 },
    { category: "hardware", count: 40 },
  ],
  aggregation_method: "exact",
  sources: ["synthetic"],
  warnings: [],
};
let verified = true;
let clarification = false;
beforeEach(() => {
  verified = true;
  clarification = false;
  voiceHarness.setMuted.mockClear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      let body: unknown = {};
      if (input === "/api/session") body = { token: "unit-test", tenant_id: 1 };
      else if (input.startsWith("/api/status")) body = { row_count: 1000000 };
      else if (input === "/api/turns") {
        const request = JSON.parse(String(init.body));
        body = {
          turn_id: request.turn_id,
          answer: "Hay 120 incidentes.",
          verified,
          clarification,
          evidence: clarification ? null : evidence,
        };
      } else if (input === "/api/feedback") body = { ok: true };
      return { ok: true, json: async () => body };
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("Spanish conversational client", () => {
  it("renders verified evidence and sends explicitly requested feedback", async () => {
    render(<App />);
    await screen.findByText("1,000,000");
    fireEvent.click(screen.getByRole("button", { name: /Cuántos incidentes/ }));
    await screen.findByText("Hay 120 incidentes.");
    expect(screen.getByText("120 coincidencias")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sí" }));
    await screen.findByText(
      "Gracias. Tu evaluación se revisará antes de aplicar mejoras.",
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/feedback",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer unit-test" }),
      }),
    );
  });
  it("does not render an unverified answer or request speech", async () => {
    verified = false;
    render(<App />);
    await screen.findByText("1,000,000");
    fireEvent.click(screen.getByRole("button", { name: /Cuántos incidentes/ }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Hay 120 incidentes.")).toBeNull();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some((call) => call[0] === "/api/voice/speak"),
    ).toBe(false);
  });
  it("shows explicit clarification without presenting verified evidence or audio", async () => {
    verified = false;
    clarification = true;
    render(<App />);
    await screen.findByText("1,000,000");
    fireEvent.click(screen.getByRole("button", { name: /Cuántos incidentes/ }));
    await screen.findByText("PRECISA TU CONSULTA");
    expect(screen.queryByText("120 coincidencias")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some((call) => call[0] === "/api/voice/speak"),
    ).toBe(false);
  });
  it("resumes wake listening after an empty transcription", async () => {
    render(<App />);
    await screen.findByText("1,000,000");
    fireEvent.click(screen.getByRole("button", { name: /Activar voz/ }));
    await screen.findByRole("button", { name: /Desactivar micrófono/ });
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ text: "  " }),
    } as Response);
    await voiceHarness.ready!(
      new Blob(["fake-test-audio"], { type: "audio/wav" }),
    );
    await waitFor(() =>
      expect(voiceHarness.setMuted).toHaveBeenLastCalledWith(false),
    );
    expect(
      vi.mocked(fetch).mock.calls.some((call) => call[0] === "/api/turns"),
    ).toBe(false);
  });
  it("does not request microphone permission on load", async () => {
    const getUserMedia = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    render(<App />);
    await screen.findByText("1,000,000");
    expect(getUserMedia).not.toHaveBeenCalled();
  });
  it("sends an exclusive upper date boundary and no client-selected tenant in turns", async () => {
    render(<App />);
    await screen.findByText("1,000,000");
    fireEvent.click(screen.getByRole("button", { name: /Cuántos incidentes/ }));
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some((call) => call[0] === "/api/turns"),
      ).toBe(true),
    );
    const call = vi
      .mocked(fetch)
      .mock.calls.find((call) => call[0] === "/api/turns")!;
    const body = JSON.parse(String(call[1]?.body));
    expect(body.to_date_exclusive).toBe("2026-10-23");
    expect(body.tenant_id).toBeUndefined();
  });
});
