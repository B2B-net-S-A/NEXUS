/**
 * „Mój czas → Przegląd” (etap 2, D1): każda karta ma własny stan — awaria to
 * zdanie z ponowieniem, nigdy „0”; wyłączony moduł = brak karty i brak
 * zapytania; premie „w drodze” z etapami; słowa zależne od formy zatrudnienia.
 * Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig, HrModuleKey, OwnProfile } from "@/lib/api/hr";
import type { LeaveBalance } from "@/lib/api/hr-leave";
import type { MyPayroll } from "@/lib/api/hr-payroll";
import type { MonthDay, MonthView } from "@/lib/api/hr-time";
import { monthYearPl, shiftMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

const mocks = vi.hoisted(() => ({ get: vi.fn(), toast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { currentYearMonth } from "../../time/time-format";
import { MyOverviewTab } from "../MyOverviewTab";

const today = warsawToday();
const year = Number(today.slice(0, 4));
const current = currentYearMonth();
const nbsp = (text: string | null) => (text ?? "").replace(/\s/g, " ");

const ALL: Record<HrModuleKey, boolean> = {
  people: true,
  leave: true,
  time: true,
  payroll: true,
  lifecycle: true,
  care: false,
  cases: false,
  equipment: true,
  settlements: false,
  approvals: false,
};

function config(open: Partial<Record<HrModuleKey, boolean>> = {}): HrConfig {
  const modules = { ...ALL, ...open };
  return {
    program: true,
    modules,
    open_modules: modules,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      settlements: false,
      approvals: false,
      cases: false,
    },
  } as HrConfig;
}

function person(form: OwnProfile["employment_type"] = "b2b"): OwnProfile {
  return {
    user_id: 7,
    name: "Ola Przykładowa",
    email: "ola@example.com",
    job_title: "Rekruterka",
    department: "Rekrutacja",
    phone: null,
    default_location: "onsite",
    employment_status: "active",
    manager_user_id: 3,
    manager_name: "Marta Fikcyjna",
    scope: "full",
    employment_type: form,
    employment_type_pending: false,
    hired_on: "2025-03-03",
    work_start_date: "2025-03-03",
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
    entitlements: [],
  } as OwnProfile;
}

function balance(over: Partial<LeaveBalance> = {}): LeaveBalance {
  return {
    year,
    employment_type: "b2b",
    has_pool: true,
    has_paid_pool: true,
    entitlement_days: "24.0",
    carried_over_days: "2.0",
    used_initial_days: "0.0",
    as_of: today,
    approved_days: "14.5",
    used_days: "12.0",
    planned_days: "2.5",
    pending_days: "0.0",
    unpaid_days: "0.0",
    remaining_days: "11.5",
    on_demand_used: null,
    on_demand_limit: null,
    childcare_used: null,
    childcare_limit: null,
    allowed_types: ["vacation"],
    ...over,
  };
}

function monthView(form: MonthView["employment_type"] = "b2b"): MonthView {
  return {
    user_id: 7,
    name: "Ola Przykładowa",
    year: current.year,
    month: current.month,
    deadline: `${current.year}-${String(current.month).padStart(2, "0")}-28`,
    employment_type: form,
    default_location: "onsite",
    can_log_overtime: false,
    approver_name: "Marta Fikcyjna",
    timesheet: null,
    days: [],
    totals: {
      work_hours: 121,
      leave_paid_hours: 0,
      overtime_hours: 0,
      leave_days: 0,
      working_days: 22,
      norm_hours: 176,
      days_missing: 4,
    },
  };
}

const PAYROLL: MyPayroll = {
  current_rate: {
    id: 1,
    user_id: 7,
    hourly_rate: "95.00",
    currency: "PLN",
    effective_from: `${year}-10-01`,
    effective_to: null,
    reason: null,
    set_by: 2,
  },
  rates: [],
  bonuses: [
    {
      id: 5,
      recipient_user_id: 7,
      recipient_name: "Ola Przykładowa",
      proposed_by: null,
      proposed_by_name: null,
      amount: "1500.00",
      currency: "PLN",
      category: "recruiter",
      category_label: "Rekruter",
      period_year: year,
      period_month: 11,
      status: "proposed",
      source: "contract_placement",
      contract_id: 10,
      eligible_on: `${year}-11-05`,
      eligible: false,
      description: "Premia rekrutera — placement: Piotr Testowy (Firma Fikcyjna)",
      assigned_by: null,
      assigned_at: null,
      cancelled_at: null,
      cancel_reason: null,
      edited: false,
      business_days_elapsed: 14,
      business_days_required: 21,
    },
  ],
  forecast: [
    {
      key: "contract:20:recruiter",
      contract_id: 20,
      role: "recruiter",
      category: "recruiter",
      category_label: "Rekruter",
      description: "Premia rekrutera — placement: Jan Przykładowy (Bank Fikcyjny)",
      amount: "2000.00",
      currency: "PLN",
      amount_missing_reason: null,
      start_date: `${year}-11-02`,
      started: false,
      eligible_on: `${year}-12-01`,
      business_days_elapsed: 0,
      business_days_required: 21,
    },
  ],
  business_days_required: 21,
};

type Routes = Record<string, unknown | Error>;

function route(routes: Routes) {
  mocks.get.mockImplementation(async (url: string) => {
    const value = routes[url];
    if (value instanceof Error) throw Object.assign(value, { response: { status: 500 } });
    if (value === undefined) throw Object.assign(new Error(url), { response: { status: 500 } });
    return { data: value };
  });
}

const monthUrl = `/api/hr/time/me/${current.year}/${current.month}`;

function healthy(over: Routes = {}): Routes {
  return {
    "/api/hr/leave/balance": balance(),
    "/api/hr/leave/my-requests": { items: [] },
    "/api/hr/leave/absence": { on: today, items: [] },
    [monthUrl]: monthView(),
    "/api/hr/time/me/history": { items: [] },
    "/api/hr/payroll/me": PAYROLL,
    "/api/equipment/me": { active: [], history: [], protocols: [] },
    "/api/hr/lifecycle/my-tasks": { items: [] },
    ...over,
  };
}

function renderTab(cfg = config(), who = person(), onOpenTab = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MyOverviewTab config={cfg} person={who} onOpenTab={onOpenTab} />
    </QueryClientProvider>,
  );
}

/** Dzień roboczy do dziś bez wpisu — liczy się do „dni do uzupełnienia”. */
const emptyWorkday = { date: today, working_day: true, entries: [], leave: null } as unknown as MonthDay;

