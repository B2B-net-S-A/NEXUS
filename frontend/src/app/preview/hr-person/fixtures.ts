/**
 * Dane harnessu `/preview/hr-person` (makieta 6 „Kartoteka osoby”) oraz
 * pomocnicy wspólni dla harnessów kartoteki, płac, odejścia i wejścia:
 * katalog osób, błąd HTTP w cache i dni
 * robocze w przód / w tył. Kandydaci do przeniesienia do `hr-fixtures.ts`
 * i `hr-harness.tsx`.
 *
 * Osoby, numery, kwoty i egzemplarze sprzętu są ZMYŚLONE (repo publiczne).
 */

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { HolderEquipment, AssignmentRow } from "@/lib/api/equipment";
import type { EmploymentStatus, EmploymentType, PersonCard, PersonFull } from "@/lib/api/hr";
import type { LeaveType } from "@/lib/api/hr-leave";
import type { RateRow } from "@/lib/api/hr-payroll";
import type {
  AbsenceState,
  PersonAbsence,
  PersonHistory,
  PersonTimesheetMonth,
} from "@/lib/api/hr-person-history";

import { HR_CAST, harnessMonthDays, shiftDay, type HarnessPerson } from "../hr-fixtures";

/**
 * Zapytanie w stanie błędu HTTP (403/404) bez wysyłki: `retryOnMount: false`
 * z `harnessQueryClient()` sprawia, że hook nie ponawia go przy montowaniu,
 * a ekran widzi to samo co po odmowie serwera (np. sekcja się chowa).
 */
export function seedHttpError(
  client: QueryClient,
  queryKey: QueryKey,
  status: number,
  detail: string,
): void {
  const error = Object.assign(new Error(detail), {
    status,
    response: { status, data: { detail } },
  });
  client.getQueryCache().build(client, { queryKey }).setState({
    status: "error",
    fetchStatus: "idle",
    error,
    errorUpdateCount: 1,
    errorUpdatedAt: Date.now(),
    fetchFailureCount: 1,
    fetchFailureReason: error,
  });
}

// ── Dni robocze ─────────────────────────────────────────────────────────────

export function isHarnessWorkDay(day: string): boolean {
  return harnessMonthDays(day.slice(0, 7)).some((d) => d.date === day && d.kind === "work");
}

/** N-ty dzień roboczy po `day` (ujemne N — przed); `0` = najbliższy roboczy od `day`. */
export function addWorkDays(day: string, n: number): string {
  let current = day;
  if (n === 0) {
    while (!isHarnessWorkDay(current)) current = shiftDay(current, 1);
    return current;
  }
  const step = n > 0 ? 1 : -1;
  let left = Math.abs(n);
  while (left > 0) {
    current = shiftDay(current, step);
    if (isHarnessWorkDay(current)) left -= 1;
  }
  return current;
}

/**
 * Chwila `HH:MM` dnia `day` w czasie firmy (Europe/Warsaw) jako ISO UTC —
 * tak jak serwer podaje `handover_at` (18:00 ostatniego dnia).
 */
export function warsawMomentIso(day: string, hour: number): string {
  const probe = new Date(`${day}T12:00:00Z`);
  const warsawHour = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Warsaw",
      hour: "2-digit",
      hourCycle: "h23",
    }).format(probe),
  );
  const offset = warsawHour - 12;
  return `${day}T${String(hour - offset).padStart(2, "0")}:00:00Z`;
}

// ── Katalog osób ────────────────────────────────────────────────────────────

const { ola, ewa, tomasz, julia, marta, kacper, admin } = HR_CAST;

/** Przełożeni obsady (makieta: Marta prowadzi zespół Rekrutacji IT). */
const MANAGER_OF: Record<number, HarnessPerson | null> = {
  [ola.id]: marta,
  [ewa.id]: marta,
  [tomasz.id]: marta,
  [julia.id]: marta,
  [kacper.id]: marta,
  [admin.id]: null,
};

export function managerOf(person: HarnessPerson): HarnessPerson | null {
  return person.id in MANAGER_OF ? MANAGER_OF[person.id] : admin;
}

/** Wyraźnie zmyślony telefon służbowy: `+48 500 000 1NN`. */
export function harnessPhone(person: HarnessPerson): string {
  return `+48 500 000 ${String(person.id).padStart(3, "0")}`;
}

