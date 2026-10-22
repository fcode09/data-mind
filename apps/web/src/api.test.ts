import { describe, it, expect } from "vitest";
import { addDay, displayValue, evidenceList } from "./api";
import { encodeWav, isWakePhrase } from "./voice";
describe("date scope", () => {
  it("converts inclusive end to exclusive next day at month and leap boundaries", () => {
    expect(addDay("2024-02-29")).toBe("2024-03-01");
    expect(addDay("2026-12-31")).toBe("2027-01-01");
  });
});
describe("safe display", () => {
  it("handles missing and object values", () => {
    expect(displayValue(null)).toBe("—");
    expect(displayValue({ count: 2 })).toBe('{"count":2}');
  });
  it("preserves an evidence list", () => {
    expect(evidenceList([])).toEqual([]);
  });
});
describe("local voice helpers", () => {
  it("requires the whole Spanish wake phrase", () => {
    expect(isWakePhrase("Hola asistente")).toBe(true);
    expect(isWakePhrase("hola asistente consulta")).toBe(true);
    expect(isWakePhrase("asistente")).toBe(false);
    expect(isWakePhrase("caracola asistente")).toBe(false);
  });
  it("encodes mono PCM WAV with bounded samples", async () => {
    const result = encodeWav(new Float32Array([-2, 0, 2]), 16000);
    const view = new DataView(await result.arrayBuffer());
    expect(result.type).toBe("audio/wav");
    expect(view.byteLength).toBe(50);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getInt16(44, true)).toBe(-32768);
    expect(view.getInt16(48, true)).toBe(32767);
  });
});
