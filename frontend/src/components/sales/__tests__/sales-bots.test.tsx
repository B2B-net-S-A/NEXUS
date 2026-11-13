/** Sprzedaż → Leady → Boty (decyzja Artura z 13.11.2026). Dane fikcyjne. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SalesBot, SalesBots } from "@/lib/api/sales-bots";

const mutate = vi.fn();
const refetch = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };
let query: { data?: SalesBots; isLoading: boolean; isSuccess: boolean; error: unknown; refetch: () => void };

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales-bots", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-bots")>()),
  useSalesBots: () => query,
  useSetBotPaused: () => ({ mutate, isPending: false }),
}));

import { BotsView } from "../bots/BotsView";

function bot(over: Partial<SalesBot>): SalesBot {
  return {
    key: "leads",
    name: "Bot Leady",
    kinds: ["signals"],
    webhook: "shared",
    enabled: true,
    paused: false,
    runs_7d: 2,
    received_7d: 2,
    failed_7d: 0,
    last_received_at: "2026-11-11T22:01:00Z",
    ...over,
  };
}

const BOTS: SalesBot[] = [
  bot({}),
  bot({ key: "research", name: "Bot Research", paused: true }),
  bot({ key: "company", name: "Bot Dane firm", enabled: false, runs_7d: 0, received_7d: 0, last_received_at: null }),
  bot({ key: "contacts", name: "Bot Kontakty", webhook: "none" }),
  bot({ key: "cognism", name: "Rutyna Cognism", webhook: "own", failed_7d: 2 }),
];

function ok(data: SalesBots) {
  return { data, isLoading: false, isSuccess: true, error: null, refetch };
}

beforeEach(() => {
  vi.clearAllMocks();
  query = ok({ items: BOTS, can_pause: true });
});

describe("BotsView", () => {
  it("pokazuje stan każdego bota, rutynę i liczby z 7 dni", () => {
    render(<BotsView />);
    const leads = within(screen.getByRole("generic", { name: "Bot Leady" }));
    expect(leads.getByText("Działa")).toBeInTheDocument();
    expect(leads.getByText("Grok · wspólna rutyna")).toBeInTheDocument();
    expect(leads.getByText(/Ostatnie 7 dni/)).toHaveTextContent("2 biegów, 2 z raportem");
    expect(within(screen.getByRole("generic", { name: "Bot Research" })).getByText("Wstrzymany")).toBeInTheDocument();
    expect(within(screen.getByRole("generic", { name: "Bot Dane firm" })).getByText("Wyłączony")).toBeInTheDocument();
    expect(within(screen.getByRole("generic", { name: "Bot Kontakty" })).getByText("Bez rutyny")).toBeInTheDocument();
    expect(within(screen.getByRole("generic", { name: "Rutyna Cognism" })).getByText(/Ostatnie 7 dni/)).toHaveTextContent(
      "2 bez raportu",
    );
    expect(screen.getByText(/bez „Przyjmij”/)).toBeInTheDocument();
  });

  it("administrator wstrzymuje i wznawia bota", () => {
    render(<BotsView />);
    fireEvent.click(screen.getByRole("switch", { name: "Wstrzymaj: Bot Leady" }));
    expect(mutate).toHaveBeenCalledWith({ bot: "leads", paused: true }, expect.anything());
    fireEvent.click(screen.getByRole("switch", { name: "Wznów: Bot Research" }));
    expect(mutate).toHaveBeenCalledWith({ bot: "research", paused: false }, expect.anything());
  });

  it("bez uprawnienia nie ma przełączników, błąd to komunikat, nie pusta lista", () => {
    query = ok({ items: BOTS, can_pause: false });
    const { rerender } = render(<BotsView />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    query = { data: undefined, isLoading: false, isSuccess: false, error: new Error("x"), refetch };
    rerender(<BotsView />);
    expect(screen.queryByText("Bot Leady")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ponownie/i })).toBeInTheDocument();
  });
});
