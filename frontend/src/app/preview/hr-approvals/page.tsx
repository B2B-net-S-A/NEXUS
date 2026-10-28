"use client";

/**
 * Harness „Ludzie → Akceptacje” (makieta 5 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwe `PeopleSectionNav` + `ApprovalsScreen` (jedna lista od 22.10.2026:
 * chipy rodzaju, nieobecności do decyzji i do wiadomości, raporty godzin
 * z podglądem miesiąca osoby, „Zdecydowane” z historią i filtrami) na zasianym
 * cache, ZERO zapytań (`hr-harness.tsx`). Moduł zgód jest tu wyłączony — zgody
 * w tej samej liście pokazuje `/preview/hr-consents`.
 *
 * Stany:
 * - domyślnie — Marta (przełożona 9 osób): urlop Kamila z zastępcą, rozmowami
 *   u klienta i nieobecnym w tym czasie Adamem, urlop Julii bez konfliktów
 *   (umowa o pracę — wnioski do decyzji); zgłoszona przerwa Oli (B2B) i
 *   nieobecność Tomasza (zlecenie, z kolizją od Marty) „do wiadomości” z
 *   „Zgłoś kolizję” (etap 2, D5); timesheety miesiąca, który ekran wybiera sam
 *   (do 10. dnia poprzedni): Julia bez raportu i szkice z „Przypomnij”, godziny
 *   „72 / 176 h” z paskiem (Kamil ma pełną normę — pasek zielony), 9 osób
 *   zwiniętych do 5 z „Pokaż wszystkie (9)”;
 * - `?kind=timesheet&year=…&month=…` — link z powiadomienia: chip „Raporty
 *   godzin” z poprzednim miesiącem (Ewa wysłała, Tomasz z nadgodzinami,
 *   Julia nie założyła, reszta zaakceptowana);
 * - urlop okolicznościowy Julii z załącznikiem: Marta widzi „Załącznik ✓” bez
 *   pliku (D6), Kadry — nazwę pliku z pobraniem (harness nie pobiera: zero zapytań);
 * - `?state=hr` — Kadry: zakres „wszyscy”, przy wniosku nazwisko przełożonego;
 * - `?state=covering` — Ola w zastępstwie za Kamila: decyduje o urlopie jego
 *   osoby, L4 widzi jako „Nieobecność” tylko do wiadomości (D6).
 * Filtry historii (status × osoba), oba miesiące timesheetów i podgląd każdej
 * osoby są zasiane — klik nie wysyła zapytania. „Anuluj” przy urlopie Kamila
 * (trwa) i L4 Ewy (minęło) otwiera okno cofnięcia z wymaganym powodem
 * (28.10.2026); przyszły termin — zwykłe potwierdzenie.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import { LEAVE_TYPE_LABELS } from "@/components/hr/leave/leave-format";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import {
  currentYearMonth,
  defaultQueueMonth,
} from "@/components/hr/time/time-format";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import {
  leaveKeys,
  type LeaveCovering,
  type LeaveRequestRow,
  type LeaveHistory,
  type LeaveStatus,
  type LeaveStatusCounts,
  type OnBehalfPerson,
  type PendingLeaveRow,
} from "@/lib/api/hr-leave";
import { timeKeys, type QueueStatus, type TeamQueue, type TeamQueueItem } from "@/lib/api/hr-time";
import { warsawToday } from "@/lib/warsaw-date";
import { shiftMonth, type YearMonth } from "@/lib/date-pl";

import {
  HR_CAST,
  HR_CLIENTS,
  harnessWorkDays,
  hrConfig,
  nthWorkDay,
  shiftDay,
  type HarnessPerson,
} from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import { personMonth, type HarnessTimesheetMode } from "../hr-my-time/fixtures";

const STATES = ["manager", "hr", "covering", "timesheets"] as const;
type State = (typeof STATES)[number];

const { ola, kamil, ewa, adam, marta, tomasz, julia, paulina } = HR_CAST;

/** Zespół Marty (9 osób) — fikcyjni. */
const TEAM: HarnessPerson[] = [ola, kamil, ewa, adam, tomasz, julia, HR_CAST.kacper, HR_CAST.natalia, HR_CAST.zofia];
/** Zespół Kamila — kolejka, którą Ola widzi w zastępstwie. */
const KAMIL_TEAM: HarnessPerson[] = [tomasz, julia, ewa];

