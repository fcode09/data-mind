import type { createModel } from "vosk-browser";
export type VoiceState = "off" | "loading" | "listening" | "recording";
export function isWakePhrase(text: string): boolean {
  return /\bhola\s+asistente\b/.test(
    text
      .toLocaleLowerCase("es")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, ""),
  );
}
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2),
    view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++)
      view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const value = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}
/** Wake recognition and idle audio never leave this browser. Only explicitly started question audio is uploaded by the caller. */
export class LocalVoice {
  private stream?: MediaStream;
  private context?: AudioContext;
  private source?: MediaStreamAudioSourceNode;
  private processor?: ScriptProcessorNode;
  private mute?: GainNode;
  private model?: Awaited<ReturnType<typeof createModel>>;
  private recognizer?: InstanceType<
    Awaited<ReturnType<typeof createModel>>["KaldiRecognizer"]
  >;
  private frames: Float32Array[] = [];
  private recording = false;
  private muted = false;
  private elapsed = 0;
  private quiet = 0;
  private heard = false;
  private generation = 0;
  constructor(
    private state: (state: VoiceState) => void,
    private ready: (wav: Blob) => void,
    private fail: (error: unknown) => void,
  ) {}
  async enable() {
    const generation = ++this.generation;
    this.state("loading");
    try {
      if (!window.isSecureContext)
        throw new Error("El micrófono requiere HTTPS o localhost.");
      this.context = new AudioContext();
      await this.context.resume();
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      if (generation !== this.generation) {
        this.stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const { createModel: loadModel } = await import("vosk-browser");
      this.model = await loadModel("/models/vosk-model-small-es-0.42.tar.gz");
      if (generation !== this.generation) {
        this.model.terminate();
        return;
      }
      this.recognizer = new this.model.KaldiRecognizer(this.context.sampleRate);
      this.recognizer.on("result", (message) => {
        if (
          "result" in message &&
          "text" in message.result &&
          !this.muted &&
          !this.recording &&
          isWakePhrase(message.result.text)
        )
          this.startQuestion();
      });
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      this.mute = this.context.createGain();
      this.mute.gain.value = 0;
      this.processor.onaudioprocess = (event) => {
        if (this.muted) return;
        if (!this.recording) {
          this.recognizer?.acceptWaveform(event.inputBuffer);
          return;
        }
        const frame = new Float32Array(event.inputBuffer.getChannelData(0));
        this.frames.push(frame);
        const seconds = frame.length / event.inputBuffer.sampleRate;
        this.elapsed += seconds;
        const rms = Math.sqrt(
          frame.reduce((sum, sample) => sum + sample * sample, 0) /
            frame.length,
        );
        if (rms > 0.015) {
          this.heard = true;
          this.quiet = 0;
        } else this.quiet += seconds;
        if (
          this.elapsed >= 20 ||
          (this.heard && this.quiet >= 1.4 && this.elapsed > 1)
        )
          this.finishQuestion();
      };
      this.source.connect(this.processor);
      this.processor.connect(this.mute);
      this.mute.connect(this.context.destination);
      this.state("listening");
    } catch (error) {
      this.disable();
      this.fail(error);
    }
  }
  startQuestion() {
    if (!this.context || this.recording || this.muted) return;
    this.frames = [];
    this.elapsed = 0;
    this.quiet = 0;
    this.heard = false;
    this.recording = true;
    this.state("recording");
  }
  finishQuestion() {
    if (!this.recording) return;
    this.recording = false;
    this.state("listening");
    const frames = this.frames;
    this.frames = [];
    if (!this.heard) return;
    const samples = new Float32Array(
      frames.reduce((sum, frame) => sum + frame.length, 0),
    );
    let offset = 0;
    frames.forEach((frame) => {
      samples.set(frame, offset);
      offset += frame.length;
    });
    this.ready(encodeWav(samples, this.context?.sampleRate || 48000));
  }
  setMuted(value: boolean) {
    this.muted = value;
    if (value) {
      this.frames = [];
      this.recording = false;
    }
  }
  disable() {
    ++this.generation;
    this.recording = false;
    this.frames = [];
    this.processor?.disconnect();
    this.source?.disconnect();
    this.mute?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.recognizer?.remove();
    this.model?.terminate();
    void this.context?.close();
    this.context = undefined;
    this.state("off");
  }
}
