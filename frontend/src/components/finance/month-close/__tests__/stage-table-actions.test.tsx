import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MonthCloseClient,
  MonthCloseOverview,
  MonthCloseStages,
  SettlementRow,
  TeamMonth,
  TeamMonthPerson,
} from "@/lib/api/client-settlements";
import type { ReminderClient } from "@/lib/api/settlement-reminders";

import { StageTable } from "../StageTable";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));

function stages(patch: Partial<{ [K in keyof MonthCloseStages]: Partial<MonthCloseStages[K]> | number }> = {}): MonthCloseStages {
  const base: MonthCloseStages = {
    people: 4,
    report: { in: 4, missing: 0, md_auto: 4, md_manual: 0 },
    check: { clean: 4, auto_clean: 4, resolved: 0, warn: 0, fail: 0, returned: 0, unread: 0, no_md: 0, missing: 0 },
    accept: { done: 4, auto: 0, ready: 0 },
    contractor_invoice: { match: 4, differs: 0, nip: 0, can_issue: 0, none: 0, waiting: 0 },
    client_invoice: { issued: 4, ready: 0, waiting_client: 0, waiting: 0, issued_early: 0 },
    missing_order: 0,
  };
  const out = { ...base } as Record<string, unknown>;
  for (const [k, v] of Object.entries(patch)) {
    out[k] = typeof v === "number" ? v : { ...(base as unknown as Record<string, object>)[k], ...v };
  }
  return out as unknown as MonthCloseStages;
}

function client(patch: Partial<MonthCloseClient> = {}): MonthCloseClient {
  return {
    client_id: 7,
    name: "Firma Testowa sp. z o.o.",
    people: 4,
    clean: 4,
    accepted: 4,
    decide: 0,
    unread: 0,
    missing: 0,
    contractor_in_ksef: 4,
    client_invoice_issued: 4,
    client_invoice_ready: 0,
    revenue_ready: null,
    top_reason: null,
    client_report: null,
    stages: stages(),
    ...patch,
  };
}

function person(patch: Partial<TeamMonthPerson> = {}): TeamMonthPerson {
  return {
    user_id: 1,
    person: "Jan Testowy",
    timesheet: "approved",
    timesheet_on: "2027-01-02",
    invoice: "in_ksef",
    invoice_on: "2027-01-03",
    paid: true,
    paid_on: "2027-01-10",
    ...patch,
  };
}

function settlementRow(patch: Partial<SettlementRow> = {}): SettlementRow {
  return {
    contract_id: 1,
    settlement_id: 1,
    person: "Anna Przykładowa",
    order_number: "ZAM/1",
    status: "ok",
    issues: null,
    md_regular: "20",
    md_extra: null,
    md_charged: "20",
    md_remaining_after: null,
    amount_cost: null,
    amount_revenue: null,
    margin: null,
    margin_pct: null,
    contractor_invoice: "none",
    client_invoice: "waiting",
    ...patch,
  };
}

interface Options {
  clients?: MonthCloseClient[];
  team?: TeamMonth | null;
  teamError?: string | null;
  reminders?: Map<number, ReminderClient>;
  reminderNote?: (r: ReminderClient | undefined) => string | undefined;
}

function renderTable(opts: Options = {}) {
  const data = {
    month: "2026-12",
    can_see_amounts: false,
    totals: {},
    clients: opts.clients ?? [client()],
    reasons: [],
  } as unknown as MonthCloseOverview;
  const clientHref = vi.fn(
    (id: number, extra: Record<string, string> = {}) => `/finance?stClient=${id}${Object.entries(extra).map(([k, v]) => `&${k}=${v}`).join("")}`,
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StageTable
        data={data}
        month="2026-12"
        team={opts.team ?? null}
        teamError={opts.teamError ?? null}
        reminders={opts.reminders ?? new Map()}
        clientHref={clientHref}
        reminderNote={opts.reminderNote ?? (() => undefined)}
      />
    </QueryClientProvider>,
  );
  return { clientHref };
}

