// „Przepisy”: etykiety i czyste funkcje ekranu (test bez renderu).

import type {
  ChangeEvent,
  ChangeItem,
  ChangeStage,
  ChangeStatus,
  ChangeUrgency,
  ComplianceRole,
  ItemClass,
  ItemGate,
  LawChangeListItem,
  RadarRun,
  RunKind,
  RunStatus,
} from "@/lib/api/compliance";

export type Lens = "all" | ComplianceRole;
export type View = "changes" | "calendar" | "setup";
export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export const LENSES: readonly { value: Lens; label: string }[] = [
  { value: "all", label: "Wszystko" },
  { value: "board", label: "Zarząd i CFO" },
  { value: "accounting", label: "Księgowość" },
  { value: "payroll", label: "Kadry i płace" },
  { value: "contracts", label: "Umowy" },
  { value: "recruitment", label: "Rekrutacja" },
];

export const ROLE_LABEL: Record<ComplianceRole, string> = {
  board: "Zarząd i CFO",
  accounting: "Księgowość",
  payroll: "Kadry i płace",
  contracts: "Umowy",
  recruitment: "Rekrutacja",
};

export const STAGES: readonly { value: ChangeStage; label: string }[] = [
  { value: "project", label: "Projekt" },
  { value: "sejm", label: "Sejm" },
  { value: "senate", label: "Senat" },
  { value: "president", label: "Prezydent" },
  { value: "journal", label: "Dz.U." },
  { value: "in_force", label: "Obowiązuje" },
];

export const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.value, s.label])) as Record<
  ChangeStage,
  string
>;

export const URGENCY_TONE: Record<ChangeUrgency, Tone> = { now: "danger", soon: "warning", watch: "info" };
export const URGENCY_LABEL: Record<ChangeUrgency, string> = {
  now: "Pilne",
  soon: "W tym kwartale",
  watch: "Obserwujemy",
};

export const STATUS_LABEL: Record<ChangeStatus, string> = {
  new: "Nowe",
  in_progress: "W toku",
  done: "Zrobione",
  not_applicable: "Nie dotyczy nas",
};

export const CLASS_ORDER: readonly ItemClass[] = ["official", "lex", "practice"];
export const CLASS_LABEL: Record<ItemClass, string> = {
  official: "Urzędowe",
  lex: "LEX",
  practice: "Praktyka",
};
export const CLASS_HINT: Record<ItemClass, string> = {
  official: "Źródło urzędowe",
  lex: "LEX (otwiera się na koncie osoby z licencją)",
  practice: "Praktyka rynkowa (Grok Bot) — nie fakt urzędowy",
};

export const GATE_LABEL: Record<ItemGate, string> = {
  pending: "czeka na API Sejmu",
  verified: "zgodne z API Sejmu",
  unverified: "bez potwierdzenia w API Sejmu",
  rejected: "odrzucone przez bramkę",
};

export const VIEWS: readonly { value: View; label: string }[] = [
  { value: "changes", label: "Zmiany" },
  { value: "calendar", label: "Terminy" },
  { value: "setup", label: "Źródła i boty" },
];

export function isLens(value: string | null): value is Lens {
  return LENSES.some((lens) => lens.value === value);
}

export function isView(value: string | null): value is View {
  return VIEWS.some((view) => view.value === value);
}

export function lensRole(lens: Lens): ComplianceRole | null {
  return lens === "all" ? null : lens;
}

const OPEN: ReadonlySet<ChangeStatus> = new Set(["new", "in_progress"]);

export function isOpen(status: ChangeStatus): boolean {
  return OPEN.has(status);
}

/** Otwarte zmiany przed zamkniętymi; w grupie kolejność z API (pilność, termin). */
export function orderChanges(changes: readonly LawChangeListItem[]): LawChangeListItem[] {
  return [...changes.filter((c) => isOpen(c.status)), ...changes.filter((c) => !isOpen(c.status))];
}

