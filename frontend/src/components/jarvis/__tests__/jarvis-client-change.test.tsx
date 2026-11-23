import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clientChangeHref, takeClientChangeText } from "@/lib/champion-client-change";
import { applyStreamEvent, type JarvisTurnState } from "@/lib/jarvis/reducer";
import type { JarvisClientChange } from "@/lib/jarvis/types";
import { JarvisClientChangeCard } from "../JarvisClientChangeCard";

vi.mock("next/link", () => ({
  default: ({ href, onClick, children, ...rest }: { href: string; onClick?: () => void; children: React.ReactNode }) => (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        onClick?.();
      }}
      {...rest}
    >
      {children}
    </a>
  ),
}));

const PROPOSAL: JarvisClientChange = {
  job_id: 42,
  job_title: "Analityk danych",
  text: "Klient teraz wymaga Pythona jako musi mieć, SAFe odpada.",
  summary: "+ Python (musi mieć)\n− SAFe",
};

describe("karta „Zmiana od klienta” od Jarvisa", () => {
  beforeEach(() => sessionStorage.clear());

  it("mówi, że nic nie zmieniono, i pokazuje streszczenie jako tekst", () => {
    render(<JarvisClientChangeCard proposal={{ ...PROPOSAL, summary: "<b>Python</b>" }} />);
    expect(screen.getByText(/nic nie zmieniono/)).toBeInTheDocument();
    expect(screen.getByText("Analityk danych")).toBeInTheDocument();
    expect(screen.getByText("<b>Python</b>")).toBeInTheDocument();
  });

  it("„Pokaż i popraw” zostawia treść dla okna i prowadzi do Profilu tej rekrutacji", () => {
    const onNavigate = vi.fn();
    render(<JarvisClientChangeCard proposal={PROPOSAL} onNavigate={onNavigate} />);
    const link = screen.getByRole("link", { name: /Pokaż i popraw/ });
    expect(link).toHaveAttribute("href", clientChangeHref(42));
    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(takeClientChangeText(42)).toBe(PROPOSAL.text);
    // Odczyt jest jednorazowy — powrót na stronę nie otwiera okna drugi raz.
    expect(takeClientChangeText(42)).toBeNull();
  });

  it("karta z historii (bez tytułu) pokazuje numer rekrutacji", () => {
    render(<JarvisClientChangeCard proposal={{ job_id: 7, text: PROPOSAL.text, summary: "" }} />);
    expect(screen.getByText("Rekrutacja #7")).toBeInTheDocument();
  });

  it("zdarzenie strumienia dokłada kartę do rozmowy", () => {
    const state = { items: [] } as unknown as JarvisTurnState;
    const next = applyStreamEvent(state, { type: "client_change", proposal: PROPOSAL });
    expect(next.items).toEqual([{ kind: "client_change", proposal: PROPOSAL }]);
  });
});