function clientRow(name = "Firma Testowa sp. z o.o.") {
  return screen.getByRole("button", { name }).closest("tr") as HTMLElement;
}

describe("StageTable: wiersz klienta", () => {
  beforeEach(() => vi.clearAllMocks());

  it("komplet: raporty, przyjęcia, KSeF i wystawiona faktura; „Zamknięte”, bez „Wystaw”", () => {
    renderTable();
    const tr = clientRow();
    // „4 os.” pod nazwą klienta i w notce wystawionej faktury.
    expect(within(tr).getAllByText("4 os.")).toHaveLength(2);
    expect(within(tr).getAllByText("4/4")).toHaveLength(2);
    expect(within(tr).getByText("komplet")).toBeInTheDocument();
    expect(within(tr).getByText("4/4 w KSeF")).toBeInTheDocument();
    expect(within(tr).getByText("Wystawiona")).toBeInTheDocument();
    expect(within(tr).getByText("Zamknięte")).toBeInTheDocument();
    expect(within(tr).queryByRole("link", { name: "Wystaw" })).not.toBeInTheDocument();
  });

  it("braki raportu z notką przypomnienia od rodzica", () => {
    const reminder = { client_id: 7 } as ReminderClient;
    renderTable({
      clients: [client({ stages: stages({ report: { in: 1, missing: 3 }, accept: { done: 0 }, client_invoice: { issued: 0 } }) })],
      reminders: new Map([[7, reminder]]),
      reminderNote: (r) => (r ? "przypomniano 05.01" : undefined),
    });
    const tr = clientRow();
    expect(within(tr).getByText("1/4")).toBeInTheDocument();
    expect(within(tr).getByText("3 brak")).toBeInTheDocument();
    expect(within(tr).getByText("przypomniano 05.01")).toBeInTheDocument();
    expect(within(tr).getByText("po przyjęciu RCP")).toBeInTheDocument();
    expect(within(tr).getByText("Konsultanci")).toBeInTheDocument();
  });

  it("kontrola: liczby w notce w liczbie pojedynczej i mnogiej, zera pominięte", () => {
    renderTable({
      clients: [
        client({
          top_reason: "Ponad zamówienie",
          stages: stages({
            check: { clean: 0, resolved: 1, fail: 1, warn: 2, unread: 0, no_md: 1, returned: 0 },
            accept: { done: 1, ready: 0 },
            client_invoice: { issued: 0 },
          }),
        }),
      ],
    });
    const tr = clientRow();
    expect(within(tr).getByText("0 bez uwag")).toBeInTheDocument();
    expect(within(tr).getByText("1 rozstrzygn.")).toBeInTheDocument();
    expect(within(tr).getByText(/1 błąd$/)).toBeInTheDocument();
    expect(within(tr).getByText(/2 uwagi$/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 bez MD zam\.$/)).toBeInTheDocument();
    expect(within(tr).queryByText(/nieodczyt/)).not.toBeInTheDocument();
    expect(within(tr).getByTitle("Najczęściej: Ponad zamówienie")).toBeInTheDocument();
    // Finanse (błąd) i Opiekun (zamówienie bez MD).
    expect(within(tr).getByText("Finanse")).toBeInTheDocument();
    expect(within(tr).getByText("Opiekun")).toBeInTheDocument();
  });

  it("kontrola: błędy i uwaga w drugiej formie", () => {
    renderTable({
      clients: [client({ stages: stages({ check: { clean: 0, fail: 2, warn: 1, unread: 3, returned: 1 }, client_invoice: { issued: 0 } }) })],
    });
    const tr = clientRow();
    expect(within(tr).getByText(/2 błędy$/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 uwaga$/)).toBeInTheDocument();
    expect(within(tr).getByText(/3 nieodczyt\.$/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 odesłane$/)).toBeInTheDocument();
  });

  it("do przyjęcia i automat, który przyjmie od dnia w styczniu", () => {
    renderTable({
      clients: [
        client({
          auto_accept: { count: 2, workday: 3, from: "2027-01-06" },
          stages: stages({ accept: { done: 2, ready: 2 }, client_invoice: { issued: 0, ready: 2 } }),
        }),
      ],
    });
    const tr = clientRow();
    expect(within(tr).getByText("2 do przyjęcia")).toBeInTheDocument();
    expect(within(tr).getByText("2 przyjmie automat od 06.01")).toBeInTheDocument();
    expect(within(tr).getByRole("link", { name: "Wystaw" })).toHaveAttribute(
      "href",
      "/finance?view=sales-invoices&siPeriod=2026-12&siView=issue&siClient=7",
    );
  });

  it("automat z zerem do przyjęcia pokazuje, ile przyjął", () => {
    renderTable({
      clients: [client({ auto_accept: { count: 0, workday: 3, from: "2027-01-06" }, stages: stages({ accept: { done: 4, auto: 3 } }) })],
    });
    expect(within(clientRow()).getByText("przyjął automat: 3")).toBeInTheDocument();
  });

  it("faktury kontraktorów: inna kwota i NIP do zatwierdzenia", () => {
    renderTable({
      clients: [client({ stages: stages({ contractor_invoice: { match: 1, differs: 2, nip: 1 }, client_invoice: { issued: 0 } }) })],
    });
    const tr = clientRow();
    expect(within(tr).getByText("4/4 w KSeF")).toBeInTheDocument();
    expect(within(tr).getByText(/2 inna kwota$/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 NIP do zatw\.$/)).toBeInTheDocument();
  });

  it("brak stanów z API (stages = undefined) nie wywraca wiersza: zera i „Wstrzymana”", () => {
    renderTable({ clients: [client({ stages: undefined })] });
    const tr = clientRow();
    expect(within(tr).getByText("0 os.")).toBeInTheDocument();
    expect(within(tr).getByText("Wstrzymana")).toBeInTheDocument();
    expect(within(tr).getByText("Zamknięte")).toBeInTheDocument();
  });

  it("link do ekranu klienta i do ekranu T4T dla klienta z raportu", () => {
    const { clientHref } = renderTable({
      clients: [client(), client({ client_id: 8, name: "Klient Raportowy", client_report: { all: 5, ok: 3, differs: 1, unmatched: 1, no_invoice: 1 } })],
    });
    expect(clientHref).toHaveBeenCalledWith(7, {});
    expect(clientHref).toHaveBeenCalledWith(8, { stSub: "t4t" });
    const links = screen.getAllByRole("link", { name: "Otwórz ekran klienta" });
    expect(links[1]).toHaveAttribute("href", "/finance?stClient=8&stSub=t4t");
  });
});

