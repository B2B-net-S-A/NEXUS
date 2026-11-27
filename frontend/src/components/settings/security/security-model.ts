// Logika ekranu „Ustawienia → Bezpieczeństwo” bez Reacta (27.11.2026, makiety
// raportu „Tarcza NEXUSA”): typy odpowiedzi `/api/security/*`, etykiety wag
// i źródeł, kafelki, brief sesji naprawy, walidacja wyjątku i siatka
// kalendarza rutyn. Funkcje zależne od dnia biorą `today` z parametru.

export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type FindingStatus = "open" | "excepted" | "fixed";
export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export interface SecurityFinding {
  id: number;
  source: string;
  scanner: string | null;
  severity: Severity;
  title: string;
  location: string | null;
  evidence: string | null;
  impact: string | null;
  steps: string[];
  status: FindingStatus;
  stored_status: FindingStatus;
  exception_expired: boolean;
  owner_user_id: number | null;
  exception_reason: string | null;
  exception_until: string | null;
  closed_note: string | null;
  closed_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SecurityEvent {
  id: number;
  source: string;
  kind: string;
  severity: Severity;
  summary: string;
  count: number;
  link: string | null;
  occurred_at: string;
}

export type SourceState =
  | "ok"
  | "live"
  | "quiet"
  | "failing"
  | "unconfigured"
  | "due"
  | "overdue";

export interface SecuritySource {
  key: string;
  name: string;
  where: string;
  state: SourceState;
  state_label: string;
  last_at: string | null;
  last_on: string | null;
  detail: string | null;
  link: string | null;
}

export interface SecurityTiles {
  ci: {
    new: number;
    conclusion: string | null;
    run_started_at: string | null;
    run_url: string | null;
    configured: boolean;
  };
  waiting: { total: number; by_severity: Partial<Record<Severity, number>> };
  traffic: { blocked: number; events: number; configured: boolean };
  logins: { ok: number; denied: number };
}

export interface SecurityOwner {
  id: number;
  name: string;
}

export interface SecurityOverview {
  today: string;
  workflow_url: string;
  tiles: SecurityTiles;
  waiting: SecurityFinding[];
  excepted: SecurityFinding[];
  recently_closed: SecurityFinding[];
  events: SecurityEvent[];
  sources: SecuritySource[];
  routines_overdue: number;
  owners: SecurityOwner[];
}

export type Cadence = "week" | "month" | "quarter";

export interface SecurityRoutine {
  id: number;
  key: string;
  title: string;
  cadence: Cadence;
  owner_label: string;
  automatic: boolean;
  last_done_on: string | null;
  next_due_on: string;
  last_note: string | null;
  state: "ok" | "soon" | "overdue";
}

export const SECURITY_OVERVIEW_KEY = ["security", "overview"] as const;
export const SECURITY_ROUTINES_KEY = ["security", "routines"] as const;

// ── Etykiety ─────────────────────────────────────────────────────────────────

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "krytyczna",
  high: "wysoka",
  medium: "średnia",
  low: "niska",
  info: "informacja",
};

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: "danger",
  high: "danger",
  medium: "warning",
  low: "info",
  info: "neutral",
};

export const SOURCE_LABEL: Record<string, string> = {
  ci: "CI",
  defectdojo: "DefectDojo",
  wazuh: "Wazuh",
  crowdsec: "CrowdSec",
  falco: "Falco",
  pentest: "Pentest",
  nexus: "NEXUS",
  manual: "Ręcznie",
  grafana: "Grafana",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

export const SOURCE_STATE_TONE: Record<SourceState, Tone> = {
  ok: "success",
  live: "success",
  quiet: "warning",
  failing: "danger",
  unconfigured: "neutral",
  due: "warning",
  overdue: "danger",
};

export const CADENCE_LABEL: Record<Cadence, string> = {
  week: "tydzień",
  month: "miesiąc",
  quarter: "kwartał",
};

/** Ton zdarzenia na liście „na żywo”: CI zielony, reszta po wadze. */
export function eventTone(event: SecurityEvent): Tone {
  if (event.kind === "ci_run") return event.severity === "info" ? "success" : "danger";
  if (event.severity === "info") return event.source === "nexus" ? "neutral" : "info";
  return SEVERITY_TONE[event.severity];
}

// ── Kafelki ─────────────────────────────────────────────────────────────────

export interface TileView {
  key: "ci" | "waiting" | "traffic" | "logins";
  label: string;
  value: string;
  sub: string;
  tone: Tone;
}

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const tens = n % 100;
  const units = n % 10;
  if (units >= 2 && units <= 4 && (tens < 12 || tens > 14)) return few;
  return many;
}

