import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MonthCloseClient, MonthCloseOverview, MonthCloseStages, TeamMonth } from "@/lib/api/client-settlements";

import { MonthCloseView } from "../MonthCloseView";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));

// Podwidoki mają własne testy — tu sprawdzamy, co widok im przekazuje.
vi.mock("../MonthAnswers", () => ({
  MonthAnswers: (p: { month: string; team: TeamMonth | null; teamError: string | null; reminders: unknown; onShowIssues: () => void }) => (
    <div data-testid="answers" data-month={p.month} data-team={p.team ? p.team.people.length : "null"} data-team-error={p.teamError ?? ""} data-reminders={p.reminders ? "yes" : "no"}>
      <button type="button" onClick={p.onShowIssues}>
        Pokaż błędy z odpowiedzi
      </button>
    </div>
  ),
}));
vi.mock("../StageTable", () => ({
  StageTable: (p: { month: string; clientHref: (id: number, extra?: Record<string, string>) => string; reminders: Map<number, unknown> }) => (
    <div data-testid="stage-table" data-month={p.month} data-href={p.clientHref(7, { stSub: "t4t" })} data-reminders={p.reminders.size} />
  ),
}));
vi.mock("../IssuesByLevel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../IssuesByLevel")>()),
  IssuesByLevel: (p: { reasons: { key: string }[] }) => <div data-testid="issues">{p.reasons.map((r) => r.key).join(",")}</div>,
}));
vi.mock("../ClosingPanel", () => ({ ClosingPanel: (p: { month: string }) => <div data-testid="closing" data-month={p.month} /> }));

const STAGES: MonthCloseStages = {
  people: 6,
  report: { in: 5, missing: 1, md_auto: 5, md_manual: 0 },
  check: { clean: 2, auto_clean: 2, resolved: 0, warn: 1, fail: 1, returned: 1, unread: 1, no_md: 0, missing: 1 },
  accept: { done: 1, auto: 0, ready: 1 },
  contractor_invoice: { match: 0, differs: 0, nip: 0, can_issue: 0, none: 6, waiting: 1 },
  client_invoice: { issued: 0, ready: 1, waiting_client: 0, waiting: 5, issued_early: 0 },
  missing_order: 0,
};

function client(patch: Partial<MonthCloseClient> = {}): MonthCloseClient {
  return {
    client_id: 7,
    name: "Firma Testowa sp. z o.o.",
    people: 6,
    clean: 2,
    accepted: 1,
    decide: 2,
    unread: 1,
    missing: 1,
    contractor_in_ksef: 0,
    client_invoice_issued: 0,
    client_invoice_ready: 1,
    revenue_ready: null,
    top_reason: null,
    client_report: null,
    stages: STAGES,
    ...patch,
  };
}

function overview(patch: Partial<MonthCloseOverview> = {}): MonthCloseOverview {
  return {
    month: "2026-12",
    can_see_amounts: true,
    totals: { people: 6, clean: 2, accepted: 1, decide: 2, unread: 1, missing: 1, contractor_in_ksef: 0, client_invoice_issued: 0 },
    stages: STAGES,
    clients: [client()],
    reasons: [
      { key: "missing", title: "Brak raportu", count: 1, clients: [], people: [] },
      { key: "fields.md_hours", title: "Godziny", level: "fail", count: 1, clients: [], people: [] },
      { key: "no_md", title: "Bez MD", count: 1, clients: [], people: [] },
    ],
    closing: { ksef_not_accepted: 2, reserve_count: 3, reserve_total: "1000.00", reserve_without_cost: 0, sales_waiting: 1, rows: null },
    ...patch,
  };
}

interface Responses {
  overview?: MonthCloseOverview | Error | "pending";
  team?: TeamMonth | Error;
  reminders?: { clients: { client_id: number }[] } | Error;
}