const isoMonth = ({ year, month }: YearMonth) => `${year}-${String(month).padStart(2, "0")}`;

function leaveRow(
  id: string,
  person: HarnessPerson,
  start: string,
  end: string,
  days: string,
  extra: Partial<PendingLeaveRow> = {},
): PendingLeaveRow {
  return {
    id,
    user_id: person.id,
    user_name: person.name,
    leave_type: "vacation",
    leave_type_label: LEAVE_TYPE_LABELS.vacation,
    status: "pending",
    start_date: start,
    end_date: end,
    half_day: null,
    days_total: days,
    paid_days: days,
    unpaid_days: "0",
    note: null,
    substitute_user_id: null,
    substitute_name: null,
    forward_mail_consent: false,
    oof_internal_message: null,
    oof_external_message: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    source: "self",
    // Złożony kilka dni temu („czeka N dni” w skrzynce).
    created_at: `${shiftDay(warsawToday(), -2)}T09:00:00+02:00`,
    can_cancel: false,
    department: person.department,
    manager_name: marta.name,
    work_total: 0,
    work_by_kind: [],
    department_absent: [],
    type_visible: true,
    can_decide: true,
    ...extra,
  };
}

/** Zgłoszenia z B2B i zlecenia „do wiadomości” (D5) — bez akceptacji i odrzucenia. */
function reportedFor(today: string): PendingLeaveRow[] {
  const later = shiftDay(today, 60).slice(0, 7);
  return [
    leaveRow("lv-r-31", ola, nthWorkDay(later, 2), nthWorkDay(later, 6), "5", {
      status: "approved",
      is_report: true,
      employment_type: "b2b",
      leave_type_label: "Przerwa w świadczeniu usług",
      paid_days: "4",
      unpaid_days: "1",
      substitute_user_id: kamil.id,
      substitute_name: kamil.name,
      work_total: 1,
      work_by_kind: [{ kind: "client_interview", label: "Rozmowa u klienta", count: 1 }],
      can_report_conflict: true,
    }),
    leaveRow("lv-r-32", tomasz, nthWorkDay(later, 10), nthWorkDay(later, 12), "3", {
      status: "approved",
      is_report: true,
      employment_type: "zlecenie",
      leave_type_label: "Nieobecność",
      paid_days: "0",
      unpaid_days: "3",
      conflict: {
        at: `${today}T10:00:00+02:00`,
        by_name: marta.name,
        note: `Wdrożenie u klienta (${HR_CLIENTS.bank.name}) — czy da się przesunąć o tydzień?`,
      },
      can_report_conflict: true,
    }),
  ];
}

function pendingFor(
  state: State,
  today: string,
): { items: PendingLeaveRow[]; total: number; covering?: LeaveCovering[]; reported?: PendingLeaveRow[] } {
  const next = shiftDay(today, 40).slice(0, 7);
  if (state === "covering") {
    const until = shiftDay(today, 6);
    const items = [
      leaveRow("lv-p-21", tomasz, nthWorkDay(next, 3), nthWorkDay(next, 4), "2", {
        substitute_user_id: julia.id,
        substitute_name: julia.name,
        manager_name: kamil.name,
        as_substitute_for: kamil.name,
        as_substitute_until: until,
        work_total: 1,
        work_by_kind: [{ kind: "client_interview", label: "Rozmowa u klienta", count: 1 }],
      }),
      leaveRow("lv-p-22", ewa, today, shiftDay(today, 2), "3", {
        // L4 i pokrewne: zastępca przełożonego widzi „Nieobecność” i tylko przyjmuje do wiadomości.
        leave_type: null,
        leave_type_label: "Nieobecność",
        status: "approved",
        manager_name: kamil.name,
        as_substitute_for: kamil.name,
        as_substitute_until: until,
        type_visible: false,
        can_decide: false,
      }),
    ];
    return {
      items,
      total: items.length,
      covering: [{ manager_user_id: kamil.id, manager_name: kamil.name, until, reports: KAMIL_TEAM.length }],
      reported: [],
    };
  }
  const items = [
    leaveRow("lv-p-11", kamil, nthWorkDay(next, 15), nthWorkDay(next, 19), "5", {
      substitute_user_id: ola.id,
      substitute_name: ola.name,
      work_total: 3,
      work_by_kind: [
        { kind: "client_interview", label: "Rozmowa u klienta", count: 2 },
        { kind: "screening", label: "Screening", count: 1 },
      ],
      department_absent: [
        { user_id: adam.id, name: adam.name, start_date: nthWorkDay(next, 17), end_date: nthWorkDay(next, 19) },
      ],
      note: `Rozmowy u klienta (${HR_CLIENTS.bank.name}) przejmie Ola — umówione z klientem.`,
    }),
    leaveRow("lv-p-12", julia, nthWorkDay(next, 8), nthWorkDay(next, 9), "2", {
      leave_type: "occasional",
      leave_type_label: LEAVE_TYPE_LABELS.occasional,
      substitute_user_id: tomasz.id,
      substitute_name: tomasz.name,
      // Treść załącznika widzą Kadry; przełożona — tylko że jest (D6).
      proof_count: 1,
      proofs:
        state === "hr"
          ? [
              {
                id: 9101,
                file_name: "akt-slubu.pdf",
                mime: "application/pdf",
                size_bytes: 182_000,
                created_at: `${today}T08:30:00+02:00`,
                can_remove: false,
              },
            ]
          : null,
    }),
  ];
  return { items, total: items.length, covering: [], reported: reportedFor(today) };
}

