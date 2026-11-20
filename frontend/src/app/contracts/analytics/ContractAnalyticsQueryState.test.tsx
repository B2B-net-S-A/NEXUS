/**
 * /contracts/analytics: nieudane pobranie marży NIE może wyglądać jak zero.
 *
 * To ekran, na którym admin odpowiada sobie na pytanie „ile zarabiamy w tym
 * miesiącu". Do sierpnia 2026 żadne z siedmiu zapytań nie czytało `isError`,
 * a `(byClient ?? []).reduce(...)` zwijał 500/403/timeout w pewne siebie
 * „0,00 zł" na kaflach marży i przychodu.
 *
 * 20.11.2026 ekran przeszedł na wariant A z tabelą z B (cztery liczby,
 * „Najbliższe 3 miesiące”, linia prognozy, tabela „Kto ile przynosi”,
 * zwinięte zestawienia). Testy sprawdzają te same reguły w nowym układzie:
 * etykiety liczb, procent po polsku („20,0 %”) i miejsce macierzy się zmieniły.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), expansion: vi.fn() }));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  contractAnalyticsExpansionApi: {
    roleClientMix: () => mocks.expansion("roleClientMix"),
    locationDistribution: () => mocks.expansion("locationDistribution"),
    terminationAnalysis: () => mocks.expansion("terminationAnalysis"),
  },
  CONTRACT_TERMINATION_REASONS: [{ value: "project_ended", label: "Koniec projektu" }],
}));

// Bramka sekcji strony nie jest przedmiotem tego testu.
vi.mock("@/components/RequirePermission", () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/lib/warsaw-date", () => ({ warsawToday: () => "2026-11-20" }));

import ContractAnalyticsPage from "@/app/contracts/analytics/page";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractAnalyticsPage />
    </QueryClientProvider>,
  );
}

/** Tekst bez spacji twardych z formatowania kwot. */
function plain(element: Element | null): string {
  return (element?.textContent ?? "").replace(/ /g, " ");
}

/** Karta liczby: etykieta i to, co pod nią (wartość, zdanie). */
function figure(label: string): HTMLElement {
  const node = screen.getByText(label).parentElement;
  if (!node) throw new Error(`Brak liczby ${label}`);
  return node;
}

const EMPTY_WINDOW = { items: [], total: 0 };

type Routes = Record<string, () => Promise<unknown>>;

/** Odpowiedzi API po fragmencie adresu; reszta — puste okno albo pusta prognoza. */
function routes(map: Routes) {
  mocks.get.mockImplementation((url: string) => {
    for (const [fragment, respond] of Object.entries(map)) {
      if (url.includes(fragment)) return respond();
    }
    if (url === "/api/contracts") return Promise.resolve({ data: EMPTY_WINDOW });
    if (url.includes("margin-by")) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: { horizon_months: 12, months: [] } });
  });
}

const ok = (data: unknown) => () => Promise.resolve({ data });
const fail = (status: number) => () => Promise.reject(httpError(status));

beforeEach(() => {
  mocks.get.mockReset();
  mocks.expansion.mockReset();
  mocks.expansion.mockRejectedValue(httpError(500));
});

