/**
 * Dzwonienie → Skuteczność: lejek, ranking z sortowaniem, pusty okres, awaria
 * zapytania i przełącznik widoczny tylko z „Sprzedaż: edycja”. Dane fikcyjne.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Effectiveness } from "@/lib/api/sales-calling-stats";

const effectiveness = vi.fn();
let canEdit = true;

vi.mock("@/lib/api/sales-calling-stats", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-calling-stats")>()),
  useCallingEffectiveness: (filters: unknown) => effectiveness(filters),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: object }) => unknown) => selector({ user: { id: 5, name: "Ja" } }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/sales/calling/effectiveness" }));

import { CallingModeSwitch } from "../calling/CallingModeSwitch";
import { EffectivenessView, funnelSteps, rankPeople } from "../calling/EffectivenessView";

const hours = Array.from({ length: 5 }, (_, weekday) =>
  Array.from({ length: 10 }, (_, i) => ({ weekday, hour: 8 + i, calls: 0, talks: 0, rate: null })),
).flat();

function data(overrides: Partial<Effectiveness> = {}): Effectiveness {
  return {
    start: "2026-11-09",
    end: "2026-11-13",
    workdays: 4,
    funnel: { calls: 40, talks: 20, offers: 8, meetings: 4, dated: 1, held: 0, qualified: 0 },
    outcomes: { no_answer: 20, offer_sent: 8, meeting_booked: 4, not_now: 8 },
    campaigns: [
      {
        id: 1,
        name: "Kampania Testowa",
        service: "Usługa",
        on_list: 100,
        left: 60,
        days_left: 6,
        calls: 40,
        talks: 20,
        offers: 8,
        meetings: 4,
      },
    ],
    sources: [{ source: "Lista A", records: 30, reached: 15, talks: 20, meetings: 4, objections: 1 }],
    hours,
    offer_followup: { offer_sent: 6, meeting_booked: 2 },
    people: [
      { user_id: 1, name: "Osoba Alfa", days: 2, calls: 30, talks: 10, offers: 5, meetings: 1, dated: 0, qualified: 0 },
      { user_id: 2, name: "Osoba Beta", days: 2, calls: 10, talks: 10, offers: 3, meetings: 3, dated: 1, qualified: 0 },
    ],
    insights: [{ tone: "warning", text: "3 z 4 umówionych spotkań nie ma terminu w NEXUSIE." }],
    campaign_options: [{ id: 1, name: "Kampania Testowa" }],
    ...overrides,
  };
}

function ok(value: Effectiveness) {
  return { data: value, isLoading: false, isSuccess: true, error: null, refetch: vi.fn() };
}

function rankingNames(): string[] {
  const table = within(screen.getByRole("region", { name: "Ranking osób" })).getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[1].textContent ?? "");
}

beforeEach(() => {
  effectiveness.mockReset();
  canEdit = true;
});

describe("Skuteczność dzwonienia", () => {
  it("liczy lejek względem poprzedniego kroku i ostrzega o spotkaniach bez terminu", () => {
    const steps = funnelSteps(data());
    expect(steps.map((s) => s.hint)).toEqual([
      "10 dziennie",
      "50% telefonów",
      "40% rozmów",
      "20% rozmów",
      "1 z 4",
      "po pierwszych spotkaniach",
    ]);
    expect(steps.find((s) => s.key === "dated")?.warn).toBe(true);
  });

  it("ranking sortuje po spotkaniach, a klik w nagłówek zmienia kolejność", () => {
    effectiveness.mockReturnValue(ok(data()));
    render(<EffectivenessView />);
    expect(rankingNames()[0]).toContain("Osoba Beta");
    fireEvent.click(screen.getByRole("button", { name: "Telefony" }));
    expect(rankingNames()[0]).toContain("Osoba Alfa");
    expect(screen.getByText("3 z 4 umówionych spotkań nie ma terminu w NEXUSIE.")).toBeInTheDocument();
    expect(screen.getByText(/Za mało telefonów, żeby pokazać pory dnia/)).toBeInTheDocument();
  });

  it("remis w rankingu rozstrzyga alfabet", () => {
    const [a, b] = data().people;
    expect(rankPeople([b, { ...a, meetings: 3 }], "meetings").map((p) => p.name)).toEqual([
      "Osoba Alfa",
      "Osoba Beta",
    ]);
  });

  it("filtry idą do zapytania: okres, kampania i „Moje”", () => {
    effectiveness.mockReturnValue(ok(data()));
    render(<EffectivenessView />);
    expect(effectiveness).toHaveBeenLastCalledWith({ period: "week", campaignId: null, mine: false });
    fireEvent.click(screen.getByRole("radio", { name: "4 tygodnie" }));
    fireEvent.click(screen.getByRole("button", { name: "Kampania Testowa" }));
    fireEvent.click(screen.getByRole("radio", { name: "Moje" }));
    expect(effectiveness).toHaveBeenLastCalledWith({ period: "4w", campaignId: 1, mine: true });
  });

  it("okres bez telefonów pokazuje pusty stan zamiast tabel", () => {
    effectiveness.mockReturnValue(
      ok(
        data({
          funnel: { calls: 0, talks: 0, offers: 0, meetings: 0, dated: 0, held: 0, qualified: 0 },
          people: [],
        }),
      ),
    );
    render(<EffectivenessView />);
    expect(screen.getByText("W tym okresie nie ma zapisanych telefonów.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ranking osób" })).not.toBeInTheDocument();
  });

  it("awaria zapytania nie wygląda jak pusty okres", () => {
    effectiveness.mockReturnValue({
      data: undefined,
      isLoading: false,
      isSuccess: false,
      error: { response: { status: 500 } },
      refetch: vi.fn(),
    });
    render(<EffectivenessView />);
    expect(screen.queryByText("W tym okresie nie ma zapisanych telefonów.")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("przełącznik „Kolejka | Skuteczność” widzi tylko „Sprzedaż: edycja”", () => {
    const { rerender } = render(<CallingModeSwitch />);
    expect(screen.getByRole("link", { name: "Skuteczność" })).toHaveAttribute("aria-current", "page");
    canEdit = false;
    rerender(<CallingModeSwitch />);
    expect(screen.queryByRole("link", { name: "Skuteczność" })).not.toBeInTheDocument();
  });
});
