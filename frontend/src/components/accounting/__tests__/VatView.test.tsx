import { render, screen, waitFor, within } from "@testing-library/react";
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
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...a: unknown[]) => download(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/vat",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { VatView } from "@/components/accounting/VatView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type {
  ForeignOverview,
  JpkOverview,
  VatMarkers,
  VatRegisters,
  VatUekOverview,
  VatUeOverview,
} from "@/lib/api/accounting-vat";
import { useAuthStore } from "@/store/auth";

function config(vatOpen = true): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "vat", label: "VAT i JPK", replaces: "rejestry i JPK w Symfonii", stage: "K5", built: true, enabled: vatOpen, open: vatOpen },
    ],
    me: { admin: false, approver: true, payroll: true },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "501", front_office_account: "502", back_office_account: "503", overhead_account: "550", team_account: "504" },
    years: [],
    today: "2026-11-20",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  };
}

function registers(overrides: Partial<VatRegisters> = {}): VatRegisters {
  return {
    year: 2026,
    month: 11,
    accounts: { output_account: "222", input_account: "221", intake_account: "080", foreign_account: "" },
    sales: [
      {
        document_id: 11,
        number: "FS 1/11/2026",
        ksef_number: "5250000000-20261130-AAAA-01",
        issue_date: "2026-11-30",
        date: "2026-11-30",
        counterparty: "Klient Testowy",
        tax_id: "5250000000",
        country: "PL",
        net: 100_000,
        vat: 23_000,
        groups: [{ key: "23", net: 100_000, vat: 23_000 }],
        correction: false,
        payroll: false,
        problem: null,
        counterparty_id: 31,
        markers: ["GTU_12", "TP"],
      },
      {
        document_id: 12,
        number: "1/11/2026/UE",
        ksef_number: null,
        issue_date: "2026-11-30",
        date: "2026-11-30",
        counterparty: "Nordic Bank Abp",
        tax_id: "FI12345678",
        country: "FI",
        net: 215_000,
        vat: 0,
        groups: [],
        correction: false,
        payroll: false,
        problem: "stawka spoza słownika JPK: oo",
        counterparty_id: 32,
        markers: [],
      },
    ],
    purchases: [
      {
        document_id: 21,
        number: "FV 7/11",
        ksef_number: "5260000000-20261112-BBBB-02",
        issue_date: "2026-11-10",
        date: "2026-11-12",
        counterparty: "Dostawca Testowy",
        tax_id: "5260000000",
        country: "PL",
        net: 100_000,
        vat: 23_000,
        groups: [{ key: "other", net: 100_000, vat: 23_000 }],
        correction: false,
        payroll: false,
        problem: null,
        counterparty_id: 33,
        markers: [],
      },
    ],
    summary: {
      groups: [
        { register: "sales", key: "23", label: "Stawka 23% (22%)", net_field: "K_19", vat_field: "K_20", also: null, net: 100_000, vat: 23_000 },
        { register: "purchases", key: "other", label: "Nabycie pozostałych towarów i usług", net_field: "K_42", vat_field: "K_43", also: null, net: 100_000, vat: 23_000 },
      ],
      output_vat: 23_000,
      input_vat: 23_000,
      due: 0,
    },
    issues: [
      {
        kind: "missing_sales",
        label: "Faktury sprzedaży z KSeF bez dokumentu w księdze",
        count: 1,
        items: [{ number: "FZ 1/11", detail: "zaliczka — bez dokumentu do czasu reguły zaliczek (K3)" }],
      },
    ],
    payroll_hidden: false,
    can_edit_accounts: false,
    ...overrides,
  };
}

function jpkOverview(overrides: Partial<JpkOverview> = {}): JpkOverview {
  return {
    year: 2026,
    month: 11,
    files: [],
    purpose: "submission",
    needs_opening_surplus: false,
    surplus_editable: false,
    surplus_value: 0,
    previous_surplus: 0,
    stale: null,
    missing: [],
    notes: [],
    contact: { email: "vat@example.com", phone: "" },
    can_prepare: true,
    can_download: true,
    can_mark_sent: true,
    can_edit_contact: false,
    ...overrides,
  };
}