describe("ContractAnalyticsPage — liczby pieniężne", () => {
  it("gdy margin-totals pada, marża i przychód pokazują „—”, nie 0 zł", async () => {
    routes({
      "margin-totals": fail(500),
      "margin-by-client": fail(500),
      utilization: fail(500),
    });

    renderPage();

    expect(await screen.findByText("Nie udało się pobrać marży")).toBeInTheDocument();
    expect(screen.getByText("Nie udało się pobrać przychodu")).toBeInTheDocument();
    expect(plain(figure("Marża miesięcznie"))).toContain("—");
    // Regresja byłaby CICHA: sformatowane zero jest nieodróżnialne od wyniku.
    expect(screen.queryByText(/^0 zł$/)).not.toBeInTheDocument();
    expect(plain(document.body)).not.toMatch(/\b0,00\b/);
  });

  it("liczby biorą sumy z margin-totals, nie z przyciętego rankingu", async () => {
    routes({
      // Sumy firmowe są WIĘKSZE niż to, co widać w rankingu obok (audyt
      // 18.09.2026 — z kafla przychodu znikało 217 060 zł).
      "margin-totals": ok({
        clients: 30,
        active_contracts: 40,
        total_monthly_margin: 1000,
        total_monthly_revenue: 5000,
        margin_pct: 20,
        fx_missing: false,
      }),
      "margin-by-client": ok([
        {
          client_id: 1,
          client_name: "Klient Alfa",
          active_contracts: 2,
          total_monthly_margin: 111,
          total_monthly_revenue: 222,
          margin_pct: 50,
        },
      ]),
      utilization: ok({
        total_candidates: 10,
        candidates_active: 4,
        active_contracts: 6,
        candidates_on_bench: 6,
        utilization_pct: 40,
        avg_bench_days: 12,
      }),
    });

    renderPage();

    await waitFor(() => expect(plain(figure("Marża miesięcznie"))).toContain("20,0 % z przychodu"));
    expect(screen.queryByText("Nie udało się pobrać marży")).not.toBeInTheDocument();
    // Regresja byłaby cicha: suma policzona z listy dałaby 111 / 222 zł.
    expect(plain(figure("Marża miesięcznie"))).toContain("1 000 zł");
    expect(plain(figure("Przychód miesięcznie"))).toContain("5 000 zł");
    expect(plain(figure("Przychód miesięcznie"))).toContain("40 kontraktów u 30 klientów");
    expect(plain(figure("Utylizacja"))).toContain("40,0 %");
    expect(plain(figure("Na ławce"))).toContain("6 osób");
    expect(plain(figure("Na ławce"))).toContain("średnio 12 dni bez kontraktu");
    // Wiersz „Razem” tabeli też idzie z sum firmy, nie z wierszy.
    const totalRow = screen.getByText("Razem").closest("tr");
    expect(plain(totalRow)).toContain("1 000");
    expect(plain(totalRow)).toContain("30 klientów z aktywnym kontraktem");
  });
});

describe("ContractAnalyticsPage — marża bez stawki kosztowej", () => {
  it("procent marży idzie z serwera, a liczba mówi o kontraktach bez kosztu", async () => {
    // Serwer liczy procent z przychodu kontraktów o ZNANEJ marży (33,3%),
    // a dzielenie marży przez przychód dałoby 25% (audyt 24.09.2026).
    routes({
      "margin-totals": ok({
        clients: 1,
        active_contracts: 2,
        total_monthly_margin: 1000,
        total_monthly_revenue: 4000,
        margin_pct: 33.3,
        fx_missing: false,
        contracts_without_cost_leg: 1,
      }),
      utilization: fail(500),
    });

    renderPage();

    await waitFor(() =>
      expect(plain(figure("Marża miesięcznie"))).toContain(
        "33,3 % z przychodu · 1 kontrakt bez stawki kosztowej poza marżą",
      ),
    );
    expect(plain(document.body)).not.toMatch(/25,0 % z przychodu/);
    expect(screen.getByText("Nie udało się pobrać utylizacji")).toBeInTheDocument();
  });
});

describe("ContractAnalyticsPage — kontrakty bez stawki przychodowej (runda 10)", () => {
  it("liczby i wiersz mówią, że suma pomija kontrakty bez stawki przychodowej", async () => {
    routes({
      "margin-totals": ok({
        clients: 1,
        active_contracts: 1,
        total_monthly_margin: 0,
        total_monthly_revenue: 0,
        margin_pct: null,
        fx_missing: false,
        contracts_without_cost_leg: 0,
        contracts_without_revenue_leg: 1,
      }),
      "margin-by-client": ok([
        {
          client_id: 7,
          client_name: "Klient bez zamówienia",
          active_contracts: 1,
          total_monthly_margin: 0,
          total_monthly_revenue: 0,
          margin_pct: null,
          fx_missing: false,
          contracts_without_revenue_leg: 1,
        },
      ]),
      utilization: fail(500),
    });

    renderPage();

    const note = "Niepełne: 1 kontrakt bez stawki przychodowej poza sumą";
    // Liczba marży i liczba przychodu — obie podpisane.
    expect(await screen.findAllByText(note)).toHaveLength(2);
    const row = screen.getByRole("link", { name: "Klient bez zamówienia" }).closest("tr");
    expect(row).toHaveTextContent("Niepełne");
  });
});

