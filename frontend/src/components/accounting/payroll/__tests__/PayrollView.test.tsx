import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showToast = vi.fn();
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
const fetchDownload = vi.fn();
const downloadBlob = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => fetchDownload(...a),
  downloadBlob: (...a: unknown[]) => downloadBlob(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/payroll",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { PayrollView } from "@/components/accounting/payroll/PayrollView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { PayrollMonth, Registrations } from "@/lib/api/payroll-lists";
import { useAuthStore } from "@/store/auth";

import { list, month, personData } from "./payroll-fixtures";

function config(overrides: Partial<LedgerConfig> = {}): LedgerConfig {
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
    today: "2026-11-14",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
    ...overrides,
  };
}

const REGISTRATIONS: Registrations = {
  date_from: "2026-10-01",
  date_to: "2026-10-31",
  events: [
    {
      kind: "ZUA",
      person_key: "u13",
      user_id: 13,
      candidate_id: null,
      contract_id: null,
      name: "Ewa Przykładowa",
      title_kind: "zlecenie",
      on: "2026-10-01",
      problems: [],
    },
  ],
  skipped: [{ name: "Piotr Testowy", kind: "ZUA", reason: "brak PESEL-u albo dokumentu" }],
  file_available: false,
};

function route(data: PayrollMonth, cfg: LedgerConfig = config()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/hr/payroll-lists/months/2026/10") return { data };
    if (url === "/api/hr/payroll-lists/people/users/12") return { data: personData() };
    if (url === "/api/hr/payroll-lists/registrations") return { data: REGISTRATIONS };
    if (url === "/api/hr/payroll-lists/years/2026/pit-11") {
      return {
        data: {
          year: 2026,
          people: [
            { person_key: "u11", name: "Anna Przykładowa", ready: true, missing: [] },
            { person_key: "u12", name: "Jan Testowy", ready: false, missing: ["adres zamieszkania"] },
          ],
        },
      };
    }
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderTab(children: ReactNode = <PayrollView />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>{children}</AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
  showToast.mockReset();
  fetchDownload.mockReset();
  downloadBlob.mockReset();
  window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Lista płac (K7a)", () => {
  it("grupuje pozycje po umowach z sumami, pokazuje problemy i blokadę zatwierdzenia z powodem", async () => {
    route(month());
    renderTab();
    expect(await screen.findByRole("heading", { name: "Lista płac 10/2026 · UoP i zlecenia" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Lista płac" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Szkic do zatwierdzenia")).toBeInTheDocument();

    const uop = screen.getByRole("rowheader", { name: "Umowy o pracę · 2" }).closest("tr")!;
    expect(within(uop).getByText("17 300,00")).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Umowy zlecenia — zespół i kontraktorzy u klientów · 2" })).toBeInTheDocument();
    const contractor = screen.getByRole("button", { name: "Piotr Testowy" }).closest("tr")!;
    expect(within(contractor).getByText("brak kwoty")).toBeInTheDocument();
    expect(within(contractor).getByRole("img", { name: /Problem blokujący/ })).toBeInTheDocument();
    expect(screen.getByText("168 h × 42,00")).toBeInTheDocument();

    const problems = screen.getByRole("region", { name: "Problemy listy" });
    expect(within(problems).getByText("Do rozwiązania przed zatwierdzeniem: 2")).toBeInTheDocument();
    expect(within(problems).getByText(/— Jan Testowy/)).toBeInTheDocument();
    expect(within(problems).getByText(/— Piotr Testowy/)).toBeInTheDocument();
    // „Do uwagi” (nie blokuje) dopiero po rozwinięciu — panel nie spycha tabeli w dół.
    expect(within(problems).queryByText(/— Ewa Przykładowa/)).not.toBeInTheDocument();
    await userEvent.setup().click(within(problems).getByRole("button", { name: "Pokaż wszystkie (3)" }));
    expect(within(problems).getByText(/— Ewa Przykładowa/)).toBeInTheDocument();

    expect(screen.getByText("Do wypłaty (do 10.11)")).toBeInTheDocument();
    expect(screen.getByText("ZUS razem (do 15.12)")).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: "Zatwierdź listę" });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription("Tę listę policzyłeś Ty — zatwierdza druga osoba z Rozliczeń.");
    expect(screen.getByRole("button", { name: "ZUS DRA + RCA (KEDU)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Przelewy" })).toBeDisabled();
  });

  it("wiersz otwiera rozpisanie pozycji; kwota Rozliczeń idzie z opisem", async () => {
    route(month());
    put.mockResolvedValue({ data: month({ inputs: [] }) });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Anna Przykładowa" }));
    const panel = await screen.findByRole("dialog", { name: "Anna Przykładowa" });
    expect(within(panel).getByText("Składki osoby")).toBeInTheDocument();
    expect(within(panel).getByText("Zaliczka PIT (skala)")).toBeInTheDocument();
    expect(within(panel).getByText("9 397,44")).toBeInTheDocument();
    expect(within(panel).getByText("Kwota zmniejszająca z PIT-2.")).toBeInTheDocument();

    const save = within(panel).getByRole("button", { name: "Zapisz kwotę" });
    await user.type(within(panel).getByLabelText("Kwota brutto Rozliczeń"), "8 000,5");
    expect(save).toBeDisabled();
    await user.type(within(panel).getByLabelText("Opis kwoty Rozliczeń"), "aneks do umowy");
    await user.type(within(panel).getByLabelText("Podstawa do Funduszu Pracy"), "abc");
    expect(save).toBeDisabled();
    await user.clear(within(panel).getByLabelText("Podstawa do Funduszu Pracy"));
    await user.type(within(panel).getByLabelText("Podstawa do Funduszu Pracy"), "9000");
    await user.click(save);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/hr/payroll-lists/months/2026/10/inputs", {
        user_id: 11,
        kind: "uop",
        gross: "8000.50",
        note: "aneks do umowy",
        fund_basis: "9000.00",
      }),
    );
  });

  it("zatwierdzenie po potwierdzeniu, gdy serwer pozwala", async () => {
    route(month({ list: list({ can_approve: true, approve_refusal: null, problems: [] }) }));
    post.mockResolvedValue({ data: month({ can_compute: false, list: list({ status: "approved" }) }) });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Zatwierdź listę" }));
    const dialog = await screen.findByRole("dialog", { name: "Zatwierdzić listę LP/2026/10?" });
    await user.click(within(dialog).getByRole("button", { name: "Zatwierdź listę" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/hr/payroll-lists/lists/7/approve"));
    expect(await screen.findByText("Zatwierdzona")).toBeInTheDocument();
  });

  it("KEDU bez danych osób pokazuje listę braków w oknie", async () => {
    route(month({ can_compute: false, list: list({ status: "approved" }) }));
    fetchDownload.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "kedu_data_missing",
            message: "Brakuje danych osób do deklaracji.",
            people: [{ person: "Jan Testowy", missing: ["adres zamieszkania"] }],
          },
        },
      },
    });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "ZUS DRA + RCA (KEDU)" }));
    await waitFor(() =>
      expect(fetchDownload).toHaveBeenCalledWith("/api/hr/payroll-lists/declarations/2026/11/kedu.xml", undefined),
    );
    const dialog = await screen.findByRole("dialog", { name: "Deklaracja ZUS — brakuje danych osób" });
    expect(within(dialog).getByText("Jan Testowy: adres zamieszkania")).toBeInTheDocument();
  });

  it("niezamknięty miesiąc odsyła do Rozliczeń — bez fałszywej pustej listy", async () => {
    route(month({ period_status: "open", can_compute: false, list: null }));
    renderTab();
    expect(await screen.findByText("Miesiąc 10/2026 nie jest jeszcze zamknięty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz Rozliczenia 10/2026" })).toHaveAttribute(
      "href",
      "/people/payroll/2026-10",
    );
    expect(screen.queryByRole("button", { name: "Przelicz listę" })).not.toBeInTheDocument();
  });

  it("zamknięty miesiąc bez listy: „Przelicz listę” z datą wypłaty", async () => {
    route(month({ list: null }));
    post.mockResolvedValue({ data: month() });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Przelicz listę" }));
    const dialog = await screen.findByRole("dialog", { name: "Przelicz listę płac 10/2026" });
    expect(within(dialog).getByLabelText("Data wypłaty")).toHaveValue("2026-11-10");
    await user.click(within(dialog).getByRole("button", { name: "Przelicz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/payroll-lists/months/2026/10/compute", { pay_date: "2026-11-10" }),
    );
  });

  it("awaria zapytania nie wygląda jak pusty miesiąc", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      throw Object.assign(new Error("500"), { response: { status: 500 } });
    });
    renderTab();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie|Odśwież/ })).toBeInTheDocument();
    expect(screen.queryByText(/nie jest jeszcze policzona/)).not.toBeInTheDocument();
  });

  it("bez uprawnienia „Rozliczenia” nie ma zakładki ani listy", async () => {
    route(month(), config({ me: { admin: false, approver: true, payroll: false } }));
    renderTab();
    expect(await screen.findByText(/Listy płac widzą osoby z uprawnieniem „Rozliczenia”/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Lista płac" })).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/hr/payroll-lists/months/2026/10");
  });
});

