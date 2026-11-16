import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const put = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
const download = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    patch: vi.fn(),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    delete: vi.fn(),
  },
}));
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...a: unknown[]) => download(...a),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/reports",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { ReportsView } from "@/components/accounting/ReportsView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { JpkKrCompareResult, JpkKrOverview } from "@/lib/api/accounting-reports";
import { useAuthStore } from "@/store/auth";

function config(): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "reports", label: "Sprawozdania i CIT", replaces: "Symfonia FK", stage: "K8", built: true, enabled: true, open: true },
    ],
    me: { admin: false, approver: true, payroll: true },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "", front_office_account: "", back_office_account: "", overhead_account: "", team_account: "" },
    years: [
      {
        id: 1,
        year: 2026,
        mode: "symfonia",
        mode_label: "Symfonia FK — NEXUS przygotowuje paczki",
        status: "open",
        journal_entries: 3,
        periods: Array.from({ length: 12 }, (_, index) => ({
          id: 100 + index,
          month: index + 1,
          starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
          ends_on: `2026-${String(index + 1).padStart(2, "0")}-28`,
          status: "closed" as const,
          closed_at: null,
          reopened_at: null,
          reopen_reason: null,
          drafts: 0,
          approved: 1,
        })),
      },
    ],
    today: "2026-11-16",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  } as LedgerConfig;
}

function overview(overrides: Partial<JpkKrOverview> = {}): JpkKrOverview {
  return {
    year: 2026,
    mode: "symfonia",
    documents: 412,
    accounts: 97,
    problems: [],
    warnings: ["Księgą urzędową roku jest Symfonia FK — plik z NEXUSA służy do porównania."],
    ready: true,
    can_download: true,
    can_compare: true,
    can_edit_settings: false,
    settings: { address: { city: "Testowo" }, estonian: true, estonian_since: 2025 },
    file_name: "JPK_KR_PD_2026.xml",
    st: { assets: 4, problems: [], warnings: [], ready: true, file_name: "JPK_ST_KR_2026.xml" },
    ...overrides,
  };
}

function route(data: JpkKrOverview = overview()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: config() };
    if (url === "/api/accounting/reports/jpk-kr") return { data };
    if (url === "/api/accounting/reports/statements") throw new Error("bilans nie powinien się ładować");
    throw new Error(`nieoczekiwane ${url}`);
  });
}