describe("ContractAnalyticsPage — degradacja kursów FX", () => {
  it("oznacza zdegradowane wiersze i nie sumuje ich jak kompletnych kwot", async () => {
    routes({
      "margin-totals": ok({
        clients: 2,
        active_contracts: 2,
        total_monthly_margin: 1099,
        total_monthly_revenue: 5499,
        margin_pct: 20,
        fx_missing: true,
      }),
      "margin-by-client": ok([
        {
          client_id: 1,
          client_name: "Klient kompletny",
          active_contracts: 1,
          total_monthly_margin: 100,
          total_monthly_revenue: 500,
          margin_pct: 20,
          fx_missing: false,
        },
        {
          client_id: 2,
          client_name: "Klient bez kursu",
          active_contracts: 1,
          // Backend zwraca sumę dostępnych nóg, ale nie jest to pełna kwota.
          total_monthly_margin: 999,
          total_monthly_revenue: 4999,
          margin_pct: 20,
          fx_missing: true,
        },
      ]),
      utilization: ok({
        total_candidates: 2,
        candidates_active: 2,
        active_contracts: 2,
        candidates_on_bench: 0,
        utilization_pct: 100,
        avg_bench_days: null,
      }),
    });

    renderPage();

    expect(await screen.findByText(/Dane finansowe są niepełne/i)).toBeInTheDocument();
    expect(plain(figure("Marża miesięcznie"))).toBe("Marża miesięcznie—Niepełne dane — brak kursu FX");
    expect(plain(figure("Przychód miesięcznie"))).toBe("Przychód miesięcznie—Niepełne dane — brak kursu FX");

    const degradedRow = screen.getByRole("link", { name: "Klient bez kursu" }).closest("tr");
    expect(degradedRow).not.toBeNull();
    expect(degradedRow).toHaveTextContent("Brak kursu FX");
    // Kontrakty, przychód, marża, marża % (kolumny 90 dni dochodzą po nich).
    expect(
      within(degradedRow as HTMLTableRowElement)
        .getAllByRole("cell")
        .slice(2, 5)
        .map((cell) => cell.textContent),
    ).toEqual(["—", "—", "—"]);
    expect(degradedRow).not.toHaveTextContent("4999");
    expect(plain(degradedRow)).not.toContain("4 999");
    // Suma też nie udaje kompletnej.
    const totalRow = screen.getByText("Razem").closest("tr");
    expect(plain(totalRow)).not.toContain("1 099");
  });

  it("fx_warnings z backendu jest widoczne nad linią prognozy, miesiące po polsku", async () => {
    const warning = "Brak kursu NBP dla walut: EUR — kwoty w tych walutach POMINIĘTE w prognozie";
    routes({
      "revenue-forecast": ok({
        horizon_months: 12,
        months: [
          { month: "2026-09", month_label: "Sep 2026", revenue: 100, margin: 10, active_count: 1 },
          { month: "2026-10", month_label: "Oct 2026", revenue: 120, margin: 12, active_count: 2 },
        ],
        fx_missing: true,
        fx_warnings: [warning],
      }),
    });

    renderPage();

    // Bez tego prognoza, która wyrzuciła kontrakty w EUR/USD, wyglądała na kompletną.
    expect(await screen.findByText(warning)).toBeInTheDocument();
    // UAT M08-B06: etykiety po polsku, nie „Sep 2026” i „cnt” z backendu.
    const table = screen.getByRole("table", { name: /Prognoza marży i przychodu/ });
    expect(within(table).getByText("wrz 2026")).toBeInTheDocument();
    expect(within(table).getByText("1 kontrakt")).toBeInTheDocument();
    expect(within(table).getByText("2 kontrakty")).toBeInTheDocument();
    expect(screen.queryByText("Sep 2026")).toBeNull();
    expect(screen.queryByText(/\bcnt\b/)).toBeNull();
  });

  it("awaria prognozy to stan błędu z ponowieniem, nie „brak kontraktów”", async () => {
    routes({ "revenue-forecast": fail(500) });

    renderPage();

    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText(/nie ma czego prognozować/)).not.toBeInTheDocument();
  });
});

const WINDOW_ITEM = {
  candidate_name: "Anna Przykładowa",
  client_id: 1,
  client_name: "Klient Alfa",
  rate_client: 150,
  rate_candidate: 110,
  margin: 40,
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  rate_unit: "hourly",
  billing_hours_per_month: 168,
  termination_reason: null,
  prolongation_status: "unknown",
};