function foreignOverview(overrides: Partial<ForeignOverview> = {}): ForeignOverview {
  return {
    year: 2026,
    month: 11,
    items: [
      {
        id: 41,
        number: "INV-0042",
        status: "draft",
        status_label: "w buforze",
        supplier_id: 51,
        supplier: "Dostawca SaaS Ltd",
        issue_date: "2026-11-03",
        service_date: "2026-10-31",
        currency: "EUR",
        rate: "4.300000",
        rate_day: "2026-10-30",
        net_cur: 10_000,
        net: 43_000,
        vat: 9_890,
        vat_rate: "23",
        deduction: "full",
        group: "imp_28b",
      },
    ],
    suppliers: [
      { id: 51, name: "Dostawca SaaS Ltd", country: "IE", tax_id: "IE1234567T", symfonia_partner_id: null, account: "202-1-1", group: "imp_28b", from_form: true },
      { id: 52, name: "Vendor Inc.", country: "US", tax_id: "123456789", symfonia_partner_id: "70100", account: "202-1-2", group: "imp_other", from_form: false },
    ],
    foreign_account: "202-1",
    next_account: "202-1-3",
    currencies: ["PLN", "EUR", "USD"],
    vat_rates: ["23", "8", "5"],
    missing: [],
    ...overrides,
  };
}

function markers(overrides: Partial<VatMarkers> = {}): VatMarkers {
  return {
    items: [{ counterparty_id: 31, name: "Klient Testowy", tax_id: "5250000000", country: "PL", markers: ["GTU_12", "TP"] }],
    labels: [
      { key: "GTU_12", label: "Usługi niematerialne (doradcze, prawne, zarządcze, marketingowe…)" },
      { key: "GTU_13", label: "Usługi transportowe i magazynowe" },
      { key: "TP", label: "Powiązania nabywcy z dostawcą (art. 32 ust. 2 pkt 1)" },
    ],
    can_edit: true,
    ...overrides,
  };
}

function vatUe(overrides: Partial<VatUeOverview> = {}): VatUeOverview {
  return {
    year: 2026,
    month: 11,
    lines: [
      {
        section: "services",
        section_label: "Usługi (art. 100 ust. 1 pkt 4)",
        country: "FI",
        number: "12345678",
        name: "Nordic Bank Abp",
        amount: 2150,
        net: 215_000,
        documents: ["1/11/2026/UE"],
        documents_count: 1,
      },
    ],
    totals: { goods: 0, services: 2150 },
    problems: [],
    blockers: [],
    missing: [],
    can_download: true,
    notes: ["Korekty faktur z wcześniejszych okresów idą na VAT-UEK za tamten okres."],
    ...overrides,
  };
}

function vatUek(overrides: Partial<VatUekOverview> = {}): VatUekOverview {
  return {
    year: 2026,
    month: 10,
    issued_year: 2026,
    issued_month: 11,
    lines: [
      {
        section: "services",
        section_label: "Usługi (art. 100 ust. 1 pkt 4)",
        country: "FI",
        number: "12345678",
        name: "Nordic Bank Abp",
        before: 2150,
        after: 1720,
        documents: ["KOR 1/11"],
        documents_count: 1,
      },
      {
        section: "services",
        section_label: "Usługi (art. 100 ust. 1 pkt 4)",
        country: "DE",
        number: "123456789",
        name: "Test GmbH",
        before: null,
        after: 300,
        documents: ["KOR 2/11"],
        documents_count: 1,
      },
    ],
    corrections: 2,
    earlier_months: [],
    problems: [],
    blockers: [],
    missing: [],
    can_download: true,
    notes: [],
    ...overrides,
  };
}

