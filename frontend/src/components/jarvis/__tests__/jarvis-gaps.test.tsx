import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { applyStreamEvent, type JarvisTurnState } from "@/lib/jarvis/reducer";
import type { JarvisGap } from "@/lib/jarvis/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { JarvisGapsOverview } from "@/components/settings/JarvisGapsOverview";
import { JarvisCapabilities } from "../JarvisCapabilities";
import { JarvisGapCard } from "../JarvisGapCard";

const report = vi.fn();
let failReport = false;
let gapRows: unknown[] = [];
vi.mock("@/lib/jarvis/api", () => ({
  reportJarvisGap: async (id: string) => {
    report(id);
    if (failReport) throw new Error("boom");
  },
  fetchJarvisGaps: async () => gapRows,
}));

const GAP: JarvisGap = {
  id: "gap-1",
  kind: "no_access",
  need: "kto jest Delivery Leadem klienta",
  why: "Rola rekrutera nie widzi klientów.",
  workaround: "Zapytaj Head of Recruitment.",
  reported: false,
};

describe("karta „Tego nie zrobię”", () => {
  beforeEach(() => {
    report.mockReset();
    failReport = false;
  });

  it("mówi, czego brakuje, dlaczego i co zrobić teraz", () => {
    render(<JarvisGapCard gap={GAP} />);
    expect(screen.getByText("Twoja rola tego nie widzi")).toBeInTheDocument();
    expect(screen.getByText(GAP.why)).toBeInTheDocument();
    expect(screen.getByText(GAP.workaround)).toBeInTheDocument();
  });

  it("zgłasza potrzebę i pokazuje, że poszło", async () => {
    render(<JarvisGapCard gap={GAP} />);
    fireEvent.click(screen.getByRole("button", { name: "Zgłoś, że tego potrzebuję" }));
    await waitFor(() => expect(screen.getByText(/Zgłoszone/)).toBeInTheDocument());
    expect(report).toHaveBeenCalledWith("gap-1");
  });

  it("nieudane zgłoszenie mówi o błędzie i zostawia przycisk", async () => {
    failReport = true;
    render(<JarvisGapCard gap={GAP} />);
    fireEvent.click(screen.getByRole("button", { name: "Zgłoś, że tego potrzebuję" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zgłoś, że tego potrzebuję" })).toBeEnabled();
  });

  it("karta zgłoszona wcześniej (z historii) nie ma przycisku", () => {
    render(<JarvisGapCard gap={{ ...GAP, reported: true }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("zdarzenie strumienia dokłada kartę do rozmowy", () => {
    const empty: JarvisTurnState = { items: [], thinking: true, mood: "thinking", conversationId: null };
    const next = applyStreamEvent(empty, { type: "gap", gap: GAP });
    expect(next.items).toEqual([{ kind: "gap", gap: GAP }]);
  });
});

describe("pusty panel — co Jarvis zrobi za tę rolę", () => {
  it("pokazuje tylko grupy, które rola ma", () => {
    render(<JarvisCapabilities capabilities={{ read: ["tablice rekrutacji"], write: [], never: ["usuwanie"] }} />);
    expect(screen.getByText("Sprawdzę od razu")).toBeInTheDocument();
    expect(screen.queryByText(/Przygotuję/)).toBeNull();
    expect(screen.getByText("usuwanie")).toBeInTheDocument();
  });
});

describe("Ustawienia → AI → Czego Jarvis nie umie", () => {
  function renderOverview() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <JarvisGapsOverview />
      </QueryClientProvider>,
    );
  }

  it("liczy zgłoszone i rodzaje, bez nazwisk pytających", async () => {
    gapRows = [
      { ...GAP, role: "recruiter", created_at: "2026-10-27T10:00:00Z", reported: true },
      { ...GAP, id: "gap-2", kind: "not_supported", role: "admin", created_at: "2026-10-27T11:00:00Z" },
    ];
    renderOverview();
    expect(await screen.findByText("Zgłoszone przez ludzi")).toBeInTheDocument();
    expect(screen.getAllByText(GAP.need)).toHaveLength(2);
    expect(screen.getByText(/rola: recruiter · zgłoszone/)).toBeInTheDocument();
  });

  it("pusty okres mówi to wprost", async () => {
    gapRows = [];
    renderOverview();
    expect(await screen.findByText(/nie pokazał żadnej karty braku/)).toBeInTheDocument();
  });
});