// Zapytanie o rolę w dużym drzewie (mini-kalendarz) bywa wolne pod obciążeniem — dłuższy limit.
const card = (name: string | RegExp) => screen.findByRole("generic", { name }, { timeout: 5000 });

describe("MyOverviewTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("B2B z pulą: płatne dni przerwy z trzema liczbami, raport godzin, premie w drodze", async () => {
    route(healthy());
    renderTab();

    const days = await card("Płatne dni przerwy (z umowy)");
    expect(await within(days).findByText(/zostało/)).toBeInTheDocument();
    expect(within(days).getByText(/wykorzystane 12 dni/)).toBeInTheDocument();
    expect(within(days).getByText(/zaplanowane 2,5 dnia/)).toBeInTheDocument();
    expect(within(days).queryByText(/na żądanie|opieka/i)).toBeNull();
    expect(nbsp(days.textContent)).not.toMatch(/urlop/i);

    const month = await card(`Raport godzin · ${["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"][current.month - 1]}`);
    expect(await within(month).findByText("121 / 176 h")).toBeInTheDocument();

    // B2B: „Wynagrodzenie dodatkowe” zamiast „Premii” (21.10.2026).
    const bonuses = await card("Wynagrodzenie dodatkowe");
    const transit = (await within(bonuses).findByText("w drodze")).closest("p");
    expect(nbsp(transit?.textContent ?? null)).toContain("~ 3500,00 zł");
    // Etapy: prognoza z podpisanej umowy i propozycja w trakcie 21 dni.
    expect(within(bonuses).getByText(/umowa podpisana/)).toBeInTheDocument();
    expect(within(bonuses).getByText(/14 z 21 dni/)).toBeInTheDocument();
    expect(nbsp(bonuses.textContent)).toContain("stawka 95,00 zł/h od 01.10");

    // B2B: koordynator i zgłoszenie, nie „przełożony” i „wniosek” (D4, D5).
    // Karta „Ja w firmie” zastępuje zakładkę „Kartoteka” (21.10.2026).
    const me = await card("Ja w firmie");
    expect(within(me).getByText("Koordynator")).toBeInTheDocument();
    expect(within(me).queryByText("Przełożony")).toBeNull();
    expect(within(me).getByText(/wskazujesz w zgłoszeniu/)).toBeInTheDocument();
    expect(within(me).getByRole("link", { name: "Otwórz kartotekę" })).toBeInTheDocument();
  });

  it("awaria zapytania to komunikat w karcie, nie „0”", async () => {
    route(
      healthy({
        "/api/hr/leave/balance": new Error("500"),
        "/api/hr/payroll/me": new Error("500"),
        [monthUrl]: new Error("500"),
      }),
    );
    renderTab();

    expect(await screen.findByText("Nie udało się wczytać nieobecności.")).toBeInTheDocument();
    expect(await screen.findByText("Nie udało się wczytać wynagrodzenia dodatkowego.")).toBeInTheDocument();
    expect(await screen.findByText("Nie udało się wczytać miesiąca.")).toBeInTheDocument();
    expect(screen.queryByText(/zostało/)).toBeNull();
    expect(screen.queryByText(/w drodze/)).toBeNull();
    expect(screen.queryByText(/0 \/ /)).toBeNull();
    expect(screen.getAllByRole("button", { name: "Spróbuj ponownie" }).length).toBeGreaterThanOrEqual(3);
  });

  it("wyłączone moduły: brak kart i brak zapytań; przełożony i zadania zostają", async () => {
    route(healthy());
    renderTab(
      config({ leave: false, time: false, payroll: false, equipment: false, lifecycle: false }),
    );

    expect(await screen.findByText("Marta Fikcyjna")).toBeInTheDocument();
    expect(screen.getByText("Nic do zrobienia.")).toBeInTheDocument();
    expect(screen.queryByRole("generic", { name: /Płatne dni|Urlop|Nieobecności/ })).toBeNull();
    expect(screen.queryByRole("generic", { name: /Premie|Wynagrodzenie dodatkowe/ })).toBeNull();
    expect(screen.queryByRole("generic", { name: "Mój sprzęt" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Zgłoś nieobecność|Uzupełnij dzień/ })).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("B2B bez puli i zlecenie: „Nieobecności” bez „zostało”, potwierdzenie godzin z art. 8b", async () => {
    route(
      healthy({
        "/api/hr/leave/balance": balance({
          employment_type: "zlecenie",
          has_pool: false,
          has_paid_pool: false,
          entitlement_days: null,
          remaining_days: null,
          used_days: "1.0",
          planned_days: "3.0",
        }),
        [monthUrl]: monthView("zlecenie"),
      }),
    );
    renderTab(config(), person("zlecenie"));

    const absences = await card(`Nieobecności ${year}`);
    const planned = (await within(absences).findByText("zaplanowane")).closest("p");
    expect(nbsp(planned?.textContent ?? null)).toBe("3 dni zaplanowane");
    expect(within(absences).queryByText(/zostało/)).toBeNull();
    expect(nbsp(absences.textContent)).not.toMatch(/urlop/i);
    expect(await screen.findByText(/art\. 8b ustawy o minimalnym wynagrodzeniu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zgłoś nieobecność" })).toBeInTheDocument();
  });

  it("UoP: urlop z limitami Kodeksu, protokół do podpisu i timesheet w zadaniach", async () => {
    route(
      healthy({
        "/api/hr/leave/balance": balance({
          employment_type: "uop",
          on_demand_used: "1.0",
          on_demand_limit: "4.0",
          childcare_used: "0.0",
          childcare_limit: "2.0",
        }),
        [monthUrl]: monthView("uop"),
        "/api/equipment/me": {
          active: [],
          history: [],
          protocols: [
            { id: 9, number: "PZO/TEST/2026/011", kind: "zwrot", status: "oczekuje", protocol_date: `${year}-10-20` },
          ],
        },
      }),
    );
    renderTab(config(), person("uop"));

    const leave = await card(`Urlop ${year}`);
    // UoP: słowa bez zmian — karta „Premie”.
    expect(await card("Premie")).toBeInTheDocument();
    expect(await within(leave).findByText(/Na żądanie 1 z 4 · opieka nad dzieckiem 0 z 2/)).toBeInTheDocument();
    const todo = await card("Do zrobienia");
    expect(await within(todo).findByText("Podpisz protokół PZO/TEST/2026/011")).toBeInTheDocument();
    expect(within(todo).getByText(/Wyślij ewidencję czasu pracy za/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Złóż wniosek urlopowy" })).toBeInTheDocument();
    const manager = await card("Ja w firmie");
    expect(within(manager).getByText("Przełożony")).toBeInTheDocument();
    expect(within(manager).getByText(/wskazujesz we wniosku/)).toBeInTheDocument();
  });

  it("osoba bez obowiązku timesheetu: bez „dni do uzupełnienia” i bez „Uzupełnij dzień”", async () => {
    route(healthy({ [monthUrl]: { ...monthView(), days: [emptyWorkday] } }));
    renderTab(config(), { ...person(), timesheet_required: false });

    const month = await card(/^Raport godzin · /);
    expect(await within(month).findByText(/Bez obowiązku raportu godzin/)).toBeInTheDocument();
    expect(nbsp(month.textContent)).not.toMatch(/do uzupełnienia|wyślij do/i);
    expect(screen.queryByRole("button", { name: "Uzupełnij dzień" })).toBeNull();
    expect(await screen.findByText("Nic do zrobienia.")).toBeInTheDocument();
  });

  it("z obowiązkiem timesheetu: dzień bez wpisu do uzupełnienia i przycisk „Uzupełnij dzień”", async () => {
    route(healthy({ [monthUrl]: { ...monthView(), days: [emptyWorkday] } }));
    renderTab();

    const month = await card(/^Raport godzin · /);
    expect(await within(month).findByText(/1 dzień do uzupełnienia/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uzupełnij dzień" })).toBeInTheDocument();
  });

  it("mini-kalendarz: brakujący dzień to przycisk, który otwiera miesiąc", async () => {
    route(healthy({ [monthUrl]: { ...monthView(), days: [{ ...emptyWorkday, weekday: 1 }] } }));
    const onOpenTab = vi.fn();
    renderTab(config(), person(), onOpenTab);

    const month = await card(/^Raport godzin · /);
    const days = await within(month).findByRole("group", { name: "Dni miesiąca" });
    fireEvent.click(within(days).getByRole("button", { name: /brak wpisu — uzupełnij/ }));
    expect(onOpenTab).toHaveBeenCalledWith("month");
    expect(within(month).getByText(/^Brakuje dziś/)).toBeInTheDocument();
    expect(within(month).getByRole("progressbar", { name: "Godziny miesiąca wobec normy" })).toHaveAttribute(
      "aria-valuenow",
      "69",
    );
  });

  it("zaległy raport z „Do zrobienia” otwiera swój miesiąc, nie bieżący", async () => {
    const overdue = shiftMonth(current, -2);
    route(
      healthy({
        "/api/hr/time/me/history": {
          items: [{ id: 9, ...overdue, status: "draft", approved_at: null, hours: 0 }],
        },
      }),
    );
    const onOpenTab = vi.fn();
    renderTab(config(), person(), onOpenTab);

    const todo = await card("Do zrobienia");
    fireEvent.click(
      await within(todo).findByRole("button", { name: `Wyślij raport godzin za ${monthYearPl(overdue)}` }),
    );
    expect(onOpenTab).toHaveBeenCalledWith("month", overdue);
  });
});