describe("StageTable: klient rozliczany z raportu (T4T)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rozpoznane osoby, zgodne faktury, różnice godzin i ruch Finansów", () => {
    renderTable({
      clients: [client({ name: "Klient Raportowy", contractor_in_ksef: 3, client_report: { all: 5, ok: 3, differs: 1, unmatched: 1, no_invoice: 1 } })],
    });
    const tr = clientRow("Klient Raportowy");
    expect(within(tr).getByText("raport klienta (T4T) · 5 os.")).toBeInTheDocument();
    expect(within(tr).getByText("Raport klienta")).toBeInTheDocument();
    expect(within(tr).getByText("4 z 5 rozpoznanych")).toBeInTheDocument();
    expect(within(tr).getByText("3 zgodne z fakturą")).toBeInTheDocument();
    expect(within(tr).getByText(/1 różnice godzin/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 bez faktury/)).toBeInTheDocument();
    expect(within(tr).getByText("3 w KSeF")).toBeInTheDocument();
    expect(within(tr).getByText("Finanse")).toBeInTheDocument();
  });

  it("pusty raport: „Brak raportu” i zamknięte bez różnic; rozwinięcie nie pyta o osoby", () => {
    renderTable({ clients: [client({ name: "Klient Raportowy", client_report: { all: 0, ok: 0, differs: 0, unmatched: 0, no_invoice: 0 } })] });
    const tr = clientRow("Klient Raportowy");
    expect(within(tr).getByText("Brak raportu")).toBeInTheDocument();
    expect(within(tr).getByText("0 zgodnych z fakturą")).toBeInTheDocument();
    expect(within(tr).getByText("Zamknięte")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Klient Raportowy" }));
    expect(mocks.get).not.toHaveBeenCalled();
  });
});

