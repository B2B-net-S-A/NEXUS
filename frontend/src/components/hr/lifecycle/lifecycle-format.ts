// Wejście i odejście — czyste funkcje do ekranów (bez zapytań, testowalne).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AccountCloseResult,
  CaseKind,
  CaseProgress,
  CaseStatus,
} from "@/lib/api/hr-lifecycle";
import { countPl } from "@/lib/plural-pl";

/** „1 dzień roboczy”, „2 dni robocze”, „5 dni roboczych” (liczba bez znaku). */
export function workingDays(count: number): string {
  return countPl(Math.abs(count), "dzień roboczy", "dni robocze", "dni roboczych");
}

/** Termin pozycji szablonu: „2 dni robocze przed startem”, „w ostatnim dniu”. */
export function formatOffset(kind: CaseKind, days: number): string {
  if (days === 0) return kind === "onboarding" ? "w dniu startu" : "w ostatnim dniu";
  const anchor = kind === "onboarding" ? "startem" : "ostatnim dniem";
  return days < 0
    ? `${workingDays(days)} przed ${anchor}`
    : `${workingDays(days)} po ${kind === "onboarding" ? "starcie" : "ostatnim dniu"}`;
}

const MOMENT = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „30.11, 18:00” — chwila w czasie firmy (Warszawa). */
export function formatMoment(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return MOMENT.format(date);
}

/** Kolor statusu sprawy wejścia i odejścia — ten sam w kartotece, sprawie i odejściu. */
export const CASE_STATUS_TONE: Record<CaseStatus, StatusDotTone> = {
  draft: "neutral",
  active: "info",
  done: "success",
  cancelled: "neutral",
};

export function isLiveStatus(status: CaseStatus): boolean {
  return status === "draft" || status === "active";
}

/** „2 z 6 zadań · 1 po terminie”. */
export function progressLabel(progress: CaseProgress): string {
  if (progress.total === 0) return "bez zadań";
  const base = `${progress.done} z ${progress.total} ${
    progress.total === 1 ? "zadania" : "zadań"
  }`;
  return progress.overdue > 0 ? `${base} · ${progress.overdue} po terminie` : base;
}

export const ACCOUNT_RESULT_LABELS: Record<AccountCloseResult, string> = {
  deactivated: "Konto wyłączone",
  already_inactive: "Konto było już wyłączone",
  skipped_admin: "Konto administratora zostaje — wyłącza je admin ręcznie",
};

/** Czy Kadry mogą już wyłączyć konto ręcznie (dzień wyłączenia minął). */
export function canDeactivateNow(
  deactivateOn: string | null,
  accountClosedAt: string | null,
  status: CaseStatus,
  today: string,
): boolean {
  if (status !== "active" || accountClosedAt || !deactivateOn) return false;
  return today >= deactivateOn.slice(0, 10);
}

/** „1 osoba”, „3 osoby”, „5 osób”. */
export function peopleCount(count: number): string {
  return countPl(Math.abs(count), "osoba", "osoby", "osób");
}

interface ReportsRowLike {
  kind: string;
  count: number | null;
  planned_count: number | null;
  receiver_name: string | null;
  status: string | null;
  result: Record<string, number> | null;
}

/**
 * Zdanie o podwładnych odchodzącej osoby (wiersz „Podwładni” przekazania, D5).
 * `null` — nie ma podwładnych albo liczby (lista spraw liczy je tylko w szczegółach).
 */
export function reportsSummary(rows: readonly ReportsRowLike[]): string | null {
  const row = rows.find((item) => item.kind === "reports");
  if (!row) return null;
  if (row.status === "done") {
    const moved = row.result?.people ?? row.planned_count ?? 0;
    if (!moved) return null;
    return `Zespół przekazany (${peopleCount(moved)}) — koordynatorem jest ${
      row.receiver_name ?? "wskazana osoba"
    }.`;
  }
  if (!row.count) return null;
  if (!row.receiver_name) {
    return `Osoby w zespole: ${peopleCount(row.count)}. Wskaż, kto zostanie ich koordynatorem — bez tego przekazanie nie przejdzie, a konto nie wyłączy się samo.`;
  }
  return `Osoby w zespole: ${peopleCount(row.count)}. Po przekazaniu ich koordynatorem będzie ${row.receiver_name} — od tej chwili wnioski i timesheety idą do tej osoby.`;
}