function setup(res: Responses = {}) {
  mocks.get.mockImplementation((url: string) => {
    const pick = (v: unknown) =>
      v === "pending" ? new Promise(() => {}) : v instanceof Error ? Promise.reject(v) : Promise.resolve({ data: v });
    if (url.endsWith("/overview")) return pick(res.overview ?? overview());
    if (url.endsWith("/team")) return pick(res.team ?? { month: "2026-12", people: [] });
    if (url.endsWith("/reminders")) return pick(res.reminders ?? { clients: [] });
    return Promise.reject(new Error(`nieoczekiwany adres ${url}`));
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MonthCloseView />
    </QueryClientProvider>,
  );
}

function monthParams(): string[] {
  return mocks.get.mock.calls.filter(([url]) => String(url).endsWith("/overview")).map(([, cfg]) => cfg.params.month);
}

describe("MonthCloseView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ toFake: ["Date"] });
    // „Dziś” w styczniu: domyślny miesiąc rozliczeń to grudzień poprzedniego roku.
    vi.setSystemTime(new Date("2027-01-10T10:00:00+01:00"));
    window.history.replaceState(null, "", "/finance?view=month-close");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("domyślnie poprzedni miesiąc przez granicę roku; lista sześciu miesięcy od stycznia", async () => {
    setup();
    const select = screen.getByLabelText("Miesiąc rozliczeń") as HTMLSelectElement;
    expect(select.value).toBe("2026-12");
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["2027-01", "2026-12", "2026-11", "2026-10", "2026-09", "2026-08"]);
    expect(select.options[1].textContent).toBe("grudzień 2026");
    await screen.findByTestId("stage-table");
    expect(monthParams()).toContain("2026-12");
  });

  it("ładowanie przed odpowiedzią przeglądu", () => {
    setup({ overview: "pending" });
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
  });

  it("awaria przeglądu to komunikat błędu, nie „żaden klient nie ma kontraktów”", async () => {
    setup({ overview: new Error("boom") });
    expect(await screen.findByText("Nie udało się pobrać przebiegu miesiąca.")).toBeInTheDocument();
    expect(screen.queryByText(/żaden klient/)).not.toBeInTheDocument();
  });

  it("pusty miesiąc po udanym zapytaniu", async () => {
    setup({ overview: overview({ clients: [], stages: undefined }) });
    expect(await screen.findByText("W grudzień 2026 żaden klient nie ma kontraktów do rozliczenia.")).toBeInTheDocument();
    expect(screen.queryByTestId("stage-table")).not.toBeInTheDocument();
  });

  it("nagłówek: kontraktorzy, klienci bez T4T, biuro i klient z raportu", async () => {
    setup({
      overview: overview({
        clients: [client(), client({ client_id: 8, name: "Klient Raportowy", people: 4, client_report: { all: 5, ok: 5, differs: 0, unmatched: 0, no_invoice: 0 } })],
      }),
      team: { month: "2026-12", people: [{ user_id: 1, person: "Jan Testowy", timesheet: "approved", timesheet_on: null, invoice: "in_ksef", invoice_on: null, paid: true, paid_on: null }] },
    });
    await screen.findByTestId("stage-table");
    await waitFor(() => expect(screen.getByText(/os\. biura/)).toBeInTheDocument());
    const header = screen.getByText(/kontraktorów u/).closest("p") as HTMLElement;
    expect(header).toHaveTextContent("6 kontraktorów u 1 klientów · 1 os. biura · Klient Raportowy z raportu klienta (5 os.)");
    expect(screen.getByTestId("answers")).toHaveAttribute("data-team", "1");
  });

  it("klient z pustym raportem pokazuje 0 os. z raportu (zero to liczba, nie brak)", async () => {
    setup({
      overview: overview({
        clients: [client(), client({ client_id: 8, name: "Klient Raportowy", people: 4, client_report: { all: 0, ok: 0, differs: 0, unmatched: 0, no_invoice: 0 } })],
      }),
    });
    await screen.findByTestId("stage-table");
    expect(screen.getByText(/kontraktorów u/).closest("p")).toHaveTextContent("Klient Raportowy z raportu klienta (0 os.)");
  });

  it("błąd biura idzie do odpowiedzi jako komunikat, biuro nie liczy się w nagłówku", async () => {
    setup({ team: new Error("boom") });
    await waitFor(() => expect(screen.getByTestId("answers")).toHaveAttribute("data-team-error", "Nie udało się pobrać biura."));
    expect(screen.getByTestId("answers")).toHaveAttribute("data-team", "null");
    expect(screen.queryByText(/os\. biura/)).not.toBeInTheDocument();
  });

  it("zakładki: liczba spraw z etapów i suma dla księgowej", async () => {
    setup();
    await screen.findByTestId("stage-table");
    // fail 1 + warn 1 + unread 1 + no_md 0 + returned 1 = 4
    expect(screen.getByRole("button", { name: /^Błędy i uwagi\s*4$/ })).toBeInTheDocument();
    // 2 + 3 + 1 = 6
    expect(screen.getByRole("button", { name: /^Dla księgowej\s*6$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gdzie są rozliczenia" })).toHaveAttribute("aria-pressed", "true");
  });

  it("bez bloku dla księgowej licznik zakładki to 0", async () => {
    setup({ overview: overview({ closing: undefined }) });
    await screen.findByTestId("stage-table");
    expect(screen.getByRole("button", { name: /^Dla księgowej\s*0$/ })).toBeInTheDocument();
  });

  // Starsze API bez `stages`: licznik zakładki liczy powody z listy pod nią
  // (fields.md_hours, no_md), a nie zera z pustych etapów.
  it("bez `stages` w odpowiedzi licznik „Błędy i uwagi” liczy powody bez braków raportu", async () => {
    setup({ overview: overview({ stages: undefined }) });
    await screen.findByTestId("stage-table");
    expect(screen.getByRole("button", { name: /^Błędy i uwagi\s*2$/ })).toBeInTheDocument();
  });

  it("zakładka błędów dostaje powody bez braków raportu i zapisuje się w adresie", async () => {
    setup();
    await screen.findByTestId("stage-table");
    fireEvent.click(screen.getByRole("button", { name: /^Błędy i uwagi/ }));
    expect(screen.getByTestId("issues")).toHaveTextContent("fields.md_hours,no_md");
    expect(new URLSearchParams(window.location.search).get("mcTab")).toBe("reasons");
    fireEvent.click(screen.getByRole("button", { name: /^Dla księgowej/ }));
    expect(screen.getByTestId("closing")).toHaveAttribute("data-month", "2026-12");
    expect(new URLSearchParams(window.location.search).get("mcTab")).toBe("closing");
    fireEvent.click(screen.getByRole("button", { name: "Gdzie są rozliczenia" }));
    expect(new URLSearchParams(window.location.search).has("mcTab")).toBe(false);
    expect(new URLSearchParams(window.location.search).get("view")).toBe("month-close");
  });

  it("„Pokaż błędy” z odpowiedzi przełącza na zakładkę błędów", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Pokaż błędy z odpowiedzi" }));
    expect(screen.getByTestId("issues")).toBeInTheDocument();
  });

  it("zmiana miesiąca pyta o nowy miesiąc i zapisuje go w adresie", async () => {
    setup();
    await screen.findByTestId("stage-table");
    fireEvent.change(screen.getByLabelText("Miesiąc rozliczeń"), { target: { value: "2027-01" } });
    await waitFor(() => expect(monthParams()).toContain("2027-01"));
    expect(new URLSearchParams(window.location.search).get("mcMonth")).toBe("2027-01");
  });

  it("miesiąc i zakładka z adresu; miesiąc spoza listy dochodzi na początek", async () => {
    window.history.replaceState(null, "", "/finance?mcMonth=2025-12&mcTab=closing");
    setup();
    const select = screen.getByLabelText("Miesiąc rozliczeń") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("2025-12"));
    expect(select.options[0].value).toBe("2025-12");
    expect(await screen.findByTestId("closing")).toHaveAttribute("data-month", "2025-12");
  });

  it("zły miesiąc i nieznana zakładka w adresie są ignorowane", async () => {
    window.history.replaceState(null, "", "/finance?mcMonth=grudzien&mcTab=xyz");
    setup();
    expect(await screen.findByTestId("stage-table")).toHaveAttribute("data-month", "2026-12");
  });

  it("tabela dostaje adres klienta z miesiącem i przypomnienia po kliencie", async () => {
    setup({ reminders: { clients: [{ client_id: 7 }, { client_id: 8 }] } });
    const table = await screen.findByTestId("stage-table");
    expect(table).toHaveAttribute("data-href", "/finance?view=settlements&stClient=7&stMonth=2026-12&stSub=t4t");
    await waitFor(() => expect(screen.getByTestId("stage-table")).toHaveAttribute("data-reminders", "2"));
    expect(screen.getByTestId("answers")).toHaveAttribute("data-reminders", "yes");
  });

  it("awaria przypomnień nie zatrzymuje widoku", async () => {
    setup({ reminders: new Error("boom") });
    const table = await screen.findByTestId("stage-table");
    expect(table).toHaveAttribute("data-reminders", "0");
    expect(screen.getByTestId("answers")).toHaveAttribute("data-reminders", "no");
  });
});