describe("ContractAnalyticsPage — najbliższe 3 miesiące", () => {
  function windowRoutes(ending: unknown, starting: unknown) {
    mocks.get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === "/api/contracts") {
        return config?.params?.expiring_in_days ? ending() : starting();
      }
      if (url.includes("margin-totals")) {
        return Promise.resolve({
          data: {
            clients: 1,
            active_contracts: 1,
            total_monthly_margin: 10000,
            total_monthly_revenue: 40000,
            margin_pct: 25,
            fx_missing: false,
          },
        });
      }
      if (url.includes("margin-by-client")) {
        return Promise.resolve({
          data: [
            {
              client_id: 1,
              client_name: "Klient Alfa",
              active_contracts: 1,
              total_monthly_margin: 10000,
              total_monthly_revenue: 40000,
              margin_pct: 25,
            },
          ],
        });
      }
      if (url.includes("margin-by")) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });
  }

  it("pyta listę kontraktów tymi samymi filtrami co /contracts i liczy bilans marży w PLN", async () => {
    windowRoutes(
      ok({
        items: [
          { ...WINDOW_ITEM, id: 1, candidate_id: 10, end_date: "2026-12-31", termination_reason: "project_ended" },
          // Kontrakt w EUR nie wchodzi do sumy bez przeliczenia.
          { ...WINDOW_ITEM, id: 2, candidate_id: 11, end_date: "2026-12-15", rate_client_currency: "EUR", rate_candidate_currency: "EUR" },
        ],
        total: 2,
      }),
      ok({
        items: [{ ...WINDOW_ITEM, id: 3, candidate_id: 12, client_id: 5, client_name: "Klient Nowy", start_date: "2026-12-01", margin: 50 }],
        total: 1,
      }),
    );

    renderPage();

    const section = await screen.findByRole("region", { name: "Najbliższe 3 miesiące" });
    await waitFor(() => expect(plain(section)).toContain("Bilans marży: +1 680 zł / mies."));
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/contracts",
      expect.objectContaining({
        params: { status: ["active", "ending"], page_size: 100, expiring_in_days: 90 },
      }),
    );
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/contracts",
      expect.objectContaining({
        params: { status: ["active", "ending"], page_size: 100, start_from: "2026-11-21", start_to: "2027-02-18" },
      }),
    );
    expect(plain(section)).toContain("2 osoby");
    expect(plain(section)).toContain("−6 720 zł marży / mies.");
    expect(plain(section)).toContain("1 kontrakt w innej walucie — poza sumą");
    expect(plain(section)).toContain("koniec projektu");
    // Klient tylko ze startem ma własny wiersz w tabeli.
    const newClient = screen.getByRole("link", { name: "Klient Nowy" }).closest("tr");
    expect(newClient).toHaveTextContent("dziś bez aktywnego kontraktu");
    expect(plain(newClient)).toContain("+8 400");
  });

  it("brak uprawnienia do listy kontraktów to zdanie, nie pusta lista; tabela zostaje bez kolumn 90 dni", async () => {
    windowRoutes(fail(403), fail(403));

    renderPage();

    expect(
      await screen.findAllByText("Lista kontraktów wymaga uprawnienia „Klienci, kontrakty i zamówienia: podgląd”."),
    ).toHaveLength(2);
    expect(screen.queryByText(/Nikomu nie kończy się umowa/)).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Klient Alfa" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Kończą się/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Kolumny „Kończą się” i „Startują” są ukryte/)).toBeInTheDocument();
  });

  it("puste okno mówi jednym zdaniem, że nic się nie zmienia", async () => {
    windowRoutes(ok(EMPTY_WINDOW), ok(EMPTY_WINDOW));

    renderPage();

    expect(await screen.findByText("Nikomu nie kończy się umowa w najbliższych 90 dniach.")).toBeInTheDocument();
    expect(screen.getByText("W najbliższych 90 dniach nie startuje żadna umowa.")).toBeInTheDocument();
  });
});

