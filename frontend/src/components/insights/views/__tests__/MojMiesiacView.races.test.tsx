import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const monthlyRaces = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  kpisApi: {
    myPanel: () =>
      Promise.resolve({
        data: {
          role: "recruiter",
          applies: true,
          weryfikacje: { day: 1, week: 3, month: 9 },
          rekomendacje: { day: 0, week: 1, month: 4 },
          interview_month: 2,
          akceptacje_month: 0,
          placementy_month: 1,
          cv_to_base: null,
          precision: { value_pct: null, verified: 2, sent: 1, target_pct: 75, window_days: 30 },
          target_verifications_daily: 4,
          target_placements_monthly: 1,
          target_cv_added_daily: null,
          target_precision_pct: 75,
        },
      }),
  },
}));
vi.mock("@/lib/insights-races-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  racesApi: {
    monthlyRaces: () => monthlyRaces(),
    myPosition: () => new Promise(() => {}),
  },
}));
vi.mock("@/lib/insights-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  insightsApi: {
    recruitmentFunnel: () => new Promise(() => {}),
    seniority: () => new Promise(() => {}),
  },
}));
vi.mock("@/lib/insights-team-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  insightsTeamApi: { teamTableWithAnchoredAverage: () => new Promise(() => {}) },
  insightsTeamQueryKeys: { teamTableAnchored: () => ["insights", "team", "anchored"] },
}));

import { MojMiesiacView } from "../MojMiesiacView";
import { useAuthStore } from "@/store/auth";

const EMPTY_SENTENCE = /Nikt nie ma jeszcze wymaganej liczby placementów/;

function renderView() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MojMiesiacView />
    </QueryClientProvider>,
  );
}

async function racePanel(): Promise<HTMLElement> {
  const heading = await screen.findByText("Wyścig placementów");
  return heading.closest("section") as HTMLElement;
}

// Runda 8 (R8-N14-2): awaria albo wczytywanie wyścigu nie może mówić
// „nikt się nie kwalifikuje” — to zdanie o wyścigu z nagrodą 1500 zł.
describe("MojMiesiacView — panel „Wyścig placementów”", () => {
  beforeEach(() => {
    monthlyRaces.mockReset();
    useAuthStore.setState({ user: { id: 7, role: "recruiter" } } as never);
  });

  it("awaria wyścigu → komunikat błędu z ponowieniem, bez zdania o pustce", async () => {
    monthlyRaces
      .mockRejectedValueOnce(Object.assign(new Error("boom"), { response: { status: 500 } }))
      .mockResolvedValue({ placements: { ranking: [], prize: { name: "1500 zł" } } });
    renderView();
    const panel = await racePanel();
    const retry = await within(panel).findByRole("button", { name: /Spróbuj ponownie|Ponów/ });
    expect(within(panel).queryByText(EMPTY_SENTENCE)).toBeNull();
    await userEvent.click(retry);
    expect(await within(panel).findByText(EMPTY_SENTENCE)).toBeTruthy();
  });

  it("wyścig jeszcze się wczytuje → „…”, bez zdania o pustce", async () => {
    monthlyRaces.mockReturnValue(new Promise(() => {}));
    renderView();
    const panel = await racePanel();
    expect(within(panel).queryByText(EMPTY_SENTENCE)).toBeNull();
    expect(within(panel).getByText("Wczytuję wyścig…")).toBeTruthy();
  });
});
