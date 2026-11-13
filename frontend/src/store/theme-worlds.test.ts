import { beforeEach, describe, expect, it } from "vitest";

import { useThemeStore } from "@/store/theme";

beforeEach(() => {
  useThemeStore.setState({ kidsMode: false, world: "none", worldBeforeSeason: null, seenSeasonKeys: [] });
});

describe("store światów", () => {
  it("wybór świata wyłącza tryb gry, a tryb gry zdejmuje świat", () => {
    useThemeStore.setState({ kidsMode: true });
    useThemeStore.getState().setWorld("sakura");
    expect(useThemeStore.getState()).toMatchObject({ world: "sakura", kidsMode: false });
    useThemeStore.getState().toggleKidsMode();
    expect(useThemeStore.getState()).toMatchObject({ world: "none", kidsMode: true });
  });

  it("wejście w świat sezonowy zapamiętuje poprzedni, wyjście czyści", () => {
    const { setWorld } = useThemeStore.getState();
    setWorld("latte");
    setWorld("winter");
    expect(useThemeStore.getState()).toMatchObject({ world: "winter", worldBeforeSeason: "latte" });
    setWorld("tulips");
    expect(useThemeStore.getState().worldBeforeSeason).toBe("latte");
    setWorld("space");
    expect(useThemeStore.getState()).toMatchObject({ world: "space", worldBeforeSeason: null });
  });

  it("zapis z konta ustawia świat bez dopisywania historii", () => {
    useThemeStore.getState().applyAccountWorld("winter", "sakura", false);
    expect(useThemeStore.getState()).toMatchObject({ world: "winter", worldBeforeSeason: "sakura", kidsMode: false });
    useThemeStore.getState().applyAccountWorld("none", null, true);
    expect(useThemeStore.getState()).toMatchObject({ world: "none", kidsMode: true });
  });

  it("widziany sezon zapisuje się raz", () => {
    const { markSeasonSeen } = useThemeStore.getState();
    markSeasonSeen("winter-2026");
    markSeasonSeen("winter-2026");
    expect(useThemeStore.getState().seenSeasonKeys).toEqual(["winter-2026"]);
  });

  it("migracja v9 → v10 dokłada świat i czyści nieznane wartości", async () => {
    const migrate = useThemeStore.persist.getOptions().migrate;
    expect(migrate).toBeDefined();
    const next = (await migrate?.({ theme: "light", palette: "rose", world: "disco" }, 9)) as unknown as Record<string, unknown>;
    expect(next).toMatchObject({ palette: "rose", world: "none", worldBeforeSeason: null, seenSeasonKeys: [] });
  });
});