describe("StageTable: rozwinięcie osób klienta", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pyta o miesiąc klienta, sortuje od błędów, linkuje do karty osoby", async () => {
    mocks.get.mockResolvedValue({
      data: {
        rows: [
          settlementRow({ contract_id: 1, person: "Zofia Zamknięta", status: "accepted", contractor_invoice: "in_ksef", client_invoice: "issued" }),
          settlementRow({ contract_id: 2, person: "Bartek Błędny", status: "warnings", issue_level: "fail", issues: "Stawka inna" }),
          settlementRow({ contract_id: 3, person: "Anna Przykładowa", status: "missing", order_number: null }),
        ],
      },
    });
    const { clientHref } = renderTable();
    const toggle = screen.getByRole("button", { name: "Pokaż osoby" });
    fireEvent.click(toggle);
    expect(screen.getByText("Ładowanie osób…")).toBeInTheDocument();
    await screen.findByText("Bartek Błędny");
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements", { params: { client_id: 7, month: "2026-12" } });
    expect(screen.getByRole("button", { name: "Zwiń osoby" })).toHaveAttribute("aria-expanded", "true");
    const names = screen.getAllByRole("link").map((a) => a.textContent).filter((t) => t && /[a-z]/.test(t) && t !== "Otwórz ekran klienta");
    expect(names).toEqual(["Bartek Błędny", "Anna Przykładowa", "Zofia Zamknięta"]);
    expect(clientHref).toHaveBeenCalledWith(7, { stContract: "2" });
    expect(screen.getByText("brak numeru zamówienia")).toBeInTheDocument();
    expect(screen.getByText("Stawka inna")).toBeInTheDocument();
    // Zwinięcie chowa osoby.
    fireEvent.click(screen.getByRole("button", { name: "Zwiń osoby" }));
    expect(screen.queryByText("Bartek Błędny")).not.toBeInTheDocument();
  });

  it("awaria zapytania o osoby to komunikat błędu, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Firma Testowa sp. z o.o." }));
    expect(await screen.findByText("Nie udało się pobrać osób klienta.")).toBeInTheDocument();
  });

  it("ponad 12 osób: podgląd i „Pokaż wszystkich”", async () => {
    mocks.get.mockResolvedValue({
      data: { rows: Array.from({ length: 14 }, (_, i) => settlementRow({ contract_id: i + 1, person: `Osoba ${String(i + 1).padStart(2, "0")}` })) },
    });
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż osoby" }));
    await screen.findByText("Osoba 01");
    expect(screen.queryByText("Osoba 13")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkich (14)" }));
    expect(screen.getByText("Osoba 14")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż wszystkich/ })).not.toBeInTheDocument();
  });
});

