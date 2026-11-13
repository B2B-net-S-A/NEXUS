/** Dzwonienie → Kampanie → Bot Listy (decyzje Artura 13.11.2026). Dane fikcyjne. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BotListState } from "@/lib/api/sales-bot-lists";
import type { CallCampaign } from "@/lib/api/sales-calling";

const save = vi.fn();
const build = vi.fn();
const refetch = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };
let state: { data?: BotListState; isSuccess: boolean; isError: boolean; error: unknown; refetch: () => void };

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOwnerCandidates: () => ({ data: [{ id: 5, name: "Ewa Testowa" }, { id: 6, name: "Jan Przykładowy" }] }),
}));
vi.mock("@/lib/api/sales-bot-lists", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-bot-lists")>()),
  useBotList: () => state,
  useSaveBrief: () => ({ mutate: save, isPending: false }),
  useBuildList: () => ({ mutate: build, isPending: false }),
}));

import { BotListPanel } from "../calling/BotListPanel";

const campaign = { id: 3, name: "Banki", service: null, script: null, total: 0, counts: {} } as CallCampaign;

function ok(data: BotListState) {
  return { data, isSuccess: true, isError: false, error: null, refetch };
}

const base: BotListState = {
  enabled: true,
  campaign_id: 3,
  brief: null,
  built_at: null,
  by_role: [
    { key: "manager", label: "Manager / Lead", calls: 517, meetings: 15, rate: 0.029, not_interested: 215 },
    { key: "board", label: "Zarząd", calls: 131, meetings: 0, rate: 0, not_interested: 54 },
  ],
  by_source: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  state = ok(base);
});

describe("BotListPanel", () => {
  it("zapisuje brief z rolą, branżą i osobami dzwoniącymi", () => {
    render(<BotListPanel campaign={campaign} onBack={() => {}} />);
    fireEvent.change(screen.getByLabelText("Branża (słowa, po przecinku)"), { target: { value: "bank, finans" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Ewa Testowa" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz brief" }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ roles: ["manager", "head"], industries: ["bank", "finans"], caller_ids: [5], per_caller: 40 }),
      expect.anything(),
    );
  });

  it("bez briefu „Zbuduj listę” jest nieaktywne, z briefem buduje listę", () => {
    const { rerender } = render(<BotListPanel campaign={campaign} onBack={() => {}} />);
    expect(screen.getByRole("button", { name: /Zbuduj listę/ })).toBeDisabled();
    state = ok({
      ...base,
      brief: { ...{ roles: ["manager"], industries: [], pkd: [], regions: [], sizes: [], triggers: [], sources: ["base"] }, include_unknown: true, per_caller: 20, caller_ids: [5], auto_refill: true },
    });
    rerender(<BotListPanel campaign={campaign} onBack={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Zbuduj listę/ }));
    expect(build).toHaveBeenCalled();
  });

  it("pokazuje „Co działa” i komunikat przy błędzie zamiast pustki", () => {
    const { rerender } = render(<BotListPanel campaign={campaign} onBack={() => {}} />);
    expect(screen.getByText("Co działa: rola")).toBeInTheDocument();
    expect(screen.getByText("2,9%")).toBeInTheDocument();
    state = { data: undefined, isSuccess: false, isError: true, error: new Error("x"), refetch };
    rerender(<BotListPanel campaign={campaign} onBack={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać Bota Listy.");
  });
});