function historyRows(today: string): LeaveRequestRow[] {
  const past = (n: number) => shiftDay(today, -n);
  const base = (id: string, person: HarnessPerson, start: string, end: string, days: string, status: LeaveStatus, extra: Partial<LeaveRequestRow> = {}): LeaveRequestRow => ({
    ...leaveRow(id, person, start, end, days),
    status,
    decided_by_name: status === "pending" ? null : marta.name,
    decided_at: status === "pending" ? null : `${start}T09:00:00+02:00`,
    ...extra,
  });
  return [
    base("lv-h-1", kamil, past(1), shiftDay(today, 5), "5", "approved", { substitute_name: ola.name }),
    base("lv-h-2", ewa, past(9), past(7), "3", "approved", {
      leave_type: "sick_leave",
      leave_type_label: LEAVE_TYPE_LABELS.sick_leave,
      decided_by_name: null,
    }),
    base("lv-h-3", tomasz, past(30), past(30), "1", "rejected", {
      decision_note: "Tego dnia dwie rozmowy u klienta — przełóż o tydzień.",
    }),
    base("lv-h-4", ola, past(45), past(44), "2", "cancelled"),
    // Zgłoszenie z B2B (D5): „Zgłoszone”, bez „Anuluj” u przełożonej — anuluje osoba albo Kadry.
    base("lv-h-5", ola, past(20), past(19), "2", "approved", {
      is_report: true,
      employment_type: "b2b",
      leave_type_label: "Przerwa w świadczeniu usług",
      decided_by_name: null,
    }),
  ];
}

function queueItem(person: HarnessPerson, period: YearMonth, status: QueueStatus, hours: number, overtime = 0, absence = 0): TeamQueueItem {
  return {
    user_id: person.id,
    name: person.name,
    job_title: person.jobTitle,
    timesheet:
      status === "missing"
        ? null
        : {
            id: person.id * 100 + period.month,
            status,
            submitted_at: status === "draft" ? null : `${isoMonth(shiftMonth(period, 1))}-02T09:00:00+02:00`,
            return_note: null,
            returned_at: null,
            approved_at: status === "approved" ? `${isoMonth(shiftMonth(period, 1))}-03T12:00:00+02:00` : null,
            approved_by_name: status === "approved" ? marta.name : null,
            payroll_locked: false,
            pdf_hash: status === "approved" ? "test-hash-0002" : null,
          },
    status,
    hours,
    overtime_hours: overtime,
    absence_days: absence,
    can_decide: true,
  };
}

/** Kolejka miesiąca: `closed` = miesiąc zakończony (wysłane i zaakceptowane), inaczej szkice. */
function queue(team: HarnessPerson[], period: YearMonth, closed: boolean): TeamQueue {
  const norm = harnessWorkDays(isoMonth(period)).length * 8;
  const items = team.map((person) => {
    if (!closed) {
      if (person.id === julia.id) return queueItem(person, period, "missing", 0);
      return queueItem(person, period, "draft", person.id === kamil.id ? norm : 72);
    }
    if (person.id === ewa.id) return queueItem(person, period, "submitted", norm - 8, 0, 1);
    if (person.id === tomasz.id) return queueItem(person, period, "submitted", norm + 2, 2);
    if (person.id === julia.id) return queueItem(person, period, "missing", 0);
    return queueItem(person, period, "approved", norm);
  });
  return { year: period.year, month: period.month, norm_hours: norm, items };
}