function route(
  cfg: LedgerConfig,
  data: VatRegisters = registers(),
  jpk: JpkOverview = jpkOverview(),
  foreign: ForeignOverview = foreignOverview(),
  marked: VatMarkers = markers(),
  ue: VatUeOverview = vatUe(),
  uek: VatUekOverview = vatUek(),
) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/vat") return { data };
    if (url === "/api/accounting/vat/jpk") return { data: jpk };
    if (url === "/api/accounting/vat/foreign") return { data: foreign };
    if (url === "/api/accounting/vat/markers") return { data: marked };
    if (url === "/api/accounting/vat/ue") return { data: ue };
    if (url === "/api/accounting/vat/uek") return { data: uek };
    if (url === "/api/finance/counterparties")
      return {
        data: {
          items: [{ id: 34, name: "Bank Powiązany S.A.", id_value: "5270000000", id_type: "nip" }],
          total: 1,
          role_counts: { client: 1, team: 0, contractor: 0, supplier: 0 },
          without_account: 0,
        },
      };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <VatView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  post.mockReset();
  download.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/vat");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — VAT (K5a)", () => {
  it("sumy do deklaracji, rejestry i lista do sprawdzenia", async () => {
    route(config());
    renderView();
    expect(await screen.findByText("Do deklaracji")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/accounting/vat", { params: { year: 2026, month: 11 } });
    const group = screen.getByText("Stawka 23% (22%)").closest("tr") as HTMLElement;
    expect(within(group).getByText("K_19 / K_20")).toBeInTheDocument();
    expect(screen.getByText("Rejestr sprzedaży · 2")).toBeInTheDocument();
    const eu = screen.getByText("1/11/2026/UE").closest("tr") as HTMLElement;
    expect(within(eu).getByText("do sprawdzenia")).toHaveAttribute("title", "stawka spoza słownika JPK: oo");
    expect(within(eu).getByText("FI12345678")).toBeInTheDocument();
    expect(screen.getByText("Faktury sprzedaży z KSeF bez dokumentu w księdze: 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Źródła →" })).toHaveAttribute("href", "/accounting/sources?year=2026&month=11");
    // Konta: VAT naliczony tylko do odczytu bez admina.
    expect(screen.queryByRole("textbox", { name: "Konto VAT naliczonego" })).not.toBeInTheDocument();
  });

  it("D2: bez Płac — informacja o ukrytych fakturach osób zespołu", async () => {
    route(config(), registers({ payroll_hidden: true, issues: [] }));
    renderView();
    expect(await screen.findByText(/Bez faktur osób zespołu/)).toBeInTheDocument();
    expect(screen.getByText(/Rejestry są pełne/)).toBeInTheDocument();
  });

  it("administrator zmienia konto VAT naliczonego i konto dostawców zagranicznych", async () => {
    route(config(), registers({ can_edit_accounts: true }));
    put.mockResolvedValue({ data: { input_account: "221-1", foreign_account: "202-1" } });
    const user = userEvent.setup();
    renderView();
    const field = await screen.findByRole("textbox", { name: "Konto VAT naliczonego" });
    await user.clear(field);
    await user.type(field, "221-1");
    await user.type(screen.getByRole("textbox", { name: "Konto dostawców zagranicznych" }), "202-1");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/accounting/vat/settings", { input_account: "221-1", foreign_account: "202-1" }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano konta VAT."));
  });

  it("długi rejestr: najpierw 50 wierszy, potem wszystkie", async () => {
    const base = registers().sales[0];
    const many = Array.from({ length: 60 }, (_, index) => ({ ...base, document_id: 100 + index, number: `FS ${index + 1}/11/2026` }));
    route(config(), registers({ sales: many, issues: [] }));
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByText("Rejestr sprzedaży · 60")).toBeInTheDocument();
    expect(screen.getByText("FS 50/11/2026")).toBeInTheDocument();
    expect(screen.queryByText("FS 51/11/2026")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pokaż wszystkie (60)" }));
    expect(screen.getByText("FS 60/11/2026")).toBeInTheDocument();
  });

  it("JPK: pierwszy miesiąc z nadwyżką z deklaracji z Symfonii", async () => {
    route(config(), registers({ issues: [] }), jpkOverview({ needs_opening_surplus: true, surplus_editable: true, surplus_value: null, previous_surplus: null }));
    post.mockResolvedValue({ data: { file: { id: 7, version: 1, purpose: "submission", status: "prepared", created_at: "2026-12-05T10:00:00Z", sent_at: null, sent_note: null }, warnings: ["Faktury kosztowe z wpływem w tym miesiącu bez FVZ: 1"] } });
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByText("JPK_V7M za listopad 2026")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Przygotuj JPK" });
    expect(button).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Nadwyżka z poprzedniej deklaracji" }), "1173");
    await user.click(button);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/vat/jpk", { year: 2026, month: 11, opening_surplus: 1173 }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "JPK v1 przygotowany i zgodny ze schematem MF. Do sprawdzenia: Faktury kosztowe z wpływem w tym miesiącu bez FVZ: 1.",
      ),
    );
  });

  it("JPK: wersje, pobranie XML, „wysłany” z UPO i korekta z uzasadnieniem", async () => {
    const files = [
      { id: 7, version: 1, purpose: "submission" as const, status: "sent" as const, created_at: "2026-12-05T10:00:00Z", sent_at: "2026-12-06T09:00:00Z", sent_note: "UPO 123", totals: { P_38: 207, P_39: 0, P_48: 2650, P_51: 0, P_62: 2443, sales_rows: 3, purchase_rows: 2 } },
      { id: 8, version: 2, purpose: "correction" as const, status: "prepared" as const, created_at: "2026-12-10T10:00:00Z", sent_at: null, sent_note: null, totals: { P_38: 230, P_39: 0, P_48: 200, P_51: 30, P_62: 0, sales_rows: 3, purchase_rows: 2 } },
    ];
    route(config(), registers({ issues: [] }), jpkOverview({ files, purpose: "correction" }));
    post.mockResolvedValue({ data: { ...files[1], status: "sent" } });
    const user = userEvent.setup();
    renderView();
    const first = (await screen.findByText("v1")).closest("tr") as HTMLElement;
    expect(within(first).getByText("do przeniesienia 2 443,00 zł")).toBeInTheDocument();
    expect(within(first).getByText("UPO 123")).toBeInTheDocument();
    await user.click(within(first).getByRole("button", { name: "Pobierz XML" }));
    expect(download).toHaveBeenCalledWith("/api/accounting/vat/jpk/7/file", "JPK_V7M_2026-11_v1.xml");
    const second = screen.getByText("v2").closest("tr") as HTMLElement;
    expect(within(second).getByText("do wpłaty 30,00 zł")).toBeInTheDocument();
    await user.click(within(second).getByRole("button", { name: "Oznacz jako wysłany" }));
    await user.type(screen.getByRole("textbox", { name: "Numer UPO" }), "UPO 456");
    await user.click(screen.getByRole("button", { name: "Wysłany" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/accounting/vat/jpk/8/sent", { note: "UPO 456" }));
    // Po wysłanej wersji kolejna to korekta — przycisk czeka na uzasadnienie.
    expect(screen.getByRole("button", { name: "Przygotuj korektę JPK" })).toBeDisabled();
  });

  it("JPK czeka na listę „do sprawdzenia” (faktura z KSeF bez dokumentu)", async () => {
    route(config(), registers(), jpkOverview());
    renderView();
    expect(await screen.findByText(/JPK powstanie po zamknięciu listy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przygotuj JPK" })).toBeDisabled();
  });

  it("JPK: złożoną starszą wersję da się oznaczyć, nieaktualny wysłany i uwagi (przegląd K5b)", async () => {
    const files = [
      { id: 7, version: 1, purpose: "submission" as const, status: "prepared" as const, created_at: "2026-12-05T10:00:00Z", sent_at: null, sent_note: null },
      { id: 8, version: 2, purpose: "submission" as const, status: "prepared" as const, created_at: "2026-12-06T10:00:00Z", sent_at: null, sent_note: null },
    ];
    route(config(), registers({ issues: [] }), jpkOverview({ files, stale: "surplus", notes: ["Znaczniki GTU i TP — jeszcze nie w NEXUSIE."] }));
    renderView();
    const first = (await screen.findByText("v1")).closest("tr") as HTMLElement;
    expect(within(first).getByRole("button", { name: "Oznacz jako wysłany" })).toBeInTheDocument();
    expect(screen.getByText(/korekta JPK za poprzedni miesiąc zmieniła nadwyżkę/)).toBeInTheDocument();
    expect(screen.getByText("Znaczniki GTU i TP — jeszcze nie w NEXUSIE.")).toBeInTheDocument();
  });

  it("JPK: unieważniona wersja bez akcji, pierwszy miesiąc z podpowiedzią nadwyżki", async () => {
    const files = [
      { id: 7, version: 1, purpose: "submission" as const, status: "sent" as const, created_at: "2026-12-05T10:00:00Z", sent_at: "2026-12-06T09:00:00Z", sent_note: null },
      { id: 8, version: 2, purpose: "submission" as const, status: "void" as const, created_at: "2026-12-06T10:00:00Z", sent_at: null, sent_note: null },
    ];
    route(config(), registers({ issues: [] }), jpkOverview({ files, purpose: "correction", surplus_editable: true, surplus_value: 120 }));
    renderView();
    const second = (await screen.findByText("v2")).closest("tr") as HTMLElement;
    expect(within(second).getByText("unieważniony (wysłano inną wersję)")).toBeInTheDocument();
    expect(within(second).queryByRole("button", { name: "Oznacz jako wysłany" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Nadwyżka z poprzedniej deklaracji" })).toHaveValue("120");
  });

  it("JPK bez Płac: stan wersji bez kwot i bez pobrania", async () => {
    const files = [{ id: 7, version: 1, purpose: "submission" as const, status: "prepared" as const, created_at: "2026-12-05T10:00:00Z", sent_at: null, sent_note: null }];
    route(config(), registers({ issues: [] }), jpkOverview({ files, can_prepare: false, can_download: false }));
    renderView();
    expect(await screen.findByText("v1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pobierz XML" })).not.toBeInTheDocument();
    expect(screen.queryByText("Deklaracja")).not.toBeInTheDocument();
    expect(screen.getByText(/przygotowuje i pobiera go osoba z Płacami/)).toBeInTheDocument();
  });

  it("moduł wyłączony — bez zapytania o rejestry", async () => {
    route(config(false));
    renderView();
    expect(await screen.findByText(/włącza go administrator w Ustawieniach/)).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/vat", expect.anything());
  });

  it("wiersz sprzedaży pokazuje znaczniki GTU/TP kontrahenta", async () => {
    route(config());
    renderView();
    const row = (await screen.findByText("FS 1/11/2026")).closest("tr") as HTMLElement;
    expect(within(row).getByText("GTU_12, TP")).toBeInTheDocument();
  });
});

describe("Księgowość — VAT: zakup zagraniczny i znaczniki (K5b-2)", () => {
  it("lista miesiąca: kwota w walucie, kurs NBP i pola JPK importu usług", async () => {
    route(config(), registers({ issues: [] }));
    renderView();
    const row = (await screen.findByText("INV-0042")).closest("tr") as HTMLElement;
    expect(within(row).getByText("100,00 EUR")).toBeInTheDocument();
    expect(within(row).getByText("kurs 4,3000 z 30.10.2026")).toBeInTheDocument();
    expect(within(row).getByText("import usług UE")).toBeInTheDocument();
    expect(within(row).getByText("430,00")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "INV-0042" })).toHaveAttribute(
      "href",
      "/accounting/documents?year=2026&month=11&type=FVZ&status=draft",
    );
  });

  it("formularz: nowy dostawca do kartoteki i faktura do bufora", async () => {
    route(config(), registers({ issues: [] }));
    post.mockResolvedValue({
      data: {
        document: { ...foreignOverview().items[0], id: 42, number: "INV-0099", net: 86_000, vat: 19_780 },
        supplier: { id: 53, name: "Nowy SaaS Ltd", country: "IE", tax_id: "IE7654321T", symfonia_partner_id: null, account: "202-1-3", group: "imp_28b", from_form: true },
      },
    });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Dodaj fakturę zagraniczną" }));
    const submit = screen.getByRole("button", { name: "Dodaj do bufora" });
    expect(submit).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "Dostawca" }), "new");
    await user.type(screen.getByRole("textbox", { name: "Nazwa dostawcy" }), "Nowy SaaS Ltd");
    await user.type(screen.getByRole("textbox", { name: "Kraj dostawcy" }), "ie");
    await user.type(screen.getByRole("textbox", { name: "Numer VAT dostawcy" }), "7654321T");
    expect(screen.getByText(/K_29 \/ K_30 — usługa od podatnika VAT z UE/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Konto rozrachunkowe dostawcy" })).toHaveAttribute("placeholder", "202-1-3");
    await user.type(screen.getByRole("textbox", { name: "Numer faktury" }), "INV-0099");
    // Data wykonania usługi idzie za datą wystawienia, dopóki jej nie zmienić.
    const issued = screen.getByLabelText("Data wystawienia");
    await user.type(issued, "2026-11-03");
    expect(screen.getByLabelText("Data wykonania usługi")).toHaveValue("2026-11-03");
    await user.clear(screen.getByLabelText("Data wykonania usługi"));
    await user.type(screen.getByLabelText("Data wykonania usługi"), "2026-10-31");
    await user.type(screen.getByRole("textbox", { name: "Netto w walucie" }), "200,00");
    await user.type(screen.getByRole("textbox", { name: "Konto kosztu" }), "402-1");
    await user.click(submit);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/vat/foreign", {
        new_supplier: { name: "Nowy SaaS Ltd", country: "IE", tax_id: "7654321T", symfonia_partner_id: undefined, account: undefined },
        number: "INV-0099",
        issue_date: "2026-11-03",
        service_date: "2026-10-31",
        currency: "EUR",
        net: "200.00",
        vat_rate: "23",
        deduction: "full",
        cost_account: "402-1",
        description: undefined,
      }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "FVZ INV-0099 w buforze: 860,00 zł netto, VAT 197,80 zł. Zatwierdza lista „Księgowi” w Dokumentach.",
      ),
    );
    // Po zapisie formularz czeka na kolejną fakturę tego dostawcy.
    expect(screen.getByRole("textbox", { name: "Numer faktury" })).toHaveValue("");
  });

  it("formularz: dostawca z kartoteki spoza UE, bez odliczenia", async () => {
    route(config(), registers({ issues: [] }));
    post.mockResolvedValue({ data: { document: foreignOverview().items[0], supplier: foreignOverview().suppliers[1] } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Dodaj fakturę zagraniczną" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Dostawca" }), "52");
    expect(screen.getByText(/K_27 \/ K_28/)).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Numer faktury" }), "US-77");
    await user.type(screen.getByLabelText("Data wystawienia"), "2026-11-02");
    await user.selectOptions(screen.getByRole("combobox", { name: "Waluta" }), "USD");
    await user.type(screen.getByRole("textbox", { name: "Netto w walucie" }), "-15.5");
    await user.selectOptions(screen.getByRole("combobox", { name: "Odliczenie VAT" }), "none");
    await user.type(screen.getByRole("textbox", { name: "Konto kosztu" }), "402-2");
    await user.click(screen.getByRole("button", { name: "Dodaj do bufora" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/accounting/vat/foreign",
        expect.objectContaining({ supplier_id: 52, currency: "USD", net: "-15.5", deduction: "none", service_date: "2026-11-02" }),
      ),
    );
  });

  it("bez konta dostawców zagranicznych nowego dostawcy nie da się założyć", async () => {
    route(config(), registers({ issues: [] }), jpkOverview(), foreignOverview({ foreign_account: "", next_account: null, missing: ["konto rozrachunków z dostawcami zagranicznymi"] }));
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Dodaj fakturę zagraniczną" }));
    expect(screen.getByRole("option", { name: /Nowy dostawca/ })).toBeDisabled();
    expect(screen.getByText(/Brakuje: konto rozrachunków z dostawcami zagranicznymi/)).toBeInTheDocument();
  });

  it("znaczniki: zmiana listy i dodanie kontrahenta z kartoteki", async () => {
    route(config(), registers({ issues: [] }));
    put.mockResolvedValue({ data: { counterparty_id: 34, name: "Bank Powiązany S.A.", tax_id: "5270000000", country: "PL", markers: ["TP"] } });
    const user = userEvent.setup();
    renderView();
    const item = (await screen.findByText("Klient Testowy", { selector: "span.font-medium" })).closest("li") as HTMLElement;
    expect(within(item).getByText("GTU_12, TP")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj kontrahenta" }));
    await user.type(screen.getByRole("textbox", { name: "Szukaj kontrahenta" }), "Bank");
    await user.click(await screen.findByRole("button", { name: /Bank Powiązany S\.A\./ }));
    const save = screen.getByRole("button", { name: "Zapisz" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /^TP/ }));
    await user.click(save);
    await waitFor(() => expect(put).toHaveBeenCalledWith("/api/accounting/vat/markers/34", { markers: ["TP"] }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano znaczniki — Bank Powiązany S.A."));
  });

  it("znaczniki bez listy „Księgowi”: tylko podgląd", async () => {
    route(config(), registers({ issues: [] }), jpkOverview(), foreignOverview(), markers({ can_edit: false }));
    renderView();
    expect(await screen.findByText("GTU i TP w JPK")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj kontrahenta" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
  });
});

describe("Księgowość — VAT-UE (K5b-3a)", () => {
  it("pozycje kontrahentów z UE i pobranie pliku XML", async () => {
    route(config(), registers({ issues: [] }));
    const user = userEvent.setup();
    renderView();
    const row = (await screen.findByText("FI 12345678")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Nordic Bank Abp")).toBeInTheDocument();
    expect(within(row).getByText("2 150,00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pobierz VAT-UE (XML)" }));
    expect(download).toHaveBeenCalledWith("/api/accounting/vat/ue/file?year=2026&month=11", "VAT-UE_2026-11.xml");
  });

  it("problem z numerem VAT UE i blokady rejestru wyłączają pobranie", async () => {
    route(
      config(),
      registers({ issues: [] }),
      jpkOverview(),
      foreignOverview(),
      markers(),
      vatUe({
        lines: [],
        problems: [
          { number: "1/11/2026/UE", detail: "nabywca bez numeru VAT UE", kind: "counterparty" },
          // Bez okresu (starszy serwer) — zostaje na liście problemów.
          { number: "KOR 1/11", detail: "korekta faktury z 10.2026 — na VAT-UEK za 10.2026", kind: "earlier" },
        ],
        blockers: ["FVS i FVZ w buforze — rejestr liczy tylko zatwierdzone: 1"],
        can_download: false,
      }),
    );
    renderView();
    expect(await screen.findByText(/nabywca bez numeru VAT UE/)).toBeInTheDocument();
    expect(screen.getByText(/na VAT-UEK za 10.2026/).closest("li")).toHaveClass("text-warning-muted-foreground");
    expect(screen.getByText(/VAT-UE powstanie po zamknięciu listy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz VAT-UE (XML)" })).toBeDisabled();
  });

  it("korekty wcześniejszego okresu: VAT-UEK z „było” i „jest” i pobranie pliku", async () => {
    route(
      config(),
      registers({ issues: [] }),
      jpkOverview(),
      foreignOverview(),
      markers(),
      vatUe({
        problems: [
          { number: "KOR 1/11", detail: "korekta faktury z 10.2026", kind: "earlier", period: "2026-10" },
          { number: "KOR 2/11", detail: "korekta faktury z 10.2026", kind: "earlier", period: "2026-10" },
        ],
      }),
    );
    const user = userEvent.setup();
    renderView();
    const block = await screen.findByRole("region", { name: "VAT-UEK za 10.2026" });
    expect(within(block).getByText("korekty: KOR 1/11, KOR 2/11")).toBeInTheDocument();
    const changed = (await within(block).findByText("FI 12345678")).closest("tr") as HTMLElement;
    expect(within(changed).getByText("2 150,00")).toBeInTheDocument();
    expect(within(changed).getByText("1 720,00")).toBeInTheDocument();
    const added = within(block).getByText("DE 123456789").closest("tr") as HTMLElement;
    expect(within(added).getByText("—")).toBeInTheDocument();
    expect(within(block).getByText(/„—” w „Było” = kontrahent dopisany/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/accounting/vat/uek", {
      params: { year: 2026, month: 10, issued_year: 2026, issued_month: 11 },
    });
    // Korekty z okresem nie wiszą już na liście problemów VAT-UE.
    expect(screen.queryByText(/korekta faktury z 10.2026/)).not.toBeInTheDocument();
    await user.click(within(block).getByRole("button", { name: "Pobierz VAT-UEK za 10.2026 (XML)" }));
    expect(download).toHaveBeenCalledWith(
      "/api/accounting/vat/uek/file?year=2026&month=10&issued_year=2026&issued_month=11",
      "VAT-UEK_2026-10_korekty_2026-11.xml",
    );
  });

  it("VAT-UEK z problemem i bez zmiany kwot nie daje pliku", async () => {
    route(
      config(),
      registers({ issues: [] }),
      jpkOverview(),
      foreignOverview(),
      markers(),
      vatUe({ problems: [{ number: "KOR 1/11", detail: "korekta", kind: "earlier", period: "2026-09" }] }),
      vatUek({
        month: 9,
        lines: [],
        problems: [{ number: "KOR 1/11", detail: "faktura pierwotna nie ma dokumentu w księdze", kind: "outside" }],
        can_download: false,
      }),
    );
    renderView();
    const block = await screen.findByRole("region", { name: "VAT-UEK za 09.2026" });
    expect(await within(block).findByText(/faktura pierwotna nie ma dokumentu/)).toBeInTheDocument();
    expect(within(block).getByRole("button", { name: "Pobierz VAT-UEK za 09.2026 (XML)" })).toBeDisabled();
  });
});

describe("Księgowość — porównanie z JPK z Symfonii (K5b-3b)", () => {
  it("wgrany plik: różnice deklaracji i wierszy", async () => {
    route(config(), registers({ issues: [] }));
    post.mockResolvedValue({
      data: {
        year: 2026,
        month: 11,
        declaration: [{ field: "P_38", nexus: 207, symfonia: 208 }, { field: "P_48", nexus: 230, symfonia: 230 }],
        rows: [
          { kind: "sales", nexus_rows: 2, symfonia_rows: 2, matched: 1, only_nexus: [], only_nexus_count: 0, only_symfonia: [], only_symfonia_count: 0,
            different: [{ number: "FS 1/11/2026", party: "Klient Testowy", document_id: 11, vat: 23_000, fields: { K_20: { nexus: 23_000, symfonia: 23_100 } }, markers: null }], different_count: 1 },
          { kind: "purchases", nexus_rows: 1, symfonia_rows: 0, matched: 0, only_nexus: [{ number: "FV 7/11", party: "Dostawca Testowy", document_id: 21, vat: 23_000 }], only_nexus_count: 1, only_symfonia: [], only_symfonia_count: 0, different: [], different_count: 0 },
        ],
        differences: 3,
        problems: [],
      },
    });
    const user = userEvent.setup();
    renderView();
    const input = await screen.findByLabelText("Plik JPK z Symfonii");
    await user.upload(input, new File(["<JPK/>"], "jpk.xml", { type: "application/xml" }));
    await user.click(screen.getByRole("button", { name: "Porównaj" }));
    expect(await screen.findByText("Różnice: 3")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/api/accounting/vat/jpk/compare", expect.any(FormData), expect.objectContaining({ params: { year: 2026, month: 11 } }));
    const p38 = screen.getByText("P_38").closest("tr") as HTMLElement;
    expect(within(p38).getByText("208")).toBeInTheDocument();
    expect(screen.queryByText("P_48")).not.toBeInTheDocument();
    expect(screen.getByText("Tylko w NEXUSIE: 1")).toBeInTheDocument();
    expect(screen.getByText(/FS 1\/11\/2026 — K_20: 230,00 \/ 231,00/)).toBeInTheDocument();
  });

  it("bez prawa do pliku JPK karty porównania nie ma", async () => {
    route(config(), registers({ issues: [] }), jpkOverview({ can_download: false, can_prepare: false }));
    renderView();
    expect(await screen.findByText("JPK_V7M za listopad 2026")).toBeInTheDocument();
    expect(screen.queryByText("Porównanie z JPK z Symfonii")).not.toBeInTheDocument();
  });
});
