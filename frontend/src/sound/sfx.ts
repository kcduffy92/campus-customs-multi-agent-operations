// Original Web Audio synth placeholders, ported from output/desk_tickets.html (Problem 6).
// Muted by default; one sound at a time; nothing plays until the user turns sound on.

export type SoundId =
  | "mario.intro" | "mario.coin" | "mario.fanfare"
  | "crash.woah" | "crash.crate" | "crash.fruit"
  | "spyro.gem" | "spyro.approval" | "spyro.treasure"
  | "ryu.hadouken" | "ryu.impact" | "ryu.victory"
  | "sonic.ring" | "sonic.warn" | "sonic.complete";

type Synth = (c: AudioContext, out: AudioNode, t: number) => void;

interface ToneOpts { f: number; f2?: number; d?: number; type?: OscillatorType; g?: number; a?: number }
interface NoiseOpts { d?: number; g?: number; type?: BiquadFilterType; f?: number; f2?: number; q?: number }

function tone(c: AudioContext, out: AudioNode, t: number, o: ToneOpts) {
  const osc = c.createOscillator();
  const v = c.createGain();
  const d = o.d ?? 0.1;
  osc.type = o.type ?? "square";
  osc.frequency.setValueAtTime(o.f, t);
  if (o.f2) osc.frequency.exponentialRampToValueAtTime(o.f2, t + d);
  v.gain.setValueAtTime(0.0001, t);
  v.gain.exponentialRampToValueAtTime(o.g ?? 0.5, t + (o.a ?? 0.005));
  v.gain.exponentialRampToValueAtTime(0.0001, t + d);
  osc.connect(v);
  v.connect(out);
  osc.start(t);
  osc.stop(t + d + 0.03);
}

function noise(c: AudioContext, out: AudioNode, t: number, o: NoiseOpts) {
  const d = o.d ?? 0.15;
  const len = Math.ceil(c.sampleRate * d);
  const buf = c.createBuffer(1, len, c.sampleRate);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
  const src = c.createBufferSource();
  const fl = c.createBiquadFilter();
  const v = c.createGain();
  src.buffer = buf;
  fl.type = o.type ?? "bandpass";
  fl.Q.value = o.q ?? 1;
  fl.frequency.setValueAtTime(o.f ?? 1500, t);
  if (o.f2) fl.frequency.exponentialRampToValueAtTime(o.f2, t + d);
  v.gain.setValueAtTime(o.g ?? 0.5, t);
  v.gain.exponentialRampToValueAtTime(0.0001, t + d);
  src.connect(fl);
  fl.connect(v);
  v.connect(out);
  src.start(t);
  src.stop(t + d + 0.03);
}

const seq = (c: AudioContext, out: AudioNode, t: number, fs: number[], step: number, o: Omit<ToneOpts, "f">) =>
  fs.forEach((f, i) => tone(c, out, t + i * step, { ...o, f, d: o.d ?? step * 1.1 }));

const SYNTH: Record<SoundId, Synth> = {
  "mario.intro": (c, o, t) => { seq(c, o, t, [523, 659, 784, 1047], 0.08, { g: 0.35 }); tone(c, o, t + 0.34, { f: 1319, d: 0.28, g: 0.3 }); },
  "mario.coin": (c, o, t) => { tone(c, o, t, { f: 880, d: 0.06, g: 0.4 }); tone(c, o, t + 0.06, { f: 1175, d: 0.32, g: 0.35 }); },
  "mario.fanfare": (c, o, t) => { seq(c, o, t, [392, 523, 659, 784, 659, 784], 0.1, { g: 0.3 }); tone(c, o, t + 0.6, { f: 1047, d: 0.35, type: "triangle", g: 0.45 }); },
  "crash.woah": (c, o, t) => { tone(c, o, t, { f: 560, f2: 190, d: 0.5, type: "sawtooth", g: 0.28, a: 0.03 }); tone(c, o, t, { f: 280, f2: 95, d: 0.5, type: "triangle", g: 0.3, a: 0.03 }); },
  "crash.crate": (c, o, t) => { noise(c, o, t, { d: 0.14, f: 1800, q: 0.8, g: 0.8 }); tone(c, o, t, { f: 140, f2: 60, d: 0.16, type: "sine", g: 0.6 }); noise(c, o, t + 0.07, { d: 0.1, f: 3200, q: 1.5, g: 0.4 }); },
  "crash.fruit": (c, o, t) => { tone(c, o, t, { f: 600, f2: 1200, d: 0.1, type: "sine", g: 0.45 }); tone(c, o, t + 0.1, { f: 1500, d: 0.18, type: "sine", g: 0.35 }); },
  "spyro.gem": (c, o, t) => seq(c, o, t, [1319, 1661, 1976, 2637], 0.05, { type: "triangle", d: 0.25, g: 0.35 }),
  "spyro.approval": (c, o, t) => seq(c, o, t, [440, 330, 440, 330], 0.11, { g: 0.3 }),
  "spyro.treasure": (c, o, t) => { [523, 659, 784].forEach((f) => tone(c, o, t, { f, d: 0.5, type: "triangle", g: 0.25 })); seq(c, o, t + 0.2, [2093, 2637, 3136], 0.06, { type: "sine", d: 0.2, g: 0.15 }); },
  "ryu.hadouken": (c, o, t) => { noise(c, o, t, { d: 0.4, f: 300, f2: 2400, q: 2, g: 0.6 }); tone(c, o, t, { f: 120, f2: 55, d: 0.4, type: "sawtooth", g: 0.22, a: 0.02 }); },
  "ryu.impact": (c, o, t) => { noise(c, o, t, { d: 0.12, type: "lowpass", f: 1200, g: 0.9 }); tone(c, o, t, { f: 95, f2: 38, d: 0.2, type: "sine", g: 0.8 }); },
  "ryu.victory": (c, o, t) => { seq(c, o, t, [587, 740, 880, 1175], 0.09, { g: 0.3 }); tone(c, o, t + 0.38, { f: 1175, d: 0.3, g: 0.28 }); },
  "sonic.ring": (c, o, t) => { tone(c, o, t, { f: 1568, d: 0.07, g: 0.3 }); tone(c, o, t + 0.07, { f: 2093, d: 0.35, g: 0.25 }); },
  "sonic.warn": (c, o, t) => seq(c, o, t, [1000, 1000, 1000], 0.08, { d: 0.05, g: 0.3 }),
  "sonic.complete": (c, o, t) => seq(c, o, t, [1047, 1319, 1568], 0.07, { type: "sine", d: 0.18, g: 0.4 }),
};

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let bus: GainNode | null = null;
let muted = true;

export const isMuted = () => muted;

export function setMuted(value: boolean) {
  muted = value;
  if (muted) stop();
  else ensure();
}

function ensure(): AudioContext | null {
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!ctx) {
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.16;
    master.connect(ctx.destination);
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function stop() {
  if (bus && ctx) {
    const b = bus;
    const t = ctx.currentTime;
    b.gain.cancelScheduledValues(t);
    b.gain.setValueAtTime(b.gain.value, t);
    b.gain.linearRampToValueAtTime(0, t + 0.02);
    setTimeout(() => b.disconnect(), 60);
  }
  bus = null;
}

/** Play a sound if sound is on. Returns false when muted or unavailable. */
export function play(id: SoundId): boolean {
  if (muted) return false;
  const c = ensure();
  if (!c || !master) return false;
  stop();
  bus = c.createGain();
  bus.connect(master);
  SYNTH[id](c, bus, c.currentTime + 0.01);
  return true;
}