describe("StageTable: biuro", () => {
  beforeEach(() => vi.clearAllMocks());

  it("błąd biura bez danych: wiersz z komunikatem", () => {
    renderTable({ teamError: "Nie udało się pobrać biura." });
    expect(screen.getByText("Biuro — B2B.Net")).toBeInTheDocument();
    expect(screen.getByText("Nie udało się pobrać biura.")).toBeInTheDocument();
  });

  it("puste biuro bez błędu: brak wiersza", () => {
    renderTable({ team: { month: "2026-12", people: [] } });
    expect(screen.queryByText("Biuro — B2B.Net")).not.toBeInTheDocument();
  });

  it("podsumowanie: ewidencje, zatwierdzone, KSeF, zapłaty, brak NIP-u i ruchy", () => {
    const team: TeamMonth = {
      month: "2026-12",
      people: [
        person({ user_id: 1, person: "Jan Testowy" }),
        person({ user_id: 2, person: "Ewa Fikcyjna", paid: false, paid_on: null }),
        person({ user_id: 3, person: "Piotr Próbny", invoice: "differs", paid: false }),
        person({ user_id: 4, person: "Ola Zmyślona", timesheet: "missing", invoice: "missing", paid: false, invoice_on: null }),
        person({ user_id: 5, person: "Adam Wymyślony", timesheet: "submitted", invoice: "no_nip", paid: false, invoice_on: null }),
      ],
    };
    renderTable({ team });
    const tr = screen.getByRole("button", { name: "Biuro — B2B.Net" }).closest("tr") as HTMLElement;
    expect(within(tr).getByText("5 os. na B2B")).toBeInTheDocument();
    expect(within(tr).getByText("4/5")).toBeInTheDocument();
    expect(within(tr).getByText("1 bez ewidencji")).toBeInTheDocument();
    expect(within(tr).getByText("3/5")).toBeInTheDocument();
    expect(within(tr).getByText("3/5 w KSeF")).toBeInTheDocument();
    expect(within(tr).getByText(/1 bez NIP-u/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 zapłacone/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 do zapłaty/)).toBeInTheDocument();
    expect(within(tr).getByText(/1 inna kwota/)).toBeInTheDocument();
    expect(within(tr).getByText("Nie dotyczy")).toBeInTheDocument();
    // Pokazujemy najwyżej dwa ruchy: Finanse (2) i Płace (NIP).
    expect(within(tr).getByText("Finanse")).toBeInTheDocument();
    expect(within(tr).getByText("Płace (NIP)")).toBeInTheDocument();
    expect(within(tr).queryByText("Osoby")).not.toBeInTheDocument();
  });

  it("rozwinięte biuro: osoby bez linków, posortowane od błędów, faktura do klienta „—”", () => {
    const team: TeamMonth = {
      month: "2026-12",
      people: [
        person({ user_id: 1, person: "Jan Testowy" }),
        person({ user_id: 2, person: "Adam Wymyślony", invoice: "no_nip", paid: false, invoice_on: null }),
      ],
    };
    renderTable({ team });
    fireEvent.click(screen.getByRole("button", { name: "Biuro — B2B.Net" }));
    const adam = screen.getByText("Adam Wymyślony").closest("tr") as HTMLElement;
    const jan = screen.getByText("Jan Testowy").closest("tr") as HTMLElement;
    expect(adam.compareDocumentPosition(jan) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(adam).getByText("Brak NIP-u")).toBeInTheDocument();
    expect(within(jan).getByText("W KSeF 03.01")).toBeInTheDocument();
    expect(within(jan).getByText("zapłacona 10.01")).toBeInTheDocument();
    expect(within(jan).getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("link", { name: "Jan Testowy" })).not.toBeInTheDocument();
  });

  it("biuro ponad 12 osób: „Pokaż wszystkich”", () => {
    const team: TeamMonth = {
      month: "2026-12",
      people: Array.from({ length: 13 }, (_, i) => person({ user_id: i + 1, person: `Pracownik ${String(i + 1).padStart(2, "0")}` })),
    };
    renderTable({ team });
    fireEvent.click(screen.getByRole("button", { name: "Biuro — B2B.Net" }));
    expect(screen.queryByText("Pracownik 13")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkich (13)" }));
    expect(screen.getByText("Pracownik 13")).toBeInTheDocument();
  });
});
