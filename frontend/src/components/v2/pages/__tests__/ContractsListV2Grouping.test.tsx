import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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
        status: ["active", "ending"],
      }),
    });
    expect(window.location.search).toBe("?status=active&status=ending");
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

  it("resetuje filtr do obowiązujących przy ponownym wejściu queryless bez remountu", async () => {
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
          (call) =>
            call[0] === "/api/contracts" &&
            call[1]?.params?.status?.join(",") === "active,ending",
        ),
      ).toBe(true),
    );
    expect(window.location.search).toBe("?status=active&status=ending");
  });

  it("ma dokładnie 9 kolumn danych w kolejności priorytetu", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");

    const table = container.querySelector("[data-contracts-responsive-table]");
    expect(table).toBeInTheDocument();
    expect(
      within(table as HTMLElement)
        .getAllByRole("columnheader")
        .map((header) => header.textContent?.replace(/\s+/g, " ").trim()),
    ).toEqual([
      "Kandydat",
      "Klient",
      "Data rozpoczęcia",
      "Data zakończenia zamówienia",
      "Stawka kosztowa",
      "Stawka przychodowa",
      "Marża",
      "Typ",
      "Status",
    ]);
    expect(screen.queryByText("Stawka klient")).not.toBeInTheDocument();
  });

  it("TCM widzi bezpieczny rejestr Delivery bez finansów i operacji", async () => {
    useAuthStore.setState({
      user: {
        id: 9,
        email: "tcm@example.com",
        name: "Talent Community Manager",
        role: "talent_community_manager",
        roles: ["talent_community_manager"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: [],
        analytics_capabilities: [],
      },
      hydrated: true,
    });

    const { container } = renderList();
    await screen.findByText("Paweł Małek");

    expect(
      screen.queryByRole("button", { name: /nowy kontrakt/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /zaznacz widoczne/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Stawka kosztowa")).not.toBeInTheDocument();
    expect(screen.queryByText("Stawka przychodowa")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-contract-member]")).toHaveLength(3);
  });

  it("osoba u 2 klientów ma 2 widoczne pasy bez rozwijania, ze wspólną komórką kandydata", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");

    expect(
      screen.getByText(/2 kontraktorów \/ 3 aktywne kontrakty/i),
    ).toBeInTheDocument();

    const groups = container.querySelectorAll("[data-contract-group]");
    expect(groups).toHaveLength(2);
    const multiGroup = Array.from(groups).find((group) =>
      group.textContent?.includes("Paweł Małek"),
    );
    expect(multiGroup).toBeDefined();

    const memberRows = multiGroup!.querySelectorAll("[data-contract-member]");
    expect(memberRows).toHaveLength(2);
    expect(memberRows[0]).toHaveTextContent("Bank Pocztowy");
    expect(memberRows[1]).toHaveTextContent("VeloBank");
    expect(multiGroup).toHaveTextContent(/pracuje u 2 klientów/i);
    expect(multiGroup!.querySelector("[aria-expanded]")).not.toBeInTheDocument();

    const candidateCell = within(memberRows[0] as HTMLElement)
      .getByRole("link", { name: "Paweł Małek" })
      .closest("td");
    expect(candidateCell).toHaveAttribute("rowspan", "2");
    expect(
      within(memberRows[1] as HTMLElement).queryByText("Paweł Małek"),
    ).not.toBeInTheDocument();

    // Typ i status są danymi konkretnej umowy i pozostają dwiema ostatnimi
    // komórkami każdego pasa.
    const firstMemberCells = within(memberRows[0] as HTMLElement).getAllByRole(
      "cell",
    );
    const secondMemberCells = within(memberRows[1] as HTMLElement).getAllByRole(
      "cell",
    );
    expect(firstMemberCells.slice(-2)[0]).toHaveTextContent("b2b");
    expect(firstMemberCells.slice(-1)[0]).toHaveTextContent("Aktywny");
    expect(secondMemberCells.slice(-2)[0]).toHaveTextContent("b2b");
    expect(secondMemberCells.slice(-1)[0]).toHaveTextContent("Aktywny");
  });

  it("pokazuje daty listy jako dd.mm.yy", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");

    const multiGroup = Array.from(
      container.querySelectorAll("[data-contract-group]"),
    ).find((group) => group.textContent?.includes("Paweł Małek"));
    expect(multiGroup).toBeDefined();
    const rows = multiGroup!.querySelectorAll("[data-contract-member]");
    const startOf = (row: Element) =>
      row.querySelector('[data-label="Data rozpoczęcia"]');
    const orderEndOf = (row: Element) =>
      row.querySelector('[data-label="Data zakończenia zamówienia"]');
    // Data rozpoczęcia i koniec zamówienia to DWIE kolumny; koniec umowy
    // zostaje jako podlinia, żeby wypowiedzenie nie zniknęło z listy.
    expect(startOf(rows[0])).toHaveTextContent(/01\.07\.26/);
    expect(startOf(rows[0])).toHaveTextContent(/umowa do 30\.09\.26/);
    expect(startOf(rows[1])).not.toHaveTextContent(/umowa do/);
    expect(orderEndOf(rows[0])).toHaveTextContent("—");
    expect(multiGroup).not.toHaveTextContent(/2026/);
  });

  it("marża ma tę samą jednostkę co stawki obok (zł/h)", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");
    const margins = Array.from(container.querySelectorAll('[data-label="Marża"]'));
    const priced = margins.find((cell) => /42,50/.test(cell.textContent ?? ""));
    expect(priced).toBeDefined();
    expect(priced).toHaveTextContent(/42,50\s*zł\s*\/h/);
    // Brak marży zostaje kreską — bez samotnej jednostki.
    expect(margins.find((cell) => /—/.test(cell.textContent ?? ""))).not.toHaveTextContent("/h");
  });

  it("koniec zamówienia ma własną kolumnę: data, bezterminowo albo brak", async () => {
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: 700,
                candidate_id: 70,
                candidate_name: "Ola Zamówienie",
                client_name: "Alior",
                status: "active",
                contract_type: "b2b",
                start_date: "2026-01-10",
                end_date: null,
                client_order_start_date: "2026-09-15",
                client_order_end_date: "2026-12-31",
                currency: "PLN",
              },
              {
                id: 701,
                candidate_id: 71,
                candidate_name: "Ewa Bezterminowa",
                client_name: "Nordea",
                status: "active",
                contract_type: "b2b",
                start_date: "2026-02-01",
                end_date: null,
                client_order_start_date: "2026-02-01",
                client_order_end_date: null,
                currency: "PLN",
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
    const { container } = renderList();
    await screen.findByText("Ola Zamówienie");
    const cells = container.querySelectorAll(
      '[data-label="Data zakończenia zamówienia"]',
    );
    expect(cells[0]).toHaveTextContent(/31\.12\.26/);
    expect(cells[0]).toHaveTextContent(/zam\. od 15\.09\.26/);
    expect(cells[1]).toHaveTextContent("bezterminowo");
  });

  it("klik w nagłówek sortuje po stronie serwera i przełącza kierunek", async () => {
    renderList();
    await screen.findByText("Paweł Małek");

    const lastParams = () =>
      (getMock.mock.calls.filter(([url]) => url === "/api/contracts").at(-1)?.[1] as {
        params: Record<string, unknown>;
      }).params;
    expect(lastParams().sort_by).toBeUndefined();

    screen.getByRole("button", { name: "Sortuj: Klient" }).click();
    await waitFor(() => expect(lastParams().sort_by).toBe("client"));
    expect(lastParams().sort_dir).toBe("asc");
    expect(window.location.search).toContain("sort=client");

    screen.getByRole("button", { name: "Sortuj: Klient" }).click();
    await waitFor(() => expect(lastParams().sort_dir).toBe("desc"));
    expect(
      screen.getByRole("button", { name: "Sortuj: Klient" }).closest("th"),
    ).toHaveAttribute("aria-sort", "descending");

    screen.getByRole("button", { name: "Sortuj: Marża" }).click();
    await waitFor(() => expect(lastParams().sort_by).toBe("margin"));
    expect(lastParams().sort_dir).toBe("asc");
    // Status/typ zostają nietknięte — sort działa obok filtrów.
    expect(lastParams().status).toEqual(["active", "ending"]);
  });

  it("filtr dat z adresu trafia do zapytania razem ze statusem", async () => {
    const query =
      "status=active&start_from=2026-01-01&order_end_to=2026-12-31&sort=start_date&dir=desc";
    window.history.replaceState({}, "", `/contracts?${query}`);
    renderList(query);
    await screen.findByText("Paweł Małek");
    const params = (getMock.mock.calls.filter(([url]) => url === "/api/contracts").at(-1)?.[1] as {
      params: Record<string, unknown>;
    }).params;
    expect(params).toMatchObject({
      status: ["active"],
      start_from: "2026-01-01",
      order_end_to: "2026-12-31",
      sort_by: "start_date",
      sort_dir: "desc",
    });
    expect(params.start_to).toBeUndefined();
    expect(
      screen.getByRole("button", { name: /Usuń filtr dat/ }),
    ).toHaveTextContent("Start 01.01.26 – …");
  });

  it("jeden responsywny DOM zachowuje komplet pól każdego klienta", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");

    const table = container.querySelector("[data-contracts-responsive-table]");
    expect(table).toBeInTheDocument();
    expect(
      container.querySelectorAll("[data-contracts-responsive-table]"),
    ).toHaveLength(1);

    const multiGroup = Array.from(
      container.querySelectorAll("[data-contract-group]"),
    ).find((group) => group.textContent?.includes("Paweł Małek"));
    expect(multiGroup).toBeDefined();
    const memberRows = multiGroup!.querySelectorAll("[data-contract-member]");
    const expectedLabels = [
      "Klient",
      "Data rozpoczęcia",
      "Data zakończenia zamówienia",
      "Stawka kosztowa",
      "Stawka przychodowa",
      "Marża",
      "Typ",
      "Status",
    ];

    const clientNames = ["Bank Pocztowy", "VeloBank"];
    for (const [index, row] of Array.from(memberRows).entries()) {
      const labelledCells = Array.from(row.querySelectorAll("td[data-label]"));
      const labels = labelledCells
        .map((cell) => cell.getAttribute("data-label"))
        .filter(
          (label): label is string => Boolean(label) && label !== "Kandydat",
        );
      expect(labels).toEqual(expectedLabels);

      const clientCell = labelledCells.find(
        (cell) => cell.getAttribute("data-label") === "Klient",
      );
      expect(clientCell).toBeDefined();
      expect(clientCell).toHaveTextContent(clientNames[index]);
      for (const cell of labelledCells.filter((item) => item !== clientCell)) {
        expect(cell).not.toHaveTextContent(clientNames[index]);
      }
    }
  });

  it("formatuje stawkę kosztową i przychodową ich własnymi walutami", async () => {
    const { container } = renderList();
    await screen.findByText("Paweł Małek");
    const row = Array.from(
      container.querySelectorAll("[data-contract-member]"),
    ).find((member) => member.textContent?.includes("Bank Pocztowy"));
    expect(row).toBeDefined();

    expect(row).toHaveTextContent("125,00 zł");
    expect(row).toHaveTextContent("175,00 €");
    // Backend zwraca null dla marży w różnych walutach; lista nie podstawia
    // wspólnej waluty i nie pokazuje pozornie porównywalnej kwoty.
    expect(row?.querySelector('[data-label="Marża"]')).toHaveTextContent("—");
  });

  it("dla statusu innego niż aktywny używa neutralnych nazw liczników", async () => {
    renderList("status=draft");

    expect(await screen.findByText(/2 osoby \/ 3 kontrakty/i)).toBeInTheDocument();
    expect(screen.queryByText(/aktywne kontrakty/i)).not.toBeInTheDocument();
  });
});