function severitySummary(bySeverity: Partial<Record<Severity, number>>): string {
  const order: Severity[] = ["critical", "high", "medium", "low", "info"];
  const parts = order
    .filter((s) => (bySeverity[s] ?? 0) > 0)
    .map((s) => `${SEVERITY_LABEL[s]} ${bySeverity[s]}`);
  return parts.length ? parts.join(" · ") : "nic nie czeka";
}

export function buildTiles(
  tiles: SecurityTiles,
  formatMoment: (iso: string) => string,
): TileView[] {
  const ci = tiles.ci;
  const ciRed = ci.conclusion !== null && ci.conclusion !== "success";
  const ciTile: TileView = !ci.configured
    ? {
        key: "ci",
        label: "Skany kodu (CI)",
        value: "—",
        sub: "czeka na pierwszy odczyt z GitHub Actions",
        tone: "neutral",
      }
    : {
        key: "ci",
        label: "Skany kodu (CI)",
        value: ciRed ? "czerwony" : `${ci.new} ${plural(ci.new, "nowe", "nowe", "nowych")}`,
        sub: `Semgrep i zależności${ci.run_started_at ? `, ${formatMoment(ci.run_started_at)}` : ""}`,
        tone: ciRed ? "danger" : ci.new > 0 ? "warning" : "success",
      };
  const waiting = tiles.waiting;
  const urgent = (waiting.by_severity.critical ?? 0) + (waiting.by_severity.high ?? 0);
  const traffic = tiles.traffic;
  return [
    ciTile,
    {
      key: "waiting",
      label: "Czeka na reakcję",
      value: String(waiting.total),
      sub: severitySummary(waiting.by_severity),
      tone: urgent > 0 ? "danger" : waiting.total > 0 ? "warning" : "success",
    },
    traffic.configured
      ? {
          key: "traffic",
          label: "Ruch z internetu, 24 h",
          value: `${traffic.blocked} ${plural(traffic.blocked, "blokada", "blokady", "blokad")}`,
          sub: `CrowdSec: ${traffic.events} ${plural(traffic.events, "zdarzenie", "zdarzenia", "zdarzeń")}`,
          tone: traffic.blocked > 0 ? "warning" : "success",
        }
      : {
          key: "traffic",
          label: "Ruch z internetu, 24 h",
          value: "—",
          sub: "CrowdSec jeszcze nie przysłał zdarzeń",
          tone: "neutral",
        },
    {
      key: "logins",
      label: "Logowania, 24 h",
      value: `${tiles.logins.ok} / ${tiles.logins.denied}`,
      sub: "udane / odrzucone",
      tone: tiles.logins.denied > 0 ? "warning" : "success",
    },
  ];
}

// ── Brief sesji naprawy ─────────────────────────────────────────────────────

/** Tekst do wklejenia w nową sesję Claude Code: kompletny bez tej strony. */
export function repairBrief(finding: SecurityFinding): string {
  const lines = [
    `Napraw znalezisko bezpieczeństwa w NEXUSIE (Ustawienia → Bezpieczeństwo, id ${finding.id}).`,
    "",
    `Tytuł: ${finding.title}`,
    `Waga: ${SEVERITY_LABEL[finding.severity]} · źródło: ${sourceLabel(finding.source)}${finding.scanner ? ` (${finding.scanner})` : ""}`,
  ];
  if (finding.location) lines.push(`Gdzie: ${finding.location}`);
  if (finding.evidence) lines.push(`Dowód: ${finding.evidence}`);
  if (finding.impact) lines.push(`Wpływ: ${finding.impact}`);
  if (finding.steps.length) {
    lines.push("", "Kroki:");
    finding.steps.forEach((step, i) => lines.push(`${i + 1}. ${step}`));
  }
  lines.push(
    "",
    "Meta: poprawka z testem, który bez niej pada; PR w kolejce merge'ów; po wdrożeniu",
    "sprawdź, że skaner nie zgłasza znaleziska, i zamknij je na ekranie jako naprawione.",
  );
  return lines.join("\n");
}

// ── Wyjątek ─────────────────────────────────────────────────────────────────

export const EXCEPTION_MIN_REASON = 10;
export const EXCEPTION_MAX_DAYS = 365;

function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

