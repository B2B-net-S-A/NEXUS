import { useThemeStore } from "@/store/theme";
import { playCelebrateSound } from "@/lib/kidsSound";
import { prefersReducedMotion } from "@/lib/prefers-reduced-motion";

/**
 * Light gamification for the "Kids / game world" mode.
 *
 * `celebrate()` fires a (themed) confetti burst, an optional sound, and notifies
 * the mascot. It is a hard no-op unless Kids mode is on, so call sites stay
 * unconditional — the professional theme never sees an effect. Respects
 * `prefers-reduced-motion` (skips confetti; mascot/sound still acknowledge).
 */

/** Window event the mascot listens to so it can react (bounce) to a win. */
export const CELEBRATE_EVENT = "nexus:celebrate";

/** Flavor of the celebration — drives confetti shapes/colors + mascot bubble. */
export type CelebrateVariant = "default" | "hired" | "offer" | "levelup" | "welcome";

interface CelebrateOptions {
  /** Optional decorative line shown by the mascot's speech bubble. */
  message?: string;
  /** Visual/audio flavor. */
  variant?: CelebrateVariant;
  /** Minor event — a small puff, no sound (keeps things "nie nachalne"). */
  small?: boolean;
}

const PALETTE = ["#ec4899", "#a855f7", "#38bdf8", "#facc15", "#34d399", "#fb7185"];

type Confetti = typeof import("canvas-confetti");

function fireConfetti(confetti: Confetti, variant: CelebrateVariant, small: boolean): void {
  const origin = { y: 0.7 };

  if (small) {
    confetti({ particleCount: 40, spread: 55, startVelocity: 35, origin, colors: PALETTE, disableForReducedMotion: true });
    return;
  }

  if (variant === "offer") {
    // Hearts raining for an accepted offer.
    const heart = confetti.shapeFromText ? confetti.shapeFromText({ text: "❤️", scalar: 2 }) : undefined;
    confetti({
      particleCount: 60,
      spread: 90,
      startVelocity: 45,
      origin,
      scalar: 2,
      colors: ["#fb7185", "#ec4899", "#f472b6"],
      ...(heart ? { shapes: [heart] } : {}),
      disableForReducedMotion: true,
    });
    return;
  }

  if (variant === "hired" || variant === "levelup") {
    // Golden stars shooting up for the big wins.
    const base = { origin, colors: ["#facc15", "#fde047", "#f59e0b", "#a855f7", "#34d399"], disableForReducedMotion: true };
    confetti({ ...base, particleCount: 80, spread: 70, startVelocity: 60, shapes: ["star"], scalar: 1.2 });
    confetti({ ...base, particleCount: 60, spread: 120, startVelocity: 35, shapes: ["star", "circle"] });
    return;
  }

  // default / welcome — a joyful multi-burst.
  const big = variant === "welcome";
  const fire = (ratio: number, opts: Record<string, unknown>) =>
    confetti({ origin, colors: PALETTE, disableForReducedMotion: true, ...opts, particleCount: Math.floor((big ? 260 : 200) * ratio) });
  fire(0.25, { spread: 26, startVelocity: 55 });
  fire(0.2, { spread: 60 });
  fire(0.35, { spread: 100, decay: 0.91, scalar: 0.9 });
  fire(0.1, { spread: 120, startVelocity: 25, decay: 0.92, scalar: 1.2 });
  fire(0.1, { spread: 120, startVelocity: 45 });
}

/**
 * Sustained confetti storm for the Konami "party mode". No-op unless Kids mode
 * is on; skipped under reduced motion. Runs ~5s of side-cannon + center bursts.
 */
export function celebrateParty(): void {
  if (typeof window === "undefined") return;
  if (!useThemeStore.getState().kidsMode) return;
  if (prefersReducedMotion()) return;

  void import("canvas-confetti")
    .then(({ default: confetti }) => {
      let elapsed = 0;
      const stepMs = 220;
      const durationMs = 5000;
      const id = window.setInterval(() => {
        confetti({ particleCount: 7, angle: 60, spread: 75, startVelocity: 55, origin: { x: 0, y: 0.95 }, colors: PALETTE, disableForReducedMotion: true });
        confetti({ particleCount: 7, angle: 120, spread: 75, startVelocity: 55, origin: { x: 1, y: 0.95 }, colors: PALETTE, disableForReducedMotion: true });
        confetti({ particleCount: 10, spread: 110, startVelocity: 45, origin: { x: Math.random(), y: 0.55 }, colors: PALETTE, shapes: ["star", "circle"], disableForReducedMotion: true });
        elapsed += stepMs;
        if (elapsed >= durationMs) window.clearInterval(id);
      }, stepMs);
    })
    .catch(() => {
      /* decorative — ignore */
    });
}

export function celebrate(options: CelebrateOptions = {}): void {
  if (typeof window === "undefined") return;
  const { kidsMode, kidsSound } = useThemeStore.getState();
  if (!kidsMode) return; // celebrate only in the game world

  const variant = options.variant ?? "default";

  // Let the mascot react even when motion is reduced (it stays static via CSS).
  window.dispatchEvent(
    new CustomEvent(CELEBRATE_EVENT, { detail: { message: options.message, variant } })
  );

  if (kidsSound && !options.small) {
    try {
      playCelebrateSound();
    } catch {
      /* audio is optional */
    }
  }

  if (prefersReducedMotion()) return;

  // canvas-confetti touches `window`/`document`, so load it lazily on the client.
  void import("canvas-confetti")
    .then(({ default: confetti }) => fireConfetti(confetti, variant, options.small === true))
    .catch(() => {
      /* confetti is purely decorative — ignore load failures */
    });
}
