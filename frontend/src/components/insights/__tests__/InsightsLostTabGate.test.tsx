/**
 * „Przegrane” montuje się dopiero, gdy wiadomo, kto patrzy.
 *
 * Bez `user` lista zakładek jest pełna („jeszcze nie wiemy”), więc rekruter
 * z linkiem `?tab=przegrane` montował `PrzegraneView`, które od razu pytało
 * `GET /api/insights/lost-review` i dostawało 403 (staging 26.11.2026, konto
 * rekrutera, błąd w konsoli przed przekierowaniem na „Rywalizację”).
 * „Wnioski” mają tę samą osłonę od #3042.
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=przegrane"),
  usePathname: () => "/insights",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/url-selection", () => ({
  useUrlWriter: () => ({ replaceUrl: vi.fn(), pushUrl: vi.fn() }),
}));
vi.mock("@/lib/insights-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/insights-api")>();
  return {
    ...actual,
    insightsApi: { ...actual.insightsApi, wnioski: vi.fn(() => new Promise(() => {})) },
  };
});

const { stub } = vi.hoisted(() => ({
  stub: (id: string) =>
    function Stub() {
      return <div data-testid={id} />;
    },
}));
vi.mock("@/components/insights/views/PrzegraneView", () => ({ PrzegraneView: stub("przegrane") }));
vi.mock("@/components/insights/views/FirmaView", () => ({ FirmaView: stub("firma") }));
vi.mock("@/components/insights/views/MojMiesiacView", () => ({ MojMiesiacView: stub("moj") }));
vi.mock("@/components/insights/views/RaportyView", () => ({ RaportyView: stub("raporty") }));
vi.mock("@/components/insights/views/RywalizacjaView", () => ({ RywalizacjaView: stub("rywalizacja") }));
vi.mock("@/components/insights/views/ZespolView", () => ({ ZespolView: stub("zespol") }));
vi.mock("@/components/insights/views/RytmDniaView", () => ({ RytmDniaView: stub("rytm") }));
vi.mock("@/components/insights/views/WnioskiView", () => ({ WnioskiView: stub("wnioski") }));
vi.mock("@/components/insights/views/ZrodlaView", () => ({ ZrodlaView: stub("zrodla") }));
vi.mock("@/components/insights/views/ZasadyView", () => ({ ZasadyView: stub("zasady") }));

import { InsightsView } from "@/components/insights/InsightsView";
import { useAuthStore } from "@/store/auth";

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InsightsView />
    </QueryClientProvider>,
  );
}

function setUser(user: unknown, hydrated: boolean) {
  useAuthStore.setState({ user, hydrated } as never);
}

afterEach(() => setUser(null, false));

describe("InsightsView — zakładka „Przegrane” czeka na użytkownika", () => {
  it("bez użytkownika nie montuje widoku (nie ma zapytania, które dostałoby 403)", () => {
    setUser(null, false);
    renderView();
    expect(screen.queryByTestId("przegrane")).toBeNull();
  });

  it("Delivery Lead widzi widok", () => {
    setUser({ id: 27, role: "delivery_lead", roles: ["delivery_lead"] }, true);
    renderView();
    expect(screen.getByTestId("przegrane")).toBeTruthy();
  });

  it("rekruter nie widzi widoku", () => {
    setUser({ id: 26, role: "recruiter", roles: ["recruiter"] }, true);
    renderView();
    expect(screen.queryByTestId("przegrane")).toBeNull();
  });
});
