import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ZasadyView } from "../ZasadyView";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  params: new URLSearchParams("tab=zasady&zasada=blizniaki"),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get } }));
vi.mock("next/navigation", () => ({ useSearchParams: () => mocks.params }));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ pushUrl: vi.fn() }) }));
vi.mock("@/store/auth", async (original) => ({
  ...(await original<typeof import("@/store/auth")>()),
  useAuthStore: (select: (s: unknown) => unknown) =>
    select({
      user: {
        id: 1,
        role: "admin",
        roles: ["admin"],
        effective_section_access: {
          sourcing: "write",
          pipeline: "write",
          insights: "write",
          delivery: "write",
          finance: "write",
          system_admin: "write",
        },
      },
    }),
}));

// Panele zapisują przez własne mutacje; zakładka nie zna ich kluczy.
function SavingPanel() {
  const save = useMutation({ mutationFn: async () => undefined });
  return (
    <button type="button" onClick={() => save.mutate()}>
      Zapisz w panelu
    </button>
  );
}
vi.mock("@/components/settings/TwinRulesSettings", () => ({
  TWIN_RULES_INTRO: "",
  TwinRulesSettings: SavingPanel,
}));
vi.mock("@/components/settings/KpiTargetsSettings", () => ({ KPI_TARGETS_INTRO: "", KpiTargetsSettings: () => null }));
vi.mock("@/components/settings/PrepReviewSettings", () => ({ PREP_REVIEW_INTRO: "", PrepReviewSettings: () => null }));
vi.mock("@/components/settings/ranking/RankingPanel", () => ({ RANKING_INTRO: "", RankingPanel: () => null }));
vi.mock("@/components/settings/PlacementExclusionsTab", () => ({ PlacementExclusionsTab: () => null }));
vi.mock("@/components/settings/QcQualityPanel", () => ({ QcQualityPanel: () => null }));
vi.mock("@/components/v2/competence-team/AllocationRulesPanel", () => ({ AllocationRulesPanel: () => null }));
vi.mock("@/components/insights/views/zasady/LeagueRulesPanel", () => ({ LeagueRulesPanel: () => null }));

const overview = (lastChange: { at: string; by: string } | null) => ({
  data: { rules: [{ id: "blizniaki", now: "Podobieństwo od 80%", last_change: lastChange }] },
});

const ui = (client: QueryClient) => (
  <QueryClientProvider client={client}>
    <ZasadyView />
  </QueryClientProvider>
);

describe("ZasadyView: przegląd po zmianie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = new URLSearchParams("tab=zasady&zasada=blizniaki");
  });

  it("po zapisie w panelu odświeża „Ostatnią zmianę”", async () => {
    mocks.get.mockResolvedValueOnce(overview(null));
    mocks.get.mockResolvedValue(overview({ at: "2026-11-05T10:00:00Z", by: "Osoba Testowa" }));
    const user = userEvent.setup();
    render(ui(new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })));
    await screen.findByText(/Ostatnia zmiana: Nigdy/);
    await user.click(screen.getByRole("button", { name: "Zapisz w panelu" }));
    await screen.findByText(/Osoba Testowa/);
  });

  it("przejście do przeglądu pobiera wartości od nowa", async () => {
    mocks.get.mockResolvedValue(overview(null));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
    const { rerender } = render(ui(client));
    await screen.findByText(/Ostatnia zmiana: Nigdy/);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    mocks.params = new URLSearchParams("tab=zasady");
    rerender(ui(client));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
  });

  it("samo wejście nie pyta dwa razy", async () => {
    mocks.get.mockResolvedValue(overview(null));
    render(ui(new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })));
    await screen.findByText(/Ostatnia zmiana: Nigdy/);
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
});