function modeOf(item: TeamQueueItem): HarnessTimesheetMode {
  return item.status === "missing" ? "missing" : item.status;
}

function prepare(params: URLSearchParams) {
  const state: State =
    params.get("kind") === "timesheet" ? "timesheets" : pickState(params.get("state"), STATES, "manager");
  const viewer = state === "hr" ? paulina : state === "covering" ? ola : marta;
  const config: HrConfig = hrConfig(
    state === "hr"
      ? { people_admin: true, has_profile: true }
      : state === "covering"
        ? {
            covering: [
              { manager_user_id: kamil.id, manager_name: kamil.name, until: shiftDay(warsawToday(), 6), reports: KAMIL_TEAM.length },
            ],
          }
        : { is_manager: true, direct_reports: TEAM.length },
  );
  const today = warsawToday();
  const team = state === "covering" ? KAMIL_TEAM : TEAM;
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: state === "covering" ? 1 : 4, cases: null });

  const pending = pendingFor(state, today);
  client.setQueryData(leaveKeys.pending, pending);

  const people: OnBehalfPerson[] = team.map((person) => ({
    user_id: person.id,
    name: person.name,
    employment_type: "b2b",
    department: person.department,
  }));
  client.setQueryData(leaveKeys.people, people);
  const history = historyRows(today).filter((row) => team.some((person) => person.id === row.user_id));
  const statuses: (LeaveStatus | null)[] = [null, "pending", "approved", "rejected", "cancelled"];
  for (const status of statuses) {
    for (const userId of [null, ...team.map((person) => person.id)]) {
      const scope = history.filter((row) => !userId || row.user_id === userId);
      const counts: LeaveStatusCounts = {
        all: scope.length,
        pending: scope.filter((row) => row.status === "pending").length,
        approved: scope.filter((row) => row.status === "approved").length,
        rejected: scope.filter((row) => row.status === "rejected").length,
        cancelled: scope.filter((row) => row.status === "cancelled").length,
      };
      client.setQueryData<LeaveHistory>(leaveKeys.history({ status, user_id: userId }), {
        items: scope.filter((row) => !status || row.status === status),
        counts,
      });
    }
  }

  // Timesheety: miesiąc kolejki, poprzedni i bieżący — z podglądem każdej osoby.
  const current = currentYearMonth();
  const months = new Map<string, YearMonth>();
  for (const period of [defaultQueueMonth(), shiftMonth(current, -1), current, shiftMonth(current, -2)]) {
    months.set(isoMonth(period), period);
  }
  for (const period of months.values()) {
    const closed = isoMonth(period) < isoMonth(current);
    const data = queue(team, period, closed);
    client.setQueryData(timeKeys.team(period.year, period.month), data);
    for (const item of data.items) {
      const person = team.find((row) => row.id === item.user_id)!;
      client.setQueryData(
        timeKeys.member(item.user_id, period.year, period.month),
        personMonth(person, period, today, modeOf(item)),
      );
    }
  }

  const previous = shiftMonth(current, -1);
  return {
    user: viewer,
    client,
    value: { state, config, timesheetHref: `?kind=timesheet&year=${previous.year}&month=${previous.month}` },
  };
}

export default function HrApprovalsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config, timesheetHref } = ready.value;
  const links = [
    { key: "manager", label: "Przełożona", href: "?" },
    { key: "timesheets", label: "Timesheety poprzedniego miesiąca", href: timesheetHref },
    { key: "hr", label: "Kadry" },
    { key: "covering", label: "W zastępstwie przełożonego" },
  ];
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Akceptacje"
      note="Dane fikcyjne, bez zapytań. Decyzje w podglądzie nie zapisują się (odpowiedź to błąd sieci)."
      states={links}
      current={state}
    >
      <div className="space-y-4">
        <PageHeader
          title="Akceptacje"
          description="Nieobecności, raporty godzin i zgody do decyzji — w jednej liście."
          density="compact"
        />
        <PeopleSectionNav config={config} active="approvals" />
        <ApprovalsScreen config={config} />
      </div>
    </HrHarnessShell>
  );
}
