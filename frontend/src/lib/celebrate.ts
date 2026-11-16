import { useThemeStore } from "@/store/theme";
import { playCelebrateSound } from "@/lib/kidsSound";
import { prefersReducedMotion } from "@/lib/prefers-reduced-motion";

/**
 * Light gamification for the "Kids / game world" mode.
 *
 * `celebrate()` fires a (themed) confetti burst, an optional sound, and notifies
 * the mascot. It is a no-op unless Kids mode or a world with its own
 * celebration is on (13.11.2026: płatki w Sakurze, szachownica w Pit stopie,
 * śnieg w Zimie…; Zen i „bez świata” — nic), so call sites stay unconditional.
 * Respects `prefers-reduced-motion` (skips confetti; mascot/sound still
 * acknowledge). Sound plays only in Kids mode.
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

/** Kształt cząstek świata: wbudowany albo rysowany ścieżką SVG. */
type WorldShape = "square" | "circle" | "star" | "petal" | "leaf";

interface WorldCelebration {
  colors: string[];
  shapes: WorldShape[];
  /** Lekkie cząstki opadają wolniej (płatki, śnieg). */
  floaty?: boolean;
  /** Płaskie cząstki bez obrotu 3D (piksele w Retro). */
  flat?: boolean;
}

const PETAL_PATH = "M0,-8 C5,-8 8,-2 6,3 C4,7 1,8 0,6 C-1,8 -4,7 -6,3 C-8,-2 -5,-8 0,-8 Z";
const LEAF_PATH = "M0,-10 C7,-6 7,6 0,10 C-7,6 -7,-6 0,-10 Z";

/** Świętowanie per świat (`docs/claude/ui/swiaty-wygladu.md`). Zen celowo bez efektu. */
export const WORLD_CELEBRATIONS: Readonly<Record<string, WorldCelebration>> = {
  sakura: { colors: ["#f9b6cd", "#f48fb1", "#fde2ea", "#c2588e"], shapes: ["petal"], floaty: true },
  tulips: { colors: ["#e2445c", "#f6b2c4", "#f4c430", "#4c9a62"], shapes: ["petal"], floaty: true },
  lavender: { colors: ["#9b7fd1", "#b9a3e8", "#7a59c9", "#cfe0c8"], shapes: ["petal"], floaty: true },
  botanic: { colors: ["#2f6b47", "#4f9a62", "#8bbf7a", "#c9d8a8"], shapes: ["leaf"], floaty: true },
  latte: { colors: ["#6e4a2e", "#a8784e", "#e7d3b8", "#f4e9dc"], shapes: ["circle"] },
  marble: { colors: ["#b08a3c", "#d9b862", "#f1e3b6", "#1c1a17"], shapes: ["star"] },
  sunset: { colors: ["#ff9a5a", "#f06a6a", "#d9649a", "#8e5aa8", "#ffd166"], shapes: ["circle", "square"] },
  holo: { colors: ["#ffb3e6", "#c9b3ff", "#a3e4ff", "#b3f5d9", "#fff2a8"], shapes: ["star", "circle"] },
  arcade: { colors: ["#00e5ff", "#ff33d6", "#fff36b", "#7cff6b"], shapes: ["square"], flat: true },
  space: { colors: ["#ffffff", "#c9d4ff", "#b28cff", "#7fe3ff"], shapes: ["star"] },
  rgb: { colors: ["#ff3b3b", "#ffe83b", "#3bff6b", "#3bf2ff", "#5b6bff", "#ff3bf2"], shapes: ["square"] },
  blueprint: { colors: ["#ffffff", "#ffd53d", "#9fd3ff"], shapes: ["square"], flat: true },
  stadium: { colors: ["#127a4c", "#f2b705", "#ffffff"], shapes: ["square", "circle"] },
  pitstop: { colors: ["#ffffff", "#111111", "#ff8a0a"], shapes: ["square"], flat: true },
  mountains: { colors: ["#21634a", "#ff7a1a", "#ffffff", "#c62828"], shapes: ["leaf", "circle"] },
  winter: { colors: ["#ffffff", "#e3f1fb", "#bfe0f5"], shapes: ["circle"], floaty: true },
  retro: { colors: ["#1d4ed8", "#e53935", "#ffd400", "#111111"], shapes: ["square"], flat: true },
};

function worldShapes(confetti: Confetti, shapes: WorldShape[]): NonNullable<Parameters<Confetti>[0]>["shapes"] {
  return shapes.map((shape) => {
    if (shape === "petal" || shape === "leaf") {
      const path = shape === "petal" ? PETAL_PATH : LEAF_PATH;
      return confetti.shapeFromPath ? confetti.shapeFromPath({ path }) : "circle";
    }
    return shape;
  });
}

function fireWorldConfetti(confetti: Confetti, fx: WorldCelebration, variant: CelebrateVariant, small: boolean): void {
  const base = {
    origin: { y: 0.7 },
    colors: fx.colors,
    shapes: worldShapes(confetti, fx.shapes),
    flat: fx.flat ?? false,
    gravity: fx.floaty ? 0.55 : 1,
    drift: fx.floaty ? 0.6 : 0,
    ticks: fx.floaty ? 320 : 200,
    scalar: fx.shapes.includes("petal") || fx.shapes.includes("leaf") ? 1.4 : 1,
    disableForReducedMotion: true,
  };
  if (small) {
    confetti({ ...base, particleCount: 30, spread: 55, startVelocity: 32 });
    return;
  }
  const big = variant === "hired" || variant === "levelup" || variant === "welcome";
  confetti({ ...base, particleCount: big ? 110 : 70, spread: 75, startVelocity: 50 });
  confetti({ ...base, particleCount: big ? 70 : 40, spread: 120, startVelocity: 32 });
}

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
  const { kidsMode, kidsSound, world } = useThemeStore.getState();
  const worldFx = kidsMode ? undefined : WORLD_CELEBRATIONS[world];
  if (!kidsMode && !worldFx) return; // tylko w trybie gry albo w świecie z własnym świętowaniem

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
    .then(({ default: confetti }) =>
      worldFx
        ? fireWorldConfetti(confetti, worldFx, variant, options.small === true)
        : fireConfetti(confetti, variant, options.small === true)
    )
    .catch(() => {
      /* confetti is purely decorative — ignore load failures */
    });
}