async function openTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <ReportsView />
      </AccountingShell>
    </QueryClientProvider>,
  );
  await userEvent.click(await screen.findByRole("tab", { name: "JPK_KR_PD za rok" }));
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  post.mockReset();
  download.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/reports?year=2026&month=11");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — JPK_KR_PD za rok (K8c)", () => {
  it("rok bez braków: pobranie pliku i korekty sprawdzonej schematem", async () => {
    route();
    download.mockResolvedValue(undefined);
    await openTab();
    expect(await screen.findByText("JPK_KR_PD za 2026")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/accounting/reports/jpk-kr", { params: { year: 2026 } });
    expect(screen.getByText("plik się składa")).toBeInTheDocument();
    expect(screen.getByText(/412 dokumentów, 97 kont w zestawieniu/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Korekta (cały plik od nowa)"));
    await userEvent.click(screen.getByRole("button", { name: "Pobierz JPK_KR_PD" }));
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith(
        "/api/accounting/reports/jpk-kr/file?year=2026&kind=kr&correction=true",
        "JPK_KR_PD_2026.xml",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Pobierz JPK_ST_KR" }));
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith(
        "/api/accounting/reports/jpk-kr/file?year=2026&kind=st&correction=true",
        "JPK_ST_KR_2026.xml",
      ),
    );
  });

  it("braki blokujące wyłączają pobranie i są wypisane", async () => {
    route(
      overview({
        ready: false,
        problems: [
          { code: "periods", message: "Niezamknięte okresy", items: ["11/2026", "12/2026"] },
          { code: "markers", message: "Konta bez znacznika MF", items: ["401", "550"] },
        ],
        st: { assets: 0, problems: [{ code: "empty", message: "Brak środków", items: [] }], warnings: [], ready: false, file_name: "x" },
      }),
    );
    await openTab();
    expect(await screen.findByText("2 braki")).toBeInTheDocument();
    expect(screen.getByText("Niezamknięte okresy")).toBeInTheDocument();
    expect(screen.getByText(/11\/2026, 12\/2026/)).toBeInTheDocument();
    expect(screen.getByText(/401, 550/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz JPK_KR_PD" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pobierz JPK_ST_KR" })).toBeDisabled();
  });

  it("bez Płac nie ma pobrania JPK_KR_PD ani porównania (D2)", async () => {
    route(overview({ can_download: false, can_compare: false }));
    await openTab();
    expect(await screen.findByText(/pobiera go osoba z Płacami albo administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pobierz JPK_KR_PD" })).not.toBeInTheDocument();
    expect(screen.queryByText("Porównanie z JPK_KR_PD z Symfonii")).not.toBeInTheDocument();
  });

  it("błąd pobrania z serwera trafia do komunikatu", async () => {
    route();
    download.mockRejectedValue({ response: { data: { detail: "Plik JPK_KR_PD nie przechodzi schematu MF" } } });
    await openTab();
    await userEvent.click(await screen.findByRole("button", { name: "Pobierz JPK_KR_PD" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining("schematu MF"), "error"));
  });

  it("porównanie z plikiem z Symfonii pokazuje różnice kont i sum", async () => {
    route();
    const result: JpkKrCompareResult = {
      year: 2026,
      same: false,
      accounts_nexus: 97,
      accounts_symfonia: 98,
      amounts: [{ account: "402", fields: { S_6: { nexus: 420_000, symfonia: 500_000 } } }],
      markers: [{ account: "222", nexus: ["BPBIII3h"], symfonia: ["BPBIII3i"] }],
      only_nexus: [],
      only_symfonia: ["999"],
      ctrl: { C_1: { nexus: 412, symfonia: 411 } },
      differences: 4,
    };
    post.mockResolvedValue({ data: result });
    await openTab();
    const file = new File(["<JPK/>"], "symfonia.xml", { type: "application/xml" });
    await userEvent.upload(await screen.findByLabelText("Plik JPK_KR_PD z Symfonii"), file);
    await userEvent.click(screen.getByRole("button", { name: "Porównaj" }));
    expect(await screen.findByText("4 różnice")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/api/accounting/reports/jpk-kr/compare", expect.any(FormData), {
      params: { year: 2026 },
      headers: { "Content-Type": "multipart/form-data" },
    });
    expect(screen.getByText("4 200,00")).toBeInTheDocument();
    expect(screen.getByText(/222 \(BPBIII3h ≠ BPBIII3i\)/)).toBeInTheDocument();
    expect(screen.getByText("Tylko w Symfonii: 999")).toBeInTheDocument();
    expect(screen.getByText(/C_1 NEXUS 412 \/ Symfonia 411/)).toBeInTheDocument();
  });

  it("administrator zapisuje adres siedziby i CIT estoński", async () => {
    route(overview({ can_edit_settings: true, settings: { address: {}, estonian: false, estonian_since: null } }));
    put.mockResolvedValue({ data: {} });
    await openTab();
    await userEvent.type(await screen.findByLabelText("Województwo"), "mazowieckie");
    await userEvent.type(screen.getByLabelText("Kod pocztowy"), "00-001");
    await userEvent.click(screen.getByLabelText("CIT estoński (ryczałt od dochodów spółek)"));
    await userEvent.type(screen.getByLabelText("Pierwszy rok CIT estońskiego"), "2025");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz dane" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/accounting/reports/jpk-kr/settings", {
        address: { province: "mazowieckie", postal_code: "00-001" },
        estonian: true,
        estonian_since: 2025,
      }),
    );
  });

  it("awaria zapytania nie wygląda jak gotowy plik", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      throw new Error("500");
    });
    await openTab();
    expect(await screen.findByRole("button", { name: /spróbuj/i })).toBeInTheDocument();
    expect(screen.queryByText("plik się składa")).not.toBeInTheDocument();
  });
});