export function exceptionBounds(today: string): { min: string; max: string } {
  return { min: addDaysIso(today, 1), max: addDaysIso(today, EXCEPTION_MAX_DAYS) };
}

/** Komunikat błędu albo `null`, gdy wyjątek można zapisać. */
export function exceptionError(reason: string, until: string, today: string): string | null {
  if (reason.trim().length < EXCEPTION_MIN_REASON) {
    return `Wpisz powód wyjątku (co najmniej ${EXCEPTION_MIN_REASON} znaków).`;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(until)) return "Wybierz datę, do kiedy trwa wyjątek.";
  const { min, max } = exceptionBounds(today);
  if (until < min) return "Termin wyjątku musi być po dzisiejszym dniu.";
  if (until > max) return "Wyjątek może trwać najwyżej rok.";
  return null;
}

// ── Kalendarz rutyn ─────────────────────────────────────────────────────────

/** Krótkie nazwy rutyn do kratki kalendarza (pełna nazwa w podpowiedzi). */
export const ROUTINE_SHORT: Record<string, string> = {
  ci_weekly: "Skan CI",
  pentest_staging: "Pentest stagingu",
  dast_staging: "ZAP + Schemathesis",
  external_scan: "Skan z zewnątrz",
  accounts_review: "Przegląd kont",
};

export interface CalendarChip {
  routineId: number;
  title: string;
  short: string;
  kind: "done" | "due" | "planned" | "overdue";
}

export interface CalendarDay {
  iso: string;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  chips: CalendarChip[];
}

function addMonthsIso(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const index = y * 12 + (m - 1) + months;
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
}

export function nextCadence(iso: string, cadence: Cadence): string {
  if (cadence === "week") return addDaysIso(iso, 7);
  return addMonthsIso(iso, cadence === "month" ? 1 : 3);
}

/** Terminy rutyny od `next_due_on` w przód, aż do `until` włącznie. */
function plannedDates(routine: SecurityRoutine, until: string): string[] {
  const dates: string[] = [];
  let current = routine.next_due_on;
  while (current <= until && dates.length < 60) {
    dates.push(current);
    current = nextCadence(current, routine.cadence);
  }
  return dates;
}

/** Siatka od poniedziałku: tydzień z `anchor` albo cały miesiąc z `anchor`. */
export function calendarDays(
  routines: readonly SecurityRoutine[],
  anchor: string,
  today: string,
  view: "week" | "month",
): CalendarDay[] {
  const [y, m] = anchor.split("-").map(Number);
  const weekday = (iso: string) => {
    const [yy, mm, dd] = iso.split("-").map(Number);
    return (new Date(Date.UTC(yy, mm - 1, dd)).getUTCDay() + 6) % 7;
  };
  let start: string;
  let length: number;
  if (view === "week") {
    start = addDaysIso(anchor, -weekday(anchor));
    length = 7;
  } else {
    const first = `${y}-${String(m).padStart(2, "0")}-01`;
    start = addDaysIso(first, -weekday(first));
    const last = addDaysIso(addMonthsIso(first, 1), -1);
    const end = addDaysIso(last, 6 - weekday(last));
    length = Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1;
  }
  const end = addDaysIso(start, length - 1);
  const byDay = new Map<string, CalendarChip[]>();
  const push = (iso: string, chip: CalendarChip) => {
    byDay.set(iso, [...(byDay.get(iso) ?? []), chip]);
  };
  for (const routine of routines) {
    const short = ROUTINE_SHORT[routine.key] ?? routine.title;
    if (routine.last_done_on && routine.last_done_on >= start && routine.last_done_on <= end) {
      push(routine.last_done_on, { routineId: routine.id, title: routine.title, short, kind: "done" });
    }
    for (const iso of plannedDates(routine, end)) {
      if (iso < start) continue;
      const kind = iso < today ? "overdue" : iso === routine.next_due_on ? "due" : "planned";
      push(iso, { routineId: routine.id, title: routine.title, short, kind });
    }
  }
  return Array.from({ length }, (_, i) => {
    const iso = addDaysIso(start, i);
    return {
      iso,
      day: Number(iso.slice(8, 10)),
      inMonth: view === "week" || Number(iso.slice(5, 7)) === m,
      isToday: iso === today,
      chips: byDay.get(iso) ?? [],
    };
  });
}

export const CHIP_TONE: Record<CalendarChip["kind"], Tone> = {
  done: "success",
  due: "warning",
  planned: "info",
  overdue: "danger",
};
