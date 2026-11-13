import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorldGallery } from "@/components/v2/shell/WorldGallery";
import { useThemeStore } from "@/store/theme";

const celebrate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/celebrate", () => ({ celebrate }));

const NOV = new Date("2026-11-13T10:00:00Z");
const DEC = new Date("2026-12-02T10:00:00Z");
const BOYS_DAY = new Date("2027-09-30T10:00:00Z");

beforeEach(() => {
  celebrate.mockReset();
  useThemeStore.setState({ kidsMode: false, world: "none", worldBeforeSeason: null, seenSeasonKeys: [] });
});

function tile(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-world-tile="${id}"]`);
  if (!el) throw new Error(`brak kafelka ${id}`);
  return el;
}

describe("galeria światów", () => {
  it("grupuje światy po klimacie i zmienia wygląd jednym kliknięciem", async () => {
    render(<WorldGallery open onOpenChange={() => {}} now={NOV} />);
    for (const label of ["Jasne i spokojne", "Kolorowe", "Ciemne", "Sport i przygoda"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    await userEvent.click(tile("sakura"));
    expect(useThemeStore.getState().world).toBe("sakura");
    expect(tile("sakura")).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Bez świata" }));
    expect(useThemeStore.getState().world).toBe("none");
  });

  it("Retro jest w katalogu, a światy sezonowe tylko w swoim terminie", () => {
    const { unmount } = render(<WorldGallery open onOpenChange={() => {}} now={NOV} />);
    expect(tile("retro")).toBeInTheDocument();
    expect(document.querySelector('[data-world-tile="winter"]')).toBeNull();
    expect(screen.queryByText("Sezonowe")).toBeNull();
    unmount();
    render(<WorldGallery open onOpenChange={() => {}} now={DEC} />);
    expect(tile("winter")).toHaveTextContent("Sezon");
    expect(document.querySelector('[data-world-tile="tulips"]')).toBeNull();
  });

  it("w Dzień Chłopaka wyróżnia Pit stop i Góry", () => {
    render(<WorldGallery open onOpenChange={() => {}} now={BOYS_DAY} />);
    expect(tile("pitstop")).toHaveTextContent("Sezon");
    expect(tile("mountains")).toHaveTextContent("Sezon");
    expect(tile("sakura")).not.toHaveTextContent("Sezon");
  });

  it("Gra to dzisiejszy tryb gry, z powitaniem tylko przy włączeniu", async () => {
    render(<WorldGallery open onOpenChange={() => {}} now={NOV} />);
    await userEvent.click(tile("game"));
    expect(useThemeStore.getState().kidsMode).toBe(true);
    expect(celebrate).toHaveBeenCalledTimes(1);
    await userEvent.click(tile("game"));
    expect(useThemeStore.getState().kidsMode).toBe(true);
    expect(celebrate).toHaveBeenCalledTimes(1);
  });
});
