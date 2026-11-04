import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { applyStreamEvent, applyUndoOutcome, type JarvisTurnState } from "@/lib/jarvis/reducer";
import type { JarvisAction } from "@/lib/jarvis/types";
import { JarvisActionCard } from "../JarvisActionCard";

function executed(undo: JarvisAction["undo"]): JarvisAction {
  return {
    id: "a1",
    tool: "create_note",
    status: "executed",
    preview: { text: "Dodam notatkę do kandydata" },
    result: { ok: true },
    undo,
  };
}

const LATER = new Date(Date.now() + 10 * 60_000).toISOString();
const EARLIER = new Date(Date.now() - 60_000).toISOString();

describe("karta zapisu wykonanego od razu", () => {
  it("pokazuje „Zrobione za Ciebie” i „Cofnij” w oknie 15 minut", () => {
    const onUndo = vi.fn();
    render(<JarvisActionCard action={executed({ state: "available", until: LATER })} onUndo={onUndo} />);
    expect(screen.getByText("Zrobione za Ciebie")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Cofnij/ }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("po oknie przycisku nie ma", () => {
    render(<JarvisActionCard action={executed({ state: "available", until: EARLIER })} onUndo={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Cofnij/ })).toBeNull();
  });

  it("przycisk znika sam, gdy okno mija przy otwartym panelu", () => {
    vi.useFakeTimers();
    try {
      const until = new Date(Date.now() + 1000).toISOString();
      render(<JarvisActionCard action={executed({ state: "available", until })} onUndo={vi.fn()} />);
      expect(screen.getByRole("button", { name: /Cofnij/ })).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(1500);
      });
      expect(screen.queryByRole("button", { name: /Cofnij/ })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("cofnięta mówi to wprost, nieudane cofnięcie też", () => {
    const { rerender } = render(<JarvisActionCard action={executed({ state: "done", until: LATER })} />);
    expect(screen.getByText(/Cofnięte/)).toBeInTheDocument();
    rerender(<JarvisActionCard action={executed({ state: "failed", until: LATER })} />);
    expect(screen.getByText(/Nie udało się cofnąć/)).toBeInTheDocument();
  });

  it("akcja bez cofania (zatwierdzona kliknięciem) nie ma przycisku", () => {
    render(<JarvisActionCard action={executed(null)} onUndo={vi.fn()} />);
    expect(screen.getByText("Akcja")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("komunikat o cofnięciu idzie na koniec rozmowy, po odpowiedzi modelu", () => {
    const card = executed({ state: "available", until: LATER });
    const items = applyUndoOutcome(
      [
        { kind: "action", action: card },
        { kind: "message", role: "assistant", markdown: "Dodałem notatkę." },
      ],
      executed({ state: "done", until: LATER }),
      "Cofnięte.",
    );
    expect(items.map((i) => (i.kind === "message" ? i.markdown : i.kind))).toEqual([
      "action",
      "Dodałem notatkę.",
      "Cofnięte.",
    ]);
  });

  it("wykonana karta nie stawia maskotki w stan „czekam na kliknięcie”", () => {
    const start: JarvisTurnState = { items: [], thinking: true, mood: "working", conversationId: null };
    const next = applyStreamEvent(start, { type: "action_proposed", action: executed({ state: "available", until: LATER }) });
    expect(next.mood).toBe("working");
  });
});
