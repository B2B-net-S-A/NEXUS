import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/payroll",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { NextYearBanner } from "@/components/accounting/payroll/NextYearNotice";
import { PayrollView } from "@/components/accounting/payroll/PayrollView";
import {
  NEXT_YEAR_DRAFT_HREF,
  nextYearSummary,
  nextYearTitle,
  wantsNextYearDraft,
  withoutDraftParam,
} from "@/components/accounting/payroll/parameters-model";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { NextYearGap, ParametersOverview, ParamCatalogItem } from "@/lib/api/payroll-lists";
import { useAuthStore } from "@/store/auth";

import { month } from "./payroll-fixtures";

const CATALOG: ParamCatalogItem[] = [
  { key: "minimum_wage", label: "Minimalne wynagrodzenie", group: "Płaca minimalna", unit: "zł", min: "100", max: "100000", integer: "0" },
  { key: "minimum_hourly_rate", label: "Minimalna stawka godzinowa", group: "Płaca minimalna", unit: "zł", min: "1", max: "1000", integer: "0" },
  {
    key: "annual_pension_limit",
    label: "Roczny limit podstawy emerytalnej i rentowych (30-krotność)",
    group: "ZUS",
    unit: "zł",
    min: "1000",
    max: "10000000",
    integer: "0",
  },
  { key: "pit_threshold", label: "Próg skali PIT (rocznie)", group: "PIT", unit: "zł", min: "1000", max: "10000000", integer: "0" },
];

const CURRENT = { minimum_wage: "4806.00", minimum_hourly_rate: "31.40", annual_pension_limit: "282600.00", pit_threshold: "120000.00" };

const MINIMUM = {
  source: "Dz.U. 2026 poz. 1213 (rozporządzenie RM z 14.09.2026)",
  url: "https://api.sejm.gov.pl/eli/acts/DU/2026/1213",
  published: "2026-09-15",
};

const GAP: NextYearGap = {
  year: 2027,
  effective_from: "2027-01-01",
  base_effective_from: "2026-01-01",
  params: { ...CURRENT, minimum_wage: "4950.00", minimum_hourly_rate: "32.30", annual_pension_limit: "300990.00" },
  known: [
    { key: "minimum_wage", label: "Minimalne wynagrodzenie", unit: "zł", value: "4950.00", before: "4806.00", ...MINIMUM },
    { key: "minimum_hourly_rate", label: "Minimalna stawka godzinowa", unit: "zł", value: "32.30", before: "31.40", ...MINIMUM },
    {
      key: "annual_pension_limit",
      label: "Roczny limit podstawy emerytalnej i rentowych (30-krotność)",
      unit: "zł",
      value: "300990.00",
      before: "282600.00",
      source: "M.P. 2026 poz. 1098 (obwieszczenie MRPiPS z 3.11.2026)",
      url: "https://api.sejm.gov.pl/eli/acts/MP/2026/1098",
      published: "2026-11-04",
    },
  ],
  unchanged_note: "Pozostałe parametry są przepisane z bieżącej wersji. Progi i kwoty PIT na 2027 nie są jeszcze pewne.",
  note: "Parametry od 01.01.2027. minimalne wynagrodzenie, minimalna stawka godzinowa: Dz.U. 2026 poz. 1213; roczny limit podstawy emerytalnej i rentowych: M.P. 2026 poz. 1098.",
};

function overview(gap: NextYearGap | null): ParametersOverview {
  return {
    catalog: CATALOG,
    current_id: 1,
    next_year: gap,
    versions: [
      {
        id: 1,
        effective_from: "2026-01-01",
        status: "confirmed",
        source: "seed",
        note: null,
        params: CURRENT,
        created_at: "2026-11-14T10:00:00",
        confirmed_at: "2026-11-14T11:00:00",
        replaced_at: null,
        live: true,
        in_use: false,
        changes: [],
      },
    ],
  };
}

function config(): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "payroll", label: "Lista płac — ZUS, PIT", replaces: "Enova 365", stage: "K7", built: true, enabled: true, open: true },
    ],
    me: { admin: false, approver: false, payroll: true },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: {
      settlement_account: "490",
      client_account: "501",
      front_office_account: "502",
      back_office_account: "503",
      overhead_account: "550",
      team_account: "504",
    },
    years: [],
    today: "2026-12-15",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  };
}

