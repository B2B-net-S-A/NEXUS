/**
 * Tiny dependency-free sound effects for Kids mode, synthesized with the Web
 * Audio API (no audio assets to ship / no CORS). Callers gate on the
 * `kidsSound` setting; this module only handles synthesis + a lazy AudioContext.
 */

type AudioCtor = typeof AudioContext;

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor: AudioCtor | undefined =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  // Browsers suspend the context until a user gesture; celebrate() is always
  // triggered by a user action, so resume is allowed here.
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** Play a single short note. */
function note(
  audio: AudioContext,
  freq: number,
  startAt: number,
  durationMs: number,
  type: OscillatorType = "triangle",
  peak = 0.16
): void {
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t0 = audio.currentTime + startAt;
  const t1 = t0 + durationMs / 1000;
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(peak, t0 + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, t1);
  osc.connect(gain).connect(audio.destination);
  osc.start(t0);
  osc.stop(t1 + 0.02);
}

/** Cheerful ascending arpeggio — used on a celebration. */
export function playCelebrateSound(): void {
  const audio = getCtx();
  if (!audio) return;
  // C5 – E5 – G5 – C6 (major, happy)
  const seq = [523.25, 659.25, 783.99, 1046.5];
  seq.forEach((f, i) => note(audio, f, i * 0.085, 150, "triangle", 0.16));
}

/** Soft little blip — used when the mascot is "petted". */
export function playPetSound(): void {
  const audio = getCtx();
  if (!audio) return;
  note(audio, 880, 0, 90, "sine", 0.12);
  note(audio, 1318.5, 0.07, 110, "sine", 0.1);
}