export function personCard(
  person: HarnessPerson,
  status: EmploymentStatus = "active",
): PersonCard {
  const manager = managerOf(person);
  return {
    user_id: person.id,
    name: person.name,
    email: person.email,
    job_title: person.jobTitle,
    department: person.department,
    phone: harnessPhone(person),
    default_location: "onsite",
    employment_status: status,
    manager_user_id: manager?.id ?? null,
    manager_name: manager?.name ?? null,
    scope: "card",
  };
}

/**
 * Katalog `GET /api/hr/people` — cała obsada z kartoteką. Kacper (nowa osoba)
 * kartoteki jeszcze nie ma, więc go tu nie ma.
 */
export function harnessDirectory(
  statuses: Partial<Record<number, EmploymentStatus>> = {},
): { items: PersonCard[]; total: number } {
  const items = Object.values(HR_CAST)
    .filter((person) => person.id !== kacper.id)
    .map((person) => personCard(person, statuses[person.id] ?? "active"))
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));
  return { items, total: items.length };
}

// ── Kartoteka Oli (makieta 6) ───────────────────────────────────────────────

/** Rok puli urlopu — liczony jak w `PersonProfile` (Europe/Warsaw). */
export function harnessLeaveYear(): number {
  return Number(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric" }).format(
      new Date(),
    ),
  );
}

/**
 * Pełna kartoteka Oli. `form` (etap 2, D6–D9): B2B z umowną pulą (domyślnie),
 * zlecenie ze znacznikiem studenta (bez puli, składki od dnia po końcu
 * zwolnienia), umowa o pracę ze stażem do urlopu i zaświadczeniem ZUS.
 */
export function olaFull(form: EmploymentType = "b2b"): PersonFull {
  if (form === "zlecenie") {
    return {
      ...olaFull("b2b"),
      employment_type: "zlecenie",
      student_contribution_exempt: true,
      contribution_exempt_until: "2027-06-30",
      contributions_from: "2027-07-01",
      entitlements: [],
    };
  }
  if (form === "uop") {
    return {
      ...olaFull("b2b"),
      employment_type: "uop",
      leave_seniority_years: 12,
      zus_certificate_received_on: "2026-05-04",
      suggested_entitlement_days: 26,
    };
  }
  return {
    ...personCard(ola),
    scope: "full",
    employment_type: "b2b",
    employment_type_pending: false,
    student_contribution_exempt: false,
    hired_on: "2025-03-03",
    work_start_date: "2025-03-03",
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
    entitlements: [
      {
        year: harnessLeaveYear(),
        entitlement_days: "26",
        carried_over_days: "2",
        used_initial_days: "16.5",
      },
    ],
  };
}

/**
 * Kartoteka Oli tak, jak ją dostają Kadry bez Płac (decyzja Artura 19.10.2026):
 * bez formy umowy i bez pól, z których formę da się odczytać.
 */
export function olaWithoutForm(): PersonFull {
  const {
    student_contribution_exempt: _student,
    contribution_exempt_until: _until,
    contributions_from: _from,
    leave_seniority_years: _seniority,
    zus_certificate_received_on: _zus,
    suggested_entitlement_days: _suggested,
    ...rest
  } = olaFull("b2b");
  return { ...rest, employment_type: null };
}

/** Kartoteka założona automatem z konta: forma i przełożony do uzupełnienia. */
export function olaFromAccount(): PersonFull {
  return {
    ...olaFull("b2b"),
    employment_type_pending: true,
    manager_pending: true,
    manager_user_id: null,
    manager_name: null,
    job_title: null,
    department: null,
    hired_on: null,
    work_start_date: null,
    entitlements: [],
  };
}

export const OLA_RATES: RateRow[] = [
  {
    id: 502,
    user_id: ola.id,
    hourly_rate: "120.00",
    currency: "PLN",
    effective_from: "2026-07-01",
    effective_to: null,
    reason: "Aneks: nowa stawka od lipca",
    set_by: HR_CAST.paulina.id,
  },
  {
    id: 501,
    user_id: ola.id,
    hourly_rate: "110.00",
    currency: "PLN",
    effective_from: "2025-03-03",
    effective_to: "2026-06-30",
    reason: "Stawka startowa z umowy",
    set_by: HR_CAST.paulina.id,
  },
];

const PROTOCOL = { id: 9001, number: "PZO/2025/03/006" };