const CONDITION_FORM_LABELS: Record<string, string> = {
  uop: "UoP",
  b2b: "B2B",
  zlecenie: "zlecenie",
};

interface ConditionsLike {
  employment_types?: readonly string[];
  equipment?: "ours" | "client" | null;
  student?: boolean | null;
}

/** Kolumna „Warunek” ścieżki: „B2B · sprzęt od nas · student”; pusto = zawsze. */
export function conditionSummary(conditions: ConditionsLike | null | undefined): string {
  if (!conditions) return "";
  const parts: string[] = [];
  const forms = conditions.employment_types ?? [];
  if (forms.length) parts.push(forms.map((form) => CONDITION_FORM_LABELS[form] ?? form).join(", "));
  if (conditions.equipment === "ours") parts.push("sprzęt od nas");
  if (conditions.equipment === "client") parts.push("sprzęt od klienta");
  if (conditions.student) parts.push("student");
  return parts.join(" · ");
}

/** Baner „Dociągnij”: „3 trwające wejścia są na starszej wersji”. */
export function behindLabel(count: number, kind: CaseKind): string {
  const noun =
    kind === "onboarding"
      ? countPl(count, "trwające wejście jest", "trwające wejścia są", "trwających wejść jest")
      : countPl(count, "trwające odejście jest", "trwające odejścia są", "trwających odejść jest");
  return `${noun} na starszej wersji tej ścieżki.`;
}

// ── Makiety 19.10.2026: oś odejścia, zadania po właścicielu, „Co powstanie” ──

export type MilestoneState = "done" | "current" | "upcoming";

export interface Milestone {
  key: "reported" | "exit_talk" | "handover" | "account" | "equipment";
  label: string;
  /** Data albo chwila (RRRR-MM-DD lub ISO) — co się stało albo kiedy ma się stać. */
  on: string | null;
  /** Kto (rozmowę wyjściową prowadził) — imię z zadania. */
  who: string | null;
  state: MilestoneState;
}

interface MilestoneTask {
  category: string;
  status: string;
  due_date: string | null;
  done_at: string | null;
  done_by_name: string | null;
  assignee_name: string | null;
}

interface MilestoneCase {
  status: string;
  started_at: string | null;
  last_working_day: string | null;
  handover_at: string | null;
  handover_executed_at: string | null;
  deactivate_on: string | null;
  account_closed_at: string | null;
  tasks: readonly MilestoneTask[];
}

function latest(dates: (string | null)[]): string | null {
  const known = dates.filter((d): d is string => Boolean(d)).sort();
  return known.length ? known[known.length - 1] : null;
}

/**
 * Oś odejścia: zgłoszone → rozmowa wyjściowa → przekazanie pracy → konto
 * wyłączone → sprzęt zwrócony. Rozmowa to zadanie „Rozmowa” (kategoria
 * `meeting`), sprzęt — zadania „Sprzęt”; bez takich zadań kroku nie ma.
 * Pierwszy niezrobiony krok jest bieżący.
 */
