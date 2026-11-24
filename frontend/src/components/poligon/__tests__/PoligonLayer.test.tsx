import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { exercisesFor } from "@/lib/poligon/exercises";

// Koniec Poligonu (24.11.2026): osoba z kampanii luk czytała „dziś nie liczy
// się do Twoich statystyk”, a dzień ćwiczeń z luk się liczy. Ze statystyk
// wypada tylko dzień onboardingu nowej osoby (`onboarding_day`).

const PATH = exercisesFor(["recruiter"]).slice(0, 2);
const state = vi.hoisted(() => ({ poligon: {} as Record<string, unknown>, done: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/jobs/990001",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/novelties/api", () => ({
  useStartStatus: () => ({ enforced: false, items: [], poligon: { ...state.poligon, done_ids: state.done } }),
}));
vi.mock("@/lib/poligon/usePoligonPath", () => ({
  usePoligonPath: () => ({ path: PATH, context: { firstNew: null, role: "recruiter" } }),
}));
vi.mock("@/lib/poligon/adapter", () => ({ onPoligonAction: () => () => undefined }));

import { PoligonLayer } from "../PoligonLayer";

const STATS = /nie liczy się do Twoich statystyk/;

/** Radix podpina nasłuch `pointerdown` na dokumencie dopiero w `setTimeout(0)` po otwarciu okna. */
async function radixListening(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  state.done = PATH.map((e) => `poligon-${e.id}`);
});

describe("PoligonLayer — koniec Poligonu", () => {
  it("nowa osoba: dzień onboardingu nie liczy się do statystyk", () => {
    state.poligon = { open: true, required: true, done: 2, total: 2, luki: null };
    render(<PoligonLayer />);
    expect(screen.getByText(/Onboarding zaliczony/).closest("span")).toHaveTextContent(STATS);
  });

  it("osoba z kampanii luk po terminie: bez zdania o statystykach", () => {
    state.poligon = { open: true, required: true, done: 2, total: 2, luki: { due: "2026-11-23", credited_ids: [] } };
    render(<PoligonLayer />);
    const end = screen.getByText(/Onboarding zaliczony/).closest("span");
    expect(end).toHaveTextContent(/NEXUS jest otwarty/);
    expect(end).not.toHaveTextContent(STATS);
  });

  it("osoba z lukami przed terminem i osoba bez wymogu: bez zdania o statystykach", () => {
    state.poligon = { open: true, required: false, done: 2, total: 2, luki: { due: "2026-11-30", credited_ids: [] } };
    const { unmount } = render(<PoligonLayer />);
    expect(screen.getByText(/Onboarding zaliczony/).closest("span")).not.toHaveTextContent(STATS);
    unmount();
    state.poligon = { open: true, required: false, done: 2, total: 2, luki: null };
    render(<PoligonLayer />);
    expect(screen.getByText(/Onboarding zaliczony/).closest("span")).not.toHaveTextContent(STATS);
  });
});

describe("PoligonLayer — okno ćwiczenia nad oknem ekranu", () => {
  it("klik w okno ćwiczenia nie zamyka otwartego okna Radix", async () => {
    state.done = [];
    state.poligon = { open: true, required: true, done: 0, total: 2, luki: null };
    const onOpenChange = vi.fn();
    render(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent>
            <DialogTitle>Edytor CV</DialogTitle>
          </DialogContent>
        </Dialog>
        <PoligonLayer />
      </>,
    );
    await radixListening();
    // Otwarte okno Radix oznacza resztę strony `aria-hidden` — stąd `hidden: true`.
    // `pointer-events: none` na body ustawia Radix, a okno ćwiczenia ma
    // `pointer-events-auto` (klasa, której jsdom nie liczy) — stąd bez sprawdzania.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByRole("region", { name: "Ćwiczenie na poligonie", hidden: true }));
    await radixListening();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
