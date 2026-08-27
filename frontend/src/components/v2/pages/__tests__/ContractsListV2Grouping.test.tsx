import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { useAuthStore } from "@/store/auth";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: {},
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

function renderList(navigationSearch?: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const result = render(
    <QueryClientProvider client={qc}>
      <ContractsListV2 navigationSearch={navigationSearch} />
    </QueryClientProvider>,
  );
  return { ...result, queryClient: qc };
}

const groupedMember = (over: Record<string, unknown>) => ({
  client_name: null,
  job_title: null,
  start_date: "2026-07-01",
  end_date: "2026-09-30",
  latest_order_end_date: null,
  contract_type: "b2b",
  rate_candidate: 125,
  rate_client: 175,
  margin: 50,
  rate_unit: "hourly",
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  status: "active",
  ...over,
});

/**
 * Konsolidacja kontraktorów wieloklientowych: lista prosi backend o grupowanie
 * po osobie i renderuje wiersz zgrupowany z rozbiciem per klient. Kolumna
 * „Stawka klient" nazywa się teraz „Stawka przychodowa", a obok stoi nowa
 * „Stawka kosztowa".
 */
describe("ContractsListV2 — grupowanie per osoba + kolumny stawek", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
    window.sessionStorage.clear();
    useAuthStore.setState({
      user: {
        id: 1,
        email: "admin@example.com",
        name: "Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance"],
        analytics_capabilities: ["view_finance"],
      },
      hydrated: true,
    });
    getMock.mockReset();
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: 467,
                candidate_id: 10,
                candidate_name: "Paweł Małek",
                client_name: "Bank Pocztowy",
                status: "active",
                contract_type: "b2b",
                start_date: "2026-07-01",
                end_date: "2026-09-30",
                rate_candidate: 125,
                rate_client: 175,
                margin: 50,
                currency: "PLN",
                group_members: [
                  groupedMember({
                    id: 467,
                    client_id: 1,
                    client_name: "Bank Pocztowy",
                    rate_client_currency: "EUR",
                    rate_candidate_currency: "PLN",
                    margin: null,
                  }),
                  groupedMember({
                    id: 512,
                    client_id: 2,
                    client_name: "VeloBank",
                    rate_candidate: 120,
                    rate_client: 162.5,
                    margin: 42.5,
                    end_date: null,
                  }),
                ],
              },
              {
                id: 300,
                candidate_id: 11,
                candidate_name: "Jan Solo",
                client_name: "Trzeci Klient",
                status: "active",
                contract_type: "b2b",
                start_date: "2026-01-01",
                end_date: "2026-09-30",
                rate_candidate: 100,
                rate_client: 140,
                margin: 40,
                currency: "PLN",
                group_members: [
                  groupedMember({
                    id: 300,
                    client_id: 3,
                    client_name: "Trzeci Klient",
                    rate_candidate: 100,
                    rate_client: 140,
                    margin: 40,
                  }),
                ],
              },
            ],
            total: 2,
            contractors_total: 2,
            contracts_total: 3,
            page: 1,
            page_size: 20,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, hydrated: true });
    vi.restoreAllMocks();
  });

  it("prosi backend o grupowanie po osobie (group_by_candidate)", async () => {
    renderList();
    await waitFor(() =>
      expect(
        getMock.mock.calls.some((c) => c[0] === "/api/contracts"),
      ).toBe(true),
    );
    const call = getMock.mock.calls.find((c) => c[0] === "/api/contracts");
    expect(call?.[1]).toMatchObject({
      params: expect.objectContaining({
        group_by_candidate: true,
        status: ["active"],
      }),
    });
    expect(window.location.search).toBe("?status=active");
  });

  it("koduje pełny return target w linkach do profilu", async () => {
    window.history.replaceState(
      {},
      "",
      "/contracts?status=draft&contract_type=b2b&page=2",
    );
    renderList();

    const link = await screen.findByRole("link", { name: "Paweł Małek" });
    expect(link.getAttribute("href")).toContain(
      "returnTo=%2Fcontracts%3Fstatus%3Ddraft%26contract_type%3Db2b%26page%3D2",
    );
  });

  it("resetuje filtr do Aktywnego przy ponownym wejściu queryless bez remountu", async () => {
    window.history.replaceState({}, "", "/contracts?status=draft");
    const view = renderList("status=draft");
    await waitFor(() =>
      expect(
        getMock.mock.calls.some(
          (call) => call[0] === "/api/contracts" && call[1]?.params?.status?.[0] === "draft",
        ),
      ).toBe(true),
    );

    window.history.replaceState({}, "", "/contracts");
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <ContractsListV2 navigationSearch="" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(
        getMock.mock.calls.some(
          (call) => call[0] === "/api/contracts" && call[1]?.params?.status?.[0] === "active",
        ),
      ).toBe(true),
    );
    expect(window.location.search).toBe("?status=active");
  });

  it("nagłówki: Stawka kosztowa + Stawka przychodowa, bez dawnej Stawka klient", async () => {
    renderList();
    await screen.findByText("Paweł Małek");
    expect(screen.getByText("Stawka kosztowa")).toBeInTheDocument();
    expect(screen.getByText("Stawka przychodowa")).toBeInTheDocument();
    expect(screen.queryByText("Stawka klient")).not.toBeInTheDocument();
  });

  it("osoba u 2 klientów = JEDEN wiersz z rozbiciem per klient", async () => {
    renderList();
    await screen.findByText("Paweł Małek");

    expect(
      screen.getByText(/2 kontraktorów \/ 3 aktywne kontrakty/i),
    ).toBeInTheDocument();

    // Obaj klienci w kolumnie „Klient" + adnotacja o wieloklientowości.
    expect(screen.getByText("Bank Pocztowy")).toBeInTheDocument();
    expect(screen.getByText("VeloBank")).toBeInTheDocument();
    expect(screen.getByText(/pracuje u 2 klientów/i)).toBeInTheDocument();
    expect(screen.getByText("Paweł Małek").closest("tr")).toHaveTextContent(
      /VeloBank:.*bezterminowo/i,
    );

    // Rozbicie stawek per klient: prefiks z nazwą klienta w komórkach kwotowych
    // (memberLines renderuje „Bank Pocztowy: " i „VeloBank: " per linia w
    // czterech kolumnach: daty, kosztowa, przychodowa, marża).
    expect(screen.getAllByText(/Bank Pocztowy:/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/VeloBank:/).length).toBeGreaterThanOrEqual(3);

    // Osoba jednoklientowa renderuje się po staremu (bez prefiksów).
    expect(screen.getByText("Jan Solo")).toBeInTheDocument();
    expect(screen.queryByText(/Trzeci Klient:/)).not.toBeInTheDocument();
  });

  it("formatuje stawkę kosztową i przychodową ich własnymi walutami", async () => {
    renderList();
    const row = (await screen.findByText("Paweł Małek")).closest("tr");

    expect(row).toHaveTextContent("125,00 zł");
    expect(row).toHaveTextContent("175,00 €");
    // Backend zwraca null dla marży w różnych walutach; lista nie podstawia
    // wspólnej waluty i nie pokazuje pozornie porównywalnej kwoty.
    expect(row).toHaveTextContent(/Bank Pocztowy: —/);
  });

  it("dla statusu innego niż aktywny używa neutralnych nazw liczników", async () => {
    renderList("status=draft");

    expect(await screen.findByText(/2 osoby \/ 3 kontrakty/i)).toBeInTheDocument();
    expect(screen.queryByText(/aktywne kontrakty/i)).not.toBeInTheDocument();
  });
});
