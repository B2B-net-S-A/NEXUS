import { useThemeStore } from "@/store/theme";

/**
 * Light gamification for the "Kids / game world" mode.
 *
 * `celebrate()` fires a confetti burst and notifies the mascot. It is a hard
 * no-op unless Kids mode is on, so call sites can stay unconditional — the
 * professional theme never sees an effect. Respects `prefers-reduced-motion`.
 */

/** Window event the mascot listens to so it can react (bounce) to a win. */
export const CELEBRATE_EVENT = "nexus:celebrate";

interface CelebrateOptions {
  /** Optional decorative line shown by the mascot's speech bubble. */
  message?: string;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export function celebrate(options: CelebrateOptions = {}): void {
  if (typeof window === "undefined") return;
  // Only celebrate in the game world — silent everywhere else.
  if (!useThemeStore.getState().kidsMode) return;

  // Let the mascot react even when motion is reduced (it stays static via CSS).
  window.dispatchEvent(
    new CustomEvent(CELEBRATE_EVENT, { detail: { message: options.message } })
  );

  if (prefersReducedMotion()) return;

  // canvas-confetti touches `window`/`document`, so load it lazily on the client.
  void import("canvas-confetti")
    .then(({ default: confetti }) => {
      const fire = (particleRatio: number, opts: Record<string, unknown>) =>
        confetti({
          origin: { y: 0.7 },
          colors: ["#ec4899", "#a855f7", "#38bdf8", "#facc15", "#34d399", "#fb7185"],
          disableForReducedMotion: true,
          ...opts,
          particleCount: Math.floor(200 * particleRatio),
        });

      // A short, joyful multi-burst (spread + a couple of focused pops).
      fire(0.25, { spread: 26, startVelocity: 55 });
      fire(0.2, { spread: 60 });
      fire(0.35, { spread: 100, decay: 0.91, scalar: 0.9 });
      fire(0.1, { spread: 120, startVelocity: 25, decay: 0.92, scalar: 1.2 });
      fire(0.1, { spread: 120, startVelocity: 45 });
    })
    .catch(() => {
      /* confetti is purely decorative — ignore load failures */
    });
}
