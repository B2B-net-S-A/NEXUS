/**
 * Akademia — czysta logika ekranów naboru (bez Reacta i sieci).
 *
 * Etapy i ich kolejność są lustrem `backend/app/services/academy_flow.py`.
 * Werdykt Luny to wyłącznie sortowanie: „Luna odłożyła” czeka na decyzję
 * człowieka, a decyzja „nie” jest pamiętana na zawsze (decyzja Artura
 * 24.09.2026) — dlatego wykluczeni mają osobny widok z „Przywróć”.
 */

import type {
  AcademyApplication,
  AcademyCounts,
  AcademySessionRow,
  AcademyStatus,
} from "@/lib/api/academy";

export const STATUS_LABELS: Record<AcademyStatus, string> = {
  new: "Z ogłoszeń",
  to_call: "Do telefonu",
  scheduled: "Umówieni w biurze",
  task_given: "Zadanie wydane",
  task_passed: "Zaliczyli zadanie",
  contract_sent: "Umowa wysłana",
  signed: "W akademii",
  rejected: "Wykluczeni",
  withdrew: "Zrezygnowali",
};

/** Kolumny widoku edycji (C). `new` ma osobny baner „Luna odłożyła”. */
export const EDITION_COLUMNS: readonly AcademyStatus[] = [
  "to_call",
  "scheduled",
  "task_given",
  "task_passed",
  "contract_sent",
  "signed",
];

export const REJECT_REASONS: readonly string[] = [
  "Nie pasują warunki z ogłoszenia",
  "Nie przyszedł na spotkanie",
  "Nie odbiera telefonu",
  "Doświadczenie ponad limit",
  "Słaba rozmowa w biurze",
];

export type Verdict = "call" | "review" | "skip";

export const VERDICT_LABELS: Record<Verdict, string> = {
  call: "Dzwonimy",
  review: "Do decyzji",
  skip: "Luna odkłada",
};

const MONTHS = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
];

const WEEKDAYS_SHORT = ["nd", "pon", "wt", "śr", "czw", "pt", "sob"];

/** Edycja startuje 1. dnia miesiąca — podpis dziś = start od następnego. */
export function nextCohort(today: Date): Date {
  return new Date(today.getFullYear(), today.getMonth() + 1, 1);
}

/** „2026-11-01” → „listopad 2026”. */
export function cohortLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [year, month] = iso.split("-").map(Number);
  if (!year || !month) return "—";
  return `${MONTHS[month - 1]} ${year}`;
}

export function toIsoDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** „pon 27.10 · 10:00” w czasie lokalnym przeglądarki. */
export function sessionLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${WEEKDAYS_SHORT[d.getDay()]} ${pad(d.getDate())}.${pad(d.getMonth() + 1)} · ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return "—";
  return `${d}.${m}`;
}

export function freeSeats(session: AcademySessionRow): number {
  return Math.max(0, session.capacity - session.taken);
}

/** Terminy, na które da się jeszcze kogoś zapisać (przyszłe, nieodwołane). */
export function bookableSessions(
  sessions: readonly AcademySessionRow[],
  now: Date,
): AcademySessionRow[] {
  return sessions
    .filter((s) => !s.cancelled && new Date(s.starts_at).getTime() > now.getTime())
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
}

/**
 * Kolejka telefonów (B): najpierw „Dzwonimy”, potem „Do decyzji”; w grupie
 * najmniej prób, potem najstarsze zgłoszenie. Osoba, która nie odebrała,
 * spada na koniec swojej grupy.
 */
export function callQueue(apps: readonly AcademyApplication[]): AcademyApplication[] {
  const rank = (a: AcademyApplication) => (a.screening_verdict === "review" ? 1 : 0);
  return apps
    .filter((a) => a.status === "to_call")
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        a.call_attempts - b.call_attempts ||
        a.applied_at.localeCompare(b.applied_at) ||
        a.id - b.id,
    );
}

/** Odłożeni przez Lunę — czekają na „Zatwierdź” albo „Dzwonimy mimo to”. */
export function lunaSkipped(apps: readonly AcademyApplication[]): AcademyApplication[] {
  return apps.filter((a) => a.status === "new" && a.screening_verdict === "skip");
}

export function awaitingLuna(apps: readonly AcademyApplication[]): number {
  return apps.filter((a) => a.status === "new" && a.screening_verdict === null).length;
}

export function byStatus(
  apps: readonly AcademyApplication[],
): Record<AcademyStatus, AcademyApplication[]> {
  const out = {
    new: [],
    to_call: [],
    scheduled: [],
    task_given: [],
    task_passed: [],
    contract_sent: [],
    signed: [],
    rejected: [],
    withdrew: [],
  } as Record<AcademyStatus, AcademyApplication[]>;
  for (const app of apps) out[app.status]?.push(app);
  return out;
}

