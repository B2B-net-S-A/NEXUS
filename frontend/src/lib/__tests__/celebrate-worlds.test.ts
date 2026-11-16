import { beforeEach, describe, expect, it, vi } from "vitest";

import { celebrate, WORLD_CELEBRATIONS } from "@/lib/celebrate";
import { useThemeStore } from "@/store/theme";

const confetti = vi.hoisted(() => Object.assign(vi.fn(), { shapeFromPath: vi.fn(() => "path-shape") }));
vi.mock("canvas-confetti", () => ({ default: confetti }));
vi.mock("@/lib/kidsSound", () => ({ playCelebrateSound: vi.fn() }));
vi.mock("@/lib/prefers-reduced-motion", () => ({ prefersReducedMotion: () => false }));

beforeEach(() => {
  confetti.mockReset();
  useThemeStore.setState({ kidsMode: false, world: "none", kidsSound: false });
});

describe("świętowanie w stylu świata", () => {
  it("bez świata i w Zen nic się nie dzieje", async () => {
    celebrate();
    useThemeStore.setState({ world: "zen" });
    celebrate();
    await new Promise((r) => setTimeout(r, 10));
    expect(confetti).not.toHaveBeenCalled();
    expect(WORLD_CELEBRATIONS.zen).toBeUndefined();
  });

  it("Sakura sypie płatkami w swoich kolorach", async () => {
    useThemeStore.setState({ world: "sakura" });
    celebrate({ variant: "hired" });
    await vi.waitFor(() => expect(confetti).toHaveBeenCalled());
    const opts = confetti.mock.calls[0][0];
    expect(opts.colors).toEqual(WORLD_CELEBRATIONS.sakura.colors);
    expect(opts.shapes).toEqual(["path-shape"]);
  });

  it("każdy świat z galerii poza Zen ma swoje świętowanie", async () => {
    const { THEME_WORLDS } = await import("@/store/theme");
    const missing = THEME_WORLDS.filter((w) => w.id !== "zen" && !WORLD_CELEBRATIONS[w.id]).map((w) => w.id);
    expect(missing).toEqual([]);
  });
});