function route(gap: NextYearGap | null) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: config() };
    if (url === "/api/hr/payroll-lists/parameters") return { data: overview(gap) };
    if (url === "/api/hr/payroll-lists/months/2026/12") return { data: month({ year: 2026, month: 12, list: null }) };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderPayroll() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <PayrollView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  useAuthStore.setState({ user: { id: 5, role: "finance", roles: ["finance"] }, realUser: null, hydrated: true } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("strażnik parametrów płac na 1 stycznia — model", () => {
  it("tytuł, zdanie z wartościami wstępnymi i adres szkicu", () => {
    expect(nextYearTitle(GAP)).toBe("Brak parametrów płac od 01.01.2027");
    const summary = nextYearSummary(GAP);
    expect(summary).toContain("minimalne wynagrodzenie 4 950,00 zł");
    expect(summary).toContain("minimalna stawka godzinowa 32,30 zł");
    expect(summary).toContain("roczny limit podstawy emerytalnej i rentowych 300 990,00 zł");
    expect(summary).toContain("z wersji od 01.01.2026");
    expect(summary).toContain("Nic nie zapisze się samo");
    expect(wantsNextYearDraft(NEXT_YEAR_DRAFT_HREF.split("?")[1])).toBe(true);
    expect(wantsNextYearDraft("?view=parameters")).toBe(false);
    expect(withoutDraftParam("?view=parameters&draft=next-year")).toBe("?view=parameters");
    expect(withoutDraftParam("?draft=next-year")).toBe("");
  });
});

describe("strażnik parametrów płac na 1 stycznia — ekrany", () => {
  it("bez luki ekran parametrów nie pokazuje komunikatu", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=12&view=parameters");
    route(null);
    renderPayroll();
    expect(await screen.findByText("Parametry płac od 01.01.2026")).toBeInTheDocument();
    expect(screen.queryByText(/Brak parametrów płac od/)).not.toBeInTheDocument();
  });

  it("przycisk otwiera szkic z wartościami 2027 i źródłami; zapis dopiero po kliknięciu, bez potwierdzenia", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=12&view=parameters");
    route(GAP);
    post.mockResolvedValue({ data: overview(null) });
    const user = userEvent.setup();
    renderPayroll();

    const notice = (await screen.findByText("Brak parametrów płac od 01.01.2027")).closest<HTMLElement>('[role="status"]')!;
    await user.click(within(notice).getByRole("button", { name: "Otwórz szkic od 01.01.2027" }));

    expect(screen.getByLabelText("Nowa wersja od")).toHaveValue("2027-01");
    expect(screen.getByLabelText("Minimalne wynagrodzenie")).toHaveValue("4950");
    expect(screen.getByLabelText("Minimalna stawka godzinowa")).toHaveValue("32,3");
    expect(screen.getByLabelText("Roczny limit podstawy emerytalnej i rentowych (30-krotność)")).toHaveValue("300990");
    expect(screen.getByLabelText("Próg skali PIT (rocznie)")).toHaveValue("120000");
    expect(screen.getByLabelText("Uwaga do wersji")).toHaveValue(GAP.note);
    const source = screen.getByTestId("source-minimum_wage");
    expect(within(source).getByRole("link", { name: MINIMUM.source })).toHaveAttribute("href", MINIMUM.url);
    expect(source).toHaveTextContent("ogłoszono 15.09.2026 · było 4 806,00 zł");
    expect(screen.queryByTestId("source-pit_threshold")).not.toBeInTheDocument();
    expect(screen.getByText(/Progi i kwoty PIT na 2027 nie są jeszcze pewne/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Zapisz wersję" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/api/hr/payroll-lists/parameters", {
      effective_from: "2027-01-01",
      params: { minimum_wage: "4950", minimum_hourly_rate: "32.3", annual_pension_limit: "300990", pit_threshold: "120000" },
      note: GAP.note,
    });
    expect(post.mock.calls.some(([url]) => String(url).includes("/confirm"))).toBe(false);
    await waitFor(() => expect(screen.queryByText(/Brak parametrów płac od/)).not.toBeInTheDocument());
  });

  it("ekran miesiąca listy płac pokazuje komunikat i przełącza na szkic w „Parametrach”", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=12");
    route(GAP);
    const user = userEvent.setup();
    renderPayroll();
    expect(await screen.findByText("Brak parametrów płac od 01.01.2027")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Otwórz szkic od 01.01.2027" }));
    expect(await screen.findByLabelText("Minimalne wynagrodzenie")).toHaveValue("4950");
    expect(window.location.search).toContain("view=parameters");
    expect(window.location.search).not.toContain("draft=");
    expect(screen.getByText("Szkic otwarty niżej — sprawdź i zapisz.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("adres ze szkicem otwiera formularz od razu", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=12&view=parameters&draft=next-year");
    route(GAP);
    renderPayroll();
    expect(await screen.findByLabelText("Minimalne wynagrodzenie")).toHaveValue("4950");
    expect(window.location.search).not.toContain("draft=");
  });

  it("baner na Ludzie → Rozliczenia linkuje do szkicu; bez uprawnienia nie pyta serwera", async () => {
    route(GAP);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={client}>
        <NextYearBanner />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "Otwórz szkic od 01.01.2027" })).toHaveAttribute(
      "href",
      NEXT_YEAR_DRAFT_HREF,
    );
    unmount();
    get.mockClear();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NextYearBanner enabled={false} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText(/Brak parametrów płac/)).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });
});