/** Zadanie po terminie — rekruter powinien przypomnieć albo zamknąć. */
export function taskOverdue(app: AcademyApplication, today: Date): boolean {
  return app.status === "task_given" && !!app.task_due && app.task_due < toIsoDate(today);
}

export function attendeesOf(
  apps: readonly AcademyApplication[],
  sessionId: number,
): AcademyApplication[] {
  return apps
    .filter((a) => a.session_id === sessionId)
    .sort((a, b) => a.full_name.localeCompare(b.full_name, "pl"));
}

/**
 * Liczby do kafli widoku edycji. Z `counts` (policzone przez serwer) biorą się
 * liczby, które lista może zaniżać — lista ma limit i ucina najstarszych
 * zamkniętych (wykluczonych, zrezygnowanych), nigdy osób w toku.
 */
export function editionStats(
  apps: readonly AcademyApplication[],
  counts?: AcademyCounts | null,
) {
  const groups = byStatus(apps);
  const fromServer = (key: string, fallback: number) => {
    const value = counts?.[key];
    return typeof value === "number" ? value : fallback;
  };
  const serverTotal = counts
    ? (Object.keys(STATUS_LABELS) as AcademyStatus[]).reduce(
        (sum, status) => sum + (counts[status] ?? 0),
        0,
      )
    : null;
  return {
    fromAds: serverTotal ?? apps.length,
    toCall: groups.to_call.length,
    review: groups.to_call.filter((a) => a.screening_verdict === "review").length,
    scheduled: groups.scheduled.length,
    tasks: groups.task_given.length,
    passed: groups.task_passed.length + groups.contract_sent.length,
    signed: groups.signed.length,
    excluded: fromServer("rejected", groups.rejected.length),
    reapplied: fromServer(
      "reapplied_excluded",
      groups.rejected.filter((a) => a.reapplied_at).length,
    ),
  };
}

/**
 * Zdanie pod nagłówkiem, gdy lista zgłoszeń została przycięta. `null` = lista
 * jest kompletna.
 */
export function truncatedListNote(shown: number, total: number | null | undefined): string | null {
  if (typeof total !== "number" || total <= shown) return null;
  return `Pokazano ${shown} z ${total} zgłoszeń. Osoby w toku są wszystkie; pominięto najstarszych wykluczonych i zrezygnowanych — znajdziesz ich wyszukiwarką.`;
}

/**
 * Komunikat po zbiorczej akcji. Przy wykluczaniu mówi wprost, ilu osób NIE
 * wykluczono i dlaczego (serwer odmawia osobom, które ktoś w międzyczasie
 * przesunął). `null` = nic nie padło.
 */
export function bulkFailureMessage(
  action: string,
  failed: readonly { id: number; message: string }[],
): string | null {
  if (failed.length === 0) return null;
  const byMessage = new Map<string, number>();
  for (const item of failed) byMessage.set(item.message, (byMessage.get(item.message) ?? 0) + 1);
  const reasons = [...byMessage.entries()]
    .map(([message, n]) => (byMessage.size > 1 ? `${message} (${n} os.)` : message))
    .join(" ");
  const head =
    action === "reject"
      ? `Nie wykluczono ${failed.length} os.`
      : `Nie udało się dla ${failed.length} os.`;
  return `${head}: ${reasons}`;
}

/**
 * Wiersz zwrócony po akcji na osobie wstawiony do listy razem z licznikami
 * statusów. Bez przeliczenia `counts` zakładka „Wykluczeni” i kafle edycji
 * pokazywały stan sprzed akcji do najbliższego odpytania (≤ 2 min). Liczniki
 * pochodne (`luna_skipped`, `reapplied_excluded`…) dociąga odświeżenie listy.
 */
export function withReplacedApplication<
  T extends { items: AcademyApplication[]; counts: AcademyCounts },
>(data: T | undefined, row: AcademyApplication): T | undefined {
  if (!data) return data;
  const previous = data.items.find((a) => a.id === row.id);
  const counts: AcademyCounts = { ...data.counts };
  if (previous && previous.status !== row.status) {
    const before = counts[previous.status];
    if (typeof before === "number") counts[previous.status] = Math.max(0, before - 1);
    counts[row.status] = (counts[row.status] ?? 0) + 1;
  }
  return {
    ...data,
    items: data.items.map((a) => (a.id === row.id ? row : a)),
    counts,
  };
}

/** Dni tygodnia w kolejności pon–nd dla formularza rytmu (0 = poniedziałek). */
export const RHYTHM_DAYS: readonly { value: number; label: string }[] = [
  { value: 0, label: "pon" },
  { value: 1, label: "wt" },
  { value: 2, label: "śr" },
  { value: 3, label: "czw" },
  { value: 4, label: "pt" },
];
