/**
 * Dane harnessu `/preview/hr-person` (makieta 6 „Kartoteka osoby”) oraz
 * pomocnicy wspólni dla harnessów kartoteki, płac, odejścia i wejścia:
 * katalog osób, klucze nieeksportowanych hooków, błąd HTTP w cache i dni
 * robocze w przód / w tył. Kandydaci do przeniesienia do `hr-fixtures.ts`
 * i `hr-harness.tsx`.
 *
 * Osoby, numery, kwoty i egzemplarze sprzętu są ZMYŚLONE (repo publiczne).
 */

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { HolderEquipment, AssignmentRow } from "@/lib/api/equipment";
import type { EmploymentStatus, PersonCard, PersonFull } from "@/lib/api/hr";
import type { CaseKind, TransferKind } from "@/lib/api/hr-lifecycle";
import type { RateRow } from "@/lib/api/hr-payroll";

import { HR_CAST, harnessMonthDays, shiftDay, type HarnessPerson } from "../hr-fixtures";

// ── Klucze hooków, które ich nie eksportują ─────────────────────────────────

/** Lustro nieeksportowanego `keys` z `lib/api/hr.ts`. */
export const HR_PEOPLE_KEYS = {
  people: ["hr", "people"] as const,
  person: (userId: number) => ["hr", "people", userId] as const,
  withoutProfile: ["hr", "admin", "users-without-profile"] as const,
};

/** Lustro nieeksportowanego `keys` z `lib/api/hr-lifecycle.ts`. */
export const LIFECYCLE_KEYS = {
  templates: (kind: CaseKind | null) => ["hr", "lifecycle", "templates", kind] as const,
  case: (id: number) => ["hr", "lifecycle", "case", id] as const,
  receivers: (id: number, kind: TransferKind) =>
    ["hr", "lifecycle", "receivers", id, kind] as const,
  summary: (userId: number) => ["hr", "lifecycle", "summary", userId] as const,
  /** Klucz `usePreviewTasks` (budowany w hooku z ładunku zapytania). */
  preview: (payload: {
    kind: CaseKind;
    anchor: string;
    template_id: number | null;
    employment_type: string | null;
    department: string | null;
  }) => ["hr", "lifecycle", "preview", payload] as const,
};

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

export function olaFull(): PersonFull {
  return {
    ...personCard(ola),
    scope: "full",
    employment_type: "b2b",
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