export function offboardingMilestones(data: MilestoneCase): Milestone[] {
  const isClosed = (t: MilestoneTask) => t.status !== "open";
  const talk = data.tasks.filter((t) => t.category === "meeting");
  const equipment = data.tasks.filter((t) => t.category === "equipment");
  const steps: (Omit<Milestone, "state"> & { done: boolean })[] = [
    {
      key: "reported",
      label: data.status === "draft" ? "Szkic" : "Zgłoszone",
      on: data.started_at,
      who: null,
      done: data.status !== "draft",
    },
  ];
  if (talk.length) {
    const done = talk.every(isClosed);
    steps.push({
      key: "exit_talk",
      label: "Rozmowa wyjściowa",
      on: done ? latest(talk.map((t) => t.done_at)) : latest(talk.map((t) => t.due_date)),
      who: (done ? talk[0].done_by_name : talk[0].assignee_name) ?? null,
      done,
    });
  }
  steps.push({
    key: "handover",
    label: "Przekazanie pracy",
    on: data.handover_executed_at ?? data.handover_at,
    who: null,
    done: Boolean(data.handover_executed_at),
  });
  steps.push({
    key: "account",
    label: "Konto wyłączone",
    on: data.account_closed_at ?? data.deactivate_on,
    who: null,
    done: Boolean(data.account_closed_at),
  });
  if (equipment.length) {
    const done = equipment.every(isClosed);
    steps.push({
      key: "equipment",
      label: "Sprzęt zwrócony",
      on: done
        ? latest(equipment.map((t) => t.done_at))
        : latest(equipment.map((t) => t.due_date)),
      who: null,
      done,
    });
  }
  const current = data.status === "cancelled" ? -1 : steps.findIndex((s) => !s.done);
  return steps.map(({ done, ...step }, index) => ({
    ...step,
    state: done ? "done" : index === current ? "current" : "upcoming",
  }));
}

export interface OwnerGroup<T> {
  key: string;
  label: string;
  /** Imię i nazwisko wykonawcy (awatar), gdy zadanie ma konkretną osobę. */
  person: string | null;
  tasks: T[];
}

interface OwnedTask {
  assignee_kind: string;
  assignee_name: string | null;
  status: string;
  due_date: string | null;
}

/**
 * Otwarte zadania pogrupowane wg wykonawcy (rola · osoba), grupy od
 * najwcześniejszego terminu; zrobione i pominięte na końcu jako „Zrobione”.
 */
export function groupTasksByOwner<T extends OwnedTask>(
  tasks: readonly T[],
  labels: Record<string, string>,
): OwnerGroup<T>[] {
  const groups = new Map<string, OwnerGroup<T>>();
  const done: T[] = [];
  for (const task of tasks) {
    if (task.status !== "open") {
      done.push(task);
      continue;
    }
    const key = `${task.assignee_kind}:${task.assignee_name ?? ""}`;
    const role = labels[task.assignee_kind] ?? task.assignee_kind;
    const first = task.assignee_name?.trim().split(/\s+/)[0];
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label: first ? `${role} · ${first}` : role,
        person: task.assignee_name,
        tasks: [],
      });
    }
    groups.get(key)?.tasks.push(task);
  }
  const firstDue = (group: OwnerGroup<T>) =>
    group.tasks.map((t) => t.due_date ?? "9999-12-31").sort()[0];
  const ordered = [...groups.values()].sort((a, b) =>
    firstDue(a) === firstDue(b) ? a.label.localeCompare(b.label, "pl") : firstDue(a) < firstDue(b) ? -1 : 1,
  );
  return done.length
    ? [...ordered, { key: "done", label: "Zrobione", person: null, tasks: done }]
    : ordered;
}

/** Kolejność wykonawców w „Co powstanie” — jak na makiecie wejścia. */
const OWNER_ORDER = [
  "manager",
  "people_admin",
  "reception",
  "it",
  "administration",
  "person",
  "care_owner",
  "delivery_lead",
];

/** „Co powstanie”: zadania z podglądu ścieżki pogrupowane wg wykonawcy. */
export function previewByOwner<T extends { assignee_kind: string }>(
  tasks: readonly T[],
): { kind: string; tasks: T[] }[] {
  const byKind = new Map<string, T[]>();
  for (const task of tasks) {
    byKind.set(task.assignee_kind, [...(byKind.get(task.assignee_kind) ?? []), task]);
  }
  const rank = (kind: string) => {
    const index = OWNER_ORDER.indexOf(kind);
    return index === -1 ? OWNER_ORDER.length : index;
  };
  return [...byKind.entries()]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([kind, items]) => ({ kind, tasks: items }));
}