function issued(
  id: number,
  category: AssignmentRow["category"],
  model: string,
  inventory: string,
  extra: Partial<AssignmentRow>,
  value: string | null,
): AssignmentRow {
  return {
    assignment_id: 9100 + id,
    item_id: 9200 + id,
    category,
    model_name: model,
    inventory_number: inventory,
    serial_number: null,
    imei: null,
    phone_number: null,
    access_card_number: null,
    ownership: "nasz",
    item_status: "wydany",
    holder: { kind: "user", id: ola.id, name: ola.name, client_name: null },
    issued_at: "2025-03-03",
    returned_at: null,
    return_condition: null,
    return_notes: null,
    issue_protocol: PROTOCOL.number,
    issue_protocol_id: PROTOCOL.id,
    return_protocol: null,
    return_protocol_id: null,
    unit_value: value,
    ...extra,
  };
}

/** Sprzęt Oli: 4 pozycje z jednego protokołu (makieta: razem 5 148,00 zł). */
export const OLA_EQUIPMENT: HolderEquipment = {
  active: [
    issued(1, "laptop", "Dell Latitude 5520", "153", { serial_number: "SN-TEST-0153" }, "3200.00"),
    issued(2, "monitor", "Dell P2422H", "M-044", { serial_number: "SN-TEST-0044" }, "749.00"),
    issued(3, "akcesorium", "Słuchawki Jabra Evolve2 75", "J-012", { serial_number: "SN-TEST-0012" }, "1199.00"),
    issued(4, "karta_dostepu", "ogólny + biuro", "K-1420", { access_card_number: "CARD-TEST-1420" }, null),
  ],
  history: [],
  protocols: [
    {
      id: PROTOCOL.id,
      number: PROTOCOL.number,
      kind: "wydanie",
      status: "potwierdzony",
      protocol_date: "2025-03-03",
    },
  ],
};

// ── „Nieobecności i godziny” (`GET /api/hr/people/{id}/history`, 22.10.2026) ──

/**
 * Historia Oli w roku `year`: urlop/przerwa wykorzystana, zaplanowana,
 * czekająca i odrzucona; przy UoP także L4. `typeVisible = false` (Finanse
 * spoza kręgu D6) — tylko zatwierdzone, „Nieobecność”; `formVisible = false`
 * (Kadry bez Płac) — rodzaj z puli to „Nieobecność”. Raporty godzin: bieżący
 * szkic, wysłany, zaakceptowane z PDF i miesiąc bez raportu.
 */
export function olaHistory(
  form: EmploymentType,
  year: number,
  { typeVisible = true, formVisible = true }: { typeVisible?: boolean; formVisible?: boolean } = {},
): PersonHistory {
  const poolLabel = !typeVisible || !formVisible
    ? "Nieobecność"
    : form === "uop"
      ? "Urlop wypoczynkowy"
      : form === "b2b"
        ? "Przerwa w świadczeniu usług"
        : "Nieobecność";
  const label = (special: string) => (typeVisible ? special : "Nieobecność");
  const absence = (
    id: string,
    start: string,
    end: string,
    days: string,
    state: AbsenceState,
    leaveType: LeaveType = "vacation",
    text = poolLabel,
  ): PersonAbsence => ({
    id,
    start_date: `${year}-${start}`,
    end_date: `${year}-${end}`,
    half_day: null,
    days_total: days,
    status: state === "waiting" ? "pending" : state === "rejected" ? "rejected" : "approved",
    state,
    leave_type: typeVisible ? leaveType : null,
    label: text,
  });
  const all = [
    absence("h-1", "12-21", "12-23", "3.0", "planned"),
    absence("h-2", "11-12", "11-12", "1.0", "waiting"),
    absence("h-3", "07-14", "07-25", "10.0", "used"),
    ...(form === "uop"
      ? [absence("h-4", "03-09", "03-11", "3.0", "used", "sick_leave", label("Zwolnienie lekarskie (L4)"))]
      : []),
    absence("h-5", "05-04", "05-04", "1.0", "rejected"),
  ];
  const months = Array.from({ length: 6 }, (_, back) => {
    const date = new Date(Date.UTC(year, new Date().getUTCMonth() - back, 1));
    return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1 };
  });
  const timesheets: PersonTimesheetMonth[] = months.map((month, index) => ({
    ...month,
    timesheet_id: index === 4 ? null : 7000 + index,
    status: index === 0 ? "draft" : index === 1 ? "submitted" : index === 4 ? null : "approved",
    hours: index === 0 ? 64 : index === 4 ? 0 : 168,
    norm_hours: 168,
    has_pdf: index >= 2 && index !== 4,
  }));
  return {
    year,
    today: `${year}-10-22`,
    absences: {
      type_visible: typeVisible,
      items: typeVisible ? all : all.filter((item) => item.status === "approved"),
    },
    timesheets: { timesheet_required: true, items: timesheets },
  };
}