describe("ContractAnalyticsPage — tabela „Kto ile przynosi”", () => {
  it("sortuje kliknięciem w nagłówek i pokazuje strzałkę przy aktywnej kolumnie", async () => {
    routes({
      "margin-totals": ok({
        clients: 2,
        active_contracts: 3,
        total_monthly_margin: 3000,
        total_monthly_revenue: 12000,
        margin_pct: 25,
        fx_missing: false,
      }),
      "margin-by-client": ok([
        { client_id: 1, client_name: "Beta", active_contracts: 1, total_monthly_margin: 1000, total_monthly_revenue: 4000, margin_pct: 25 },
        { client_id: 2, client_name: "Alfa", active_contracts: 2, total_monthly_margin: 2000, total_monthly_revenue: 8000, margin_pct: 25 },
      ]),
    });
    const user = userEvent.setup({ delay: null });

    renderPage();

    const report = await screen.findByRole("region", { name: "Kto ile przynosi" });
    await within(report).findByRole("link", { name: "Alfa" });
    const names = () =>
      within(report)
        .getAllByRole("link")
        .map((a) => a.textContent);
    expect(names()).toEqual(["Alfa", "Beta"]);
    expect(within(report).getByRole("columnheader", { name: /Marża\s*zł \/ mies\./ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );

    await user.click(within(report).getByRole("button", { name: /^Klient/ }));
    expect(names()).toEqual(["Alfa", "Beta"]);
    await user.click(within(report).getByRole("button", { name: /^Klient/ }));
    expect(names()).toEqual(["Beta", "Alfa"]);
    expect(within(report).getByRole("columnheader", { name: /^Klient/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("„Konsultanci” pobiera ranking osób dopiero po przełączeniu", async () => {
    routes({
      "margin-totals": ok({
        clients: 1,
        active_contracts: 1,
        total_monthly_margin: 1000,
        total_monthly_revenue: 4000,
        margin_pct: 25,
        fx_missing: false,
      }),
      "margin-by-contractor": ok([
        { candidate_id: 9, candidate_name: "Jan Testowy", active_contracts: 1, total_monthly_margin: 1000, total_monthly_revenue: 4000, margin_pct: 25 },
      ]),
    });
    const user = userEvent.setup({ delay: null });

    renderPage();

    await screen.findByRole("region", { name: "Kto ile przynosi" });
    expect(mocks.get).not.toHaveBeenCalledWith("/api/contract-analytics/margin-by-contractor", expect.anything());
    await user.click(screen.getByRole("radio", { name: "Konsultanci" }));

    expect(await screen.findByRole("link", { name: "Jan Testowy" })).toHaveAttribute("href", "/candidates/9");
    expect(mocks.get).toHaveBeenCalledWith("/api/contract-analytics/margin-by-contractor", {
      params: { limit: 100 },
    });
  });
});

describe("ContractAnalyticsPage — macierz rola × klient", () => {
  it("zwinięta na dole; po rozwinięciu Σ używa unikalnych osób per rola", async () => {
    routes({});
    mocks.expansion.mockImplementation((name: string) => {
      if (name === "roleClientMix") {
        return Promise.resolve({
          data: {
            total_active: 1,
            total_active_contracts: 2,
            role_totals: { Developer: 1 },
            rows: [
              { role: "Developer", client_id: 1, client_name: "Client A", active_count: 1, pct_of_total: 100 },
              { role: "Developer", client_id: 2, client_name: "Client B", active_count: 1, pct_of_total: 100 },
            ],
            roles: ["Developer"],
            clients: [
              { id: 1, name: "Client A" },
              { id: 2, name: "Client B" },
            ],
          },
        });
      }
      return Promise.reject(httpError(500));
    });
    const user = userEvent.setup({ delay: null });

    renderPage();

    const toggle = await screen.findByRole("button", { name: /Rola × klient — szczegóły/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(mocks.expansion).not.toHaveBeenCalled();
    await user.click(toggle);

    expect(await screen.findByText(/1 kontraktor \/ 2 kontrakty/i)).toBeInTheDocument();
    const row = screen.getByText("Developer").closest("tr");
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLTableRowElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["Developer", "1", "1", "1"]);
  });

  it("awaria rzadszego zestawienia to stan błędu, nie znikająca sekcja", async () => {
    routes({});
    const user = userEvent.setup({ delay: null });

    renderPage();

    await user.click(await screen.findByRole("button", { name: /Lokalizacja konsultantów/ }));
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });
});