describe("Lista płac — dane osoby", () => {
  it("z pozycji otwiera dane płacowe z maską PESEL-u i wysyła tylko zmiany z wersją", async () => {
    route(month());
    put.mockResolvedValue({ data: personData({ pit2: 0, version: 4 }) });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Jan Testowy" }));
    const panel = await screen.findByRole("dialog", { name: "Jan Testowy" });
    await user.click(within(panel).getByRole("button", { name: "Dane płacowe osoby" }));
    const dialog = await screen.findByRole("dialog", { name: "Dane płacowe — Jan Testowy" });
    expect(within(dialog).getByText(/Zapisany: •••••••3459/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Nowy PESEL")).toHaveValue("");
    expect(within(dialog).getByLabelText("Oddział NFZ")).toHaveValue("07R");
    expect(within(dialog).getByLabelText("Wymiar etatu")).toHaveValue("1/1");
    expect(within(dialog).queryByLabelText("Emerytalne i rentowe")).not.toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Zapisz dane" });
    expect(save).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText("PIT-2"), "0");
    await user.click(save);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/hr/payroll-lists/people/users/12", { expected_version: 3, pit2: 0 }),
    );
  });

  it("dane zmienione w międzyczasie: komunikat z „Odśwież”", async () => {
    route(month());
    put.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "stale_person_data",
            message: "Dane tej osoby zmienił w międzyczasie ktoś inny — odśwież i wpisz zmiany jeszcze raz.",
          },
        },
      },
    });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Jan Testowy" }));
    const panel = await screen.findByRole("dialog", { name: "Jan Testowy" });
    await user.click(within(panel).getByRole("button", { name: "Dane płacowe osoby" }));
    const dialog = await screen.findByRole("dialog", { name: "Dane płacowe — Jan Testowy" });
    await user.type(within(dialog).getByLabelText("Kod tytułu ubezpieczenia"), "{backspace}1");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz dane" }));
    expect(await within(dialog).findByText(/zmienił w międzyczasie ktoś inny/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Odśwież" })).toBeInTheDocument();
  });
});

describe("Lista płac — pliki ZUS i PIT", () => {
  it("pokazuje zgłoszenia i pominiętych; bez kompletu plik zgłoszeń jest nieaktywny", async () => {
    route(month());
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10&view=files");
    renderTab();
    expect(await screen.findByText("Ewa Przykładowa")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/hr/payroll-lists/registrations", {
      params: { date_from: "2026-10-01", date_to: "2026-10-31" },
    });
    expect(screen.getByText("zgłoszenie do ubezpieczeń")).toBeInTheDocument();
    expect(screen.getByText(/Piotr Testowy \(ZUA\): brak PESEL-u albo dokumentu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz KEDU zgłoszeń" })).toBeDisabled();
    expect(await screen.findByText("brakuje: adres zamieszkania")).toBeInTheDocument();
    expect(screen.getByText("Gotowe: 1 z 2 osób")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "PIT-11 ZIP" })).toBeEnabled();
  });
});
