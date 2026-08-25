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

function renderList() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ContractsListV2 />
    </QueryClientProvider>,
  );
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
      params: expect.objectContaining({ group_by_candidate: true }),
    });
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

    // Licznik mówi o kontraktorach (grupach), nie o umowach.
    expect(screen.getByText(/2 kontraktorzy w systemie/i)).toBeInTheDocument();

    // Obaj klienci w kolumnie „Klient" + adnotacja o wieloklientowości.
    expect(screen.getByText("Bank Pocztowy")).toBeInTheDocument();
    expect(screen.getByText("VeloBank")).toBeInTheDocument();
    expect(screen.getByText(/pracuje u 2 klientów/i)).toBeInTheDocument();

    // Rozbicie stawek per klient: prefiks z nazwą klienta w komórkach kwotowych
    // (memberLines renderuje „Bank Pocztowy: " i „VeloBank: " per linia w
    // czterech kolumnach: daty, kosztowa, przychodowa, marża).
    expect(screen.getAllByText(/Bank Pocztowy:/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/VeloBank:/).length).toBeGreaterThanOrEqual(3);

    // Osoba jednoklientowa renderuje się po staremu (bez prefiksów).
    expect(screen.getByText("Jan Solo")).toBeInTheDocument();
    expect(screen.queryByText(/Trzeci Klient:/)).not.toBeInTheDocument();
  });
});
