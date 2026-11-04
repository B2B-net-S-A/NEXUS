import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Zgłoszenie DL-a 29.10.2026: „Zobacz, kto się liczy” w panelu celów prowadzi
// do `/insights?tab=moj-miesiac&kto=…#kto-sie-liczy`. Od #2593 (22.10) DL
// dostaje „Jak idzie mój portfel?” bez tej listy, a u rekrutera lista jest
// zwinięta — link nie pokazywał nikogo.

let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => search,
}));
vi.mock("@/components/insights/sections/WhoCountsPanel", () => ({
  MyWhoCountsPanel: () => <div>LISTA KTO SIĘ LICZY</div>,
}));
vi.mock("../my-month/MyGoalsPanel", () => ({ MyGoalsPanel: () => null }));
vi.mock("../my-month/MyInFlightPanel", () => ({ MyInFlightPanel: () => null }));
vi.mock("../my-month/MyBonusPanel", () => ({ MyBonusPanel: () => null }));
vi.mock("@/lib/api/boardTasks", () => ({ useDlSendQueue: () => ({ data: undefined }) }));
vi.mock("@/lib/insights-races-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  racesApi: { myPosition: () => new Promise(() => {}) },
}));
vi.mock("@/lib/insights-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  insightsBoardApi: { dlPortfolio: () => new Promise(() => {}) },
}));

import { MyPortfolioView } from "../my-month/MyPortfolioView";
import { MyWhoCountsSection } from "../my-month/MyWhoCountsSection";
import { useAuthStore } from "@/store/auth";

const LIST = "LISTA KTO SIĘ LICZY";

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("Mój miesiąc — link „Zobacz, kto się liczy”", () => {
  beforeEach(() => {
    search = new URLSearchParams();
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead" } } as never);
  });

  it("widok Delivery Leada ma listę i link z panelu celów ją otwiera", () => {
    search = new URLSearchParams("tab=moj-miesiac&kto=rekomendacje");
    render(wrap(<MyPortfolioView />));
    expect(screen.getByText(LIST)).toBeTruthy();
  });

  it("bez linku lista jest zwinięta i rozwija się przyciskiem", async () => {
    search = new URLSearchParams("tab=moj-miesiac");
    render(wrap(<MyWhoCountsSection />));
    expect(screen.queryByText(LIST)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Kto się liczy do celów/ }));
    expect(screen.getByText(LIST)).toBeTruthy();
  });

  it("link kliknięty, gdy ekran już stoi otwarty, też rozwija listę", () => {
    search = new URLSearchParams("tab=moj-miesiac");
    const { rerender } = render(wrap(<MyWhoCountsSection />));
    expect(screen.queryByText(LIST)).toBeNull();
    search = new URLSearchParams("tab=moj-miesiac&kto=weryfikacje");
    rerender(wrap(<MyWhoCountsSection />));
    expect(screen.getByText(LIST)).toBeTruthy();
  });
});