/** Liczba dni od `today` do `iso` (obie „RRRR-MM-DD”, kalendarz firmy). */
export function daysBetween(today: string, iso: string): number {
  const [y1, m1, d1] = today.split("-").map(Number);
  const [y2, m2, d2] = iso.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000);
}

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

/** „1.01.2027” z „2027-01-01”. */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return `${d}.${String(m).padStart(2, "0")}.${y}`;
}

/** „15.11.2026, 06:10” ze znacznika czasu (kalendarz firmy). */
export function formatMoment(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "numeric",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function monthTitle(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  const name = MONTHS[m - 1] ?? "";
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${y}`;
}

export function daysLeftLabel(days: number): string {
  if (days < 0) return `po terminie ${-days} ${days === -1 ? "dzień" : "dni"}`;
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  return `za ${days} dni`;
}

export function daysLeftTone(days: number): Tone {
  if (days <= 30) return "danger";
  if (days <= 60) return "warning";
  return "neutral";
}

/** Krótka linia daty na liście: termin, a bez niego wejście w życie. */
export function dateLine(change: Pick<LawChangeListItem, "deadline" | "effective_on">): string {
  if (change.deadline) return `termin ${formatDay(change.deadline)}`;
  if (change.effective_on) return `od ${formatDay(change.effective_on)}`;
  return "bez daty";
}

export interface DeadlineEntry {
  key: string;
  changeId: number;
  title: string;
  date: string;
  kind: "deadline" | "effective";
  days: number;
  roles: ComplianceRole[];
}

/**
 * Terminy z otwartych zmian: `deadline` zawsze (także po terminie — to sprawa
 * do zrobienia), `effective_on` tylko od dziś (przepis już obowiązujący nie
 * jest terminem). Posortowane po dacie.
 */
export function deadlineEntries(changes: readonly LawChangeListItem[], today: string): DeadlineEntry[] {
  const out: DeadlineEntry[] = [];
  for (const change of changes) {
    if (!isOpen(change.status)) continue;
    if (change.deadline) {
      out.push({
        key: `${change.id}-deadline`,
        changeId: change.id,
        title: change.title,
        date: change.deadline,
        kind: "deadline",
        days: daysBetween(today, change.deadline),
        roles: change.roles,
      });
    }
    if (change.effective_on && change.effective_on >= today && change.effective_on !== change.deadline) {
      out.push({
        key: `${change.id}-effective`,
        changeId: change.id,
        title: change.title,
        date: change.effective_on,
        kind: "effective",
        days: daysBetween(today, change.effective_on),
        roles: change.roles,
      });
    }
  }
  return out.sort((a, b) => a.date.localeCompare(b.date) || a.changeId - b.changeId);
}

/** Terminy pogrupowane miesiącami („RRRR-MM”), w kolejności dat. */
export function deadlinesByMonth(entries: readonly DeadlineEntry[]): { month: string; entries: DeadlineEntry[] }[] {
  const groups = new Map<string, DeadlineEntry[]>();
  for (const entry of entries) {
    const month = entry.date.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), entry]);
  }
  return [...groups.entries()].map(([month, list]) => ({ month, entries: list }));
}

export function itemsByClass(items: readonly ChangeItem[]): { klass: ItemClass; items: ChangeItem[] }[] {
  return CLASS_ORDER.map((klass) => ({ klass, items: items.filter((item) => item.klass === klass) })).filter(
    (group) => group.items.length > 0,
  );
}

/** Adres ze źródła bota jako link tylko dla http(s) — reszta zostaje tekstem. */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return /^https?:\/\//i.test(url.trim()) ? url.trim() : null;
}

/** Link sondy prowadzi wyłącznie wewnątrz NEXUSA (ścieżka od „/”, nie „//”). */
export function safeInternalLink(link: string | null | undefined): string | null {
  if (!link) return null;
  return link.startsWith("/") && !link.startsWith("//") ? link : null;
}

export function probeLine(probe: { key: string; value: number | null; text: string | null }): string {
  if (probe.text) return probe.text;
  return probe.value == null ? probe.key : `${probe.key}: ${probe.value}`;
}

export function eventLine(event: ChangeEvent): string {
  switch (event.kind) {
    case "created":
      // Zmianę „Przejrzyj wzory” zakłada NEXUS po nowym tekście aktu w korpusie.
      return event.bot ? "Zmiana założona przez Analityka" : "Zmiana założona przez NEXUS";
    case "updated":
      return "Analityk zaktualizował treść";
    case "stage":
      return `Etap: ${stageName(event.from)} → ${stageName(event.to)}`;
    case "status":
      return `Status: ${statusName(event.from)} → ${statusName(event.to)}`;
    case "task_added":
      return "Dodane zadanie";
    case "task_done":
      return "Zadanie zrobione";
    case "task_reopened":
      return "Zadanie otwarte ponownie";
    case "task_updated":
      return "Zadanie zmienione";
  }
}

function stageName(value: string | null): string {
  return (value && STAGE_LABEL[value as ChangeStage]) || value || "—";
}

function statusName(value: string | null): string {
  return (value && STATUS_LABEL[value as ChangeStatus]) || value || "—";
}

export const RUN_KIND_LABEL: Record<RunKind, string> = {
  collect: "Grok Zbieracz",
  analyze: "Grok Analityk",
};

export const RUN_STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  started: { label: "pracuje", tone: "info" },
  received: { label: "przyjęty", tone: "success" },
  failed: { label: "nieudany", tone: "danger" },
  expired: { label: "wygasł", tone: "warning" },
};

const SUMMARY_LABELS: Record<RunKind, readonly [string, string][]> = {
  collect: [
    ["items_in", "pozycje w raporcie"],
    ["new", "nowe"],
    ["known", "znane"],
    ["duplicates", "powtórki"],
  ],
  analyze: [
    ["changes_in", "zmiany w raporcie"],
    ["created", "nowe zmiany"],
    ["updated", "zaktualizowane"],
    ["stage_changes", "zmiany etapu"],
    ["tasks_added", "nowe zadania"],
  ],
};

const SKIP_REASON_LABEL: Record<string, string> = {
  login_required: "wymagane logowanie",
  device_approval: "wymagane zatwierdzenie urządzenia",
  mfa: "wymagany kod uwierzytelniający",
  access_denied: "odmowa dostępu",
  unavailable: "serwis niedostępny",
  unknown: "przyczyna nieustalona",
};

/** Jedna linia liczb biegu („pozycje w raporcie: 14 · nowe: 9”); nieznane klucze pomija. */
export function runSummaryLine(run: Pick<RadarRun, "kind" | "summary">): string {
  const parts: string[] = [];
  for (const [key, label] of SUMMARY_LABELS[run.kind] ?? []) {
    const value = run.summary[key];
    if (typeof value === "number") parts.push(`${label}: ${value}`);
  }
  const gate = run.summary.gate;
  if (run.kind === "collect" && gate && typeof gate === "object") {
    const n = (key: string) => {
      const value = (gate as Record<string, unknown>)[key];
      return typeof value === "number" ? value : 0;
    };
    parts.push(
      `bramka: zgodne z API Sejmu ${n("verified")}, bez potwierdzenia ${n("unverified")}, odrzucone ${n("rejected")}`,
    );
  }
  if (run.kind === "collect") {
    const saved = run.summary.saved_sources;
    for (const [key, name] of [["lex", "LEX"], ["gofin", "Gofin"]] as const) {
      const skipped = run.summary[`${key}_skipped`] === true;
      const reason = run.summary[`${key}_skip_reason`];
      const count = typeof saved === "object" ? saved[key] : undefined;
      const details: string[] = [];
      if (skipped) {
        const label = typeof reason === "string" ? SKIP_REASON_LABEL[reason] : undefined;
        details.push(label ? `pominięty (${label})` : "pominięty");
      }
      if (typeof count === "number") details.push(`zapisane pozycje: ${count}`);
      if (details.length) parts.push(`${name} ${details.join(", ")}`);
    }
  }
  return parts.join(" · ");
}