export interface AccountMatch {
  user_id: number;
  name: string;
  email: string;
  /** Konto bez kartoteki można wybrać; z kartoteką — tylko informacja. */
  has_profile: boolean;
}

function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toLowerCase();
}

/**
 * Wyszukiwanie konta w kreatorze wejścia: najpierw konta bez kartoteki (to
 * zwykle osoby, które właśnie wchodzą), potem z kartoteką — wyszarzone.
 * Szukanie po imieniu, nazwisku albo e-mailu, bez wielkości liter i ogonków.
 */
export function matchAccounts(
  withoutProfile: readonly { user_id: number; name: string; email: string }[],
  people: readonly { user_id: number; name: string; email: string }[],
  query: string,
  limit = 8,
): AccountMatch[] {
  const term = fold(query.trim());
  const hit = (row: { name: string; email: string }) =>
    !term || fold(row.name).includes(term) || fold(row.email).includes(term);
  const free = withoutProfile.filter(hit).map((row) => ({ ...row, has_profile: false }));
  const taken = term
    ? people
        .filter((row) => !withoutProfile.some((a) => a.user_id === row.user_id) && hit(row))
        .map((row) => ({ user_id: row.user_id, name: row.name, email: row.email, has_profile: true }))
    : [];
  return [...free, ...taken].slice(0, limit);
}

/** Rodzaje pracy, które przechodzą razem z rekrutacjami (karty, rozmowy, kontakty). */
const WITH_RECRUITMENTS = new Set(["pipeline_cards", "client_meetings", "followups"]);

export function goesWithRecruitments(kind: string): boolean {
  return WITH_RECRUITMENTS.has(kind);
}

interface WorkRowLike {
  kind: string;
  transferable: boolean;
  count: number | null;
  status: string | null;
}

/**
 * „Komu przekazać” (makieta 19.10.2026): wiersze z pracą, praca, która idzie
 * z rekrutacjami (podpis pod wierszem rekrutacji), i rodzaje z zerem —
 * zwinięte do jednej linijki. Wiersz z wynikiem przekazania (zrobione albo
 * błąd) zostaje zawsze, nawet z zerem.
 */
export function workLayout<T extends WorkRowLike>(
  rows: readonly T[],
): { rows: T[]; withRecruitments: T[]; empty: T[] } {
  const hasOutcome = (row: T) => row.status === "done" || row.status === "failed";
  const recruitments = rows.some((row) => row.kind === "recruitments" && (row.count ?? 1) > 0);
  const withRecruitments = recruitments
    ? rows.filter((row) => WITH_RECRUITMENTS.has(row.kind) && (row.count ?? 0) > 0)
    : [];
  const empty = rows.filter((row) => row.count === 0 && !hasOutcome(row));
  const shown = rows.filter(
    (row) => !empty.includes(row) && !withRecruitments.includes(row),
  );
  return { rows: shown, withRecruitments, empty };
}

/** „dziś”, „jutro”, „za 42 dni”, „3 dni temu” — odległość od dziś w dniach kalendarza. */
export function daysFromToday(day: string | null, today: string): string | null {
  if (!day) return null;
  const toDays = (iso: string) => {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return Date.UTC(y, m - 1, d) / 86_400_000;
  };
  const diff = Math.round(toDays(day) - toDays(today));
  if (diff === 0) return "dziś";
  if (diff === 1) return "jutro";
  if (diff === -1) return "wczoraj";
  return diff > 0
    ? `za ${countPl(diff, "dzień", "dni", "dni")}`
    : `${countPl(-diff, "dzień", "dni", "dni")} temu`;
}
