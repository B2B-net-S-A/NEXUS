/**
 * Lista „Kto się liczy” (17.10.2026): kto stoi za liczbami celów —
 * Weryfikacje, Rekomendacje, Placementy — i co się z tymi osobami dzieje teraz.
 *
 * Wiersze daje `GET /api/dashboard/v2/recruitment-activity/details` z tego
 * samego zapytania atrybucji co licznik w górnym pasku, więc liczba wierszy
 * w okresie celu równa się liczbie w pasku. Tu jest tylko prezentacja: okresy,
 * etykiety, grupowanie po dniach i podsumowanie — komponenty to rysują.
 */
import { NEXUS_FIRST_DAY } from "@/lib/insights-history"
import { formatMoney, formatWholeMoney } from "@/lib/money"
import { pluralPl } from "@/lib/plural-pl"
import type {
  RecruitmentActivityDetailItem,
  RecruitmentActivityDetailResponse,
  RecruitmentActivityMargin,
  RecruitmentActivityMetric,
  RecruitmentActivityPerson,
  RecruitmentActivityState,
} from "@/lib/recruitment-activity-api"

export type WhoCountsMetric = RecruitmentActivityMetric
export type WhoCountsPeriodKind = "day" | "week" | "month"

interface WhoCountsMetricDef {
  metric: WhoCountsMetric
  /** Wartość parametru `kto` w adresie. */
  slug: string
  label: string
  noun: readonly [string, string, string]
  /** Okres celu: weryfikacje dziś, rekomendacje w tygodniu, placementy w miesiącu. */
  defaultKind: WhoCountsPeriodKind
  /** Nagłówek kolumny „kto kliknął etap”. */
  moverLabel: string
}

export const WHO_COUNTS_METRICS: Record<WhoCountsMetric, WhoCountsMetricDef> = {
  verification: {
    metric: "verification",
    slug: "weryfikacje",
    label: "Weryfikacje",
    noun: ["weryfikacja", "weryfikacje", "weryfikacji"],
    defaultKind: "day",
    moverLabel: "Zweryfikował(a)",
  },
  recommendation: {
    metric: "recommendation",
    slug: "rekomendacje",
    label: "Rekomendacje",
    noun: ["rekomendacja", "rekomendacje", "rekomendacji"],
    defaultKind: "week",
    moverLabel: "CV wysłał(a)",
  },
  interview: {
    metric: "interview",
    slug: "rozmowy",
    label: "Rozmowy u klienta",
    noun: ["rozmowa u klienta", "rozmowy u klienta", "rozmów u klienta"],
    defaultKind: "week",
    moverLabel: "Rozmowę wpisał(a)",
  },
  acceptance: {
    metric: "acceptance",
    slug: "akceptacje",
    label: "Akceptacje",
    noun: ["akceptacja", "akceptacje", "akceptacji"],
    defaultKind: "month",
    moverLabel: "Akceptację wpisał(a)",
  },
  placement: {
    metric: "placement",
    slug: "placementy",
    label: "Placementy",
    noun: ["placement", "placementy", "placementów"],
    defaultKind: "month",
    moverLabel: "Zatrudnienie wpisał(a)",
  },
}

/** Cele osoby w panelu z górnego paska — i zakładki listy w „Mój miesiąc”. */
export const PERSONAL_WHO_COUNTS: readonly WhoCountsMetric[] = [
  "verification",
  "recommendation",
  "placement",
]

/** Kolumny tabeli Insights → Zespół → Ludzie, które da się otworzyć jako listę. */
export const TEAM_WHO_COUNTS: readonly WhoCountsMetric[] = [
  "verification",
  "recommendation",
  "interview",
  "placement",
]

export function metricFromSlug(slug: string | null | undefined): WhoCountsMetric | null {
  if (!slug) return null
  const found = Object.values(WHO_COUNTS_METRICS).find((def) => def.slug === slug)
  return found ? found.metric : null
}

/** Id celu z katalogu KPI (`kpi_catalog.py`) → lista. */
export const KPI_ID_TO_WHO_COUNTS: Readonly<Record<string, WhoCountsMetric>> = {
  daily_first_verifications: "verification",
  weekly_cvs_sent: "recommendation",
  monthly_placements: "placement",
}

export const WHO_COUNTS_ANCHOR = "kto-sie-liczy"

/** Link z panelu celów na listę osoby w okresie celu. */
export function whoCountsHref(metric: WhoCountsMetric): string {
  return `/insights?tab=moj-miesiac&kto=${WHO_COUNTS_METRICS[metric].slug}#${WHO_COUNTS_ANCHOR}`
}

// ── Okresy (dni kalendarza firmy, „YYYY-MM-DD”) ─────────────────────────────

const PERIOD_SLUGS: Record<WhoCountsPeriodKind, string> = {
  day: "dzien",
  week: "tydzien",
  month: "miesiac",
}

export function periodKindFromSlug(slug: string | null | undefined): WhoCountsPeriodKind | null {
  const entry = Object.entries(PERIOD_SLUGS).find(([, value]) => value === slug)
  return entry ? (entry[0] as WhoCountsPeriodKind) : null
}

export function periodKindSlug(kind: WhoCountsPeriodKind): string {
  return PERIOD_SLUGS[kind]
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

export function isIsoDay(value: string | null | undefined): value is string {
  if (!value || !ISO_DAY.test(value)) return false
  const parsed = toUtcNoon(value)
  return !Number.isNaN(parsed.getTime()) && fromUtc(parsed) === value
}

/** Dzisiejsza data w kalendarzu firmy (Europe/Warsaw), nie w UTC. */
export function warsawToday(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

/** Dzień zdarzenia w kalendarzu firmy. */
export function warsawDay(iso: string): string {
  return warsawToday(new Date(iso))
}

function toUtcNoon(day: string): Date {
  return new Date(`${day}T12:00:00Z`)
}

function fromUtc(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function addDays(day: string, days: number): string {
  const date = toUtcNoon(day)
  date.setUTCDate(date.getUTCDate() + days)
  return fromUtc(date)
}

export function weekStart(day: string): string {
  const weekday = (toUtcNoon(day).getUTCDay() + 6) % 7 // poniedziałek = 0
  return addDays(day, -weekday)
}

function monthStart(day: string): string {
  return `${day.slice(0, 7)}-01`
}

function addMonths(day: string, months: number): string {
  const date = toUtcNoon(monthStart(day))
  date.setUTCMonth(date.getUTCMonth() + months)
  return fromUtc(date)
}

export interface DayRange {
  start: string
  /** Ostatni dzień okresu (włącznie). */
  end: string
}

export function periodRange(kind: WhoCountsPeriodKind, anchor: string): DayRange {
  if (kind === "day") return { start: anchor, end: anchor }
  if (kind === "week") {
    const start = weekStart(anchor)
    return { start, end: addDays(start, 6) }
  }
  const start = monthStart(anchor)
  return { start, end: addDays(addMonths(start, 1), -1) }
}

/** Początek okresu przesuniętego o `delta` okresów. */
export function shiftPeriod(kind: WhoCountsPeriodKind, anchor: string, delta: number): string {
  if (kind === "day") return addDays(anchor, delta)
  if (kind === "week") return addDays(weekStart(anchor), delta * 7)
  return addMonths(anchor, delta)
}

/** Następny okres zaczyna się po dzisiejszym dniu — strzałka „dalej” jest martwa. */
export function isLatestPeriod(kind: WhoCountsPeriodKind, anchor: string, today: string): boolean {
  return shiftPeriod(kind, anchor, 1) > today
}

const SHORT_MONTH = new Intl.DateTimeFormat("pl-PL", { month: "short", timeZone: "UTC" })
const LONG_MONTH = new Intl.DateTimeFormat("pl-PL", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
})
const WEEKDAY = new Intl.DateTimeFormat("pl-PL", { weekday: "long", timeZone: "UTC" })

function dayMonth(day: string): string {
  return `${Number(day.slice(8, 10))}.${day.slice(5, 7)}`
}

/** „12–18 paź”, „29 wrz – 5 paź”, z rokiem, gdy nie jest bieżący. */
export function rangeLabel(range: DayRange, today: string): string {
  const { start, end } = range
  const year = start.slice(0, 4) === today.slice(0, 4) && end.slice(0, 4) === today.slice(0, 4)
    ? ""
    : ` ${end.slice(0, 4)}`
  if (start === end) return `${WEEKDAY.format(toUtcNoon(start))} ${dayMonth(start)}${year}`
  const startMonth = SHORT_MONTH.format(toUtcNoon(start))
  const endMonth = SHORT_MONTH.format(toUtcNoon(end))
  const startDay = Number(start.slice(8, 10))
  const endDay = Number(end.slice(8, 10))
  if (start.slice(0, 7) === end.slice(0, 7)) return `${startDay}–${endDay} ${endMonth}${year}`
  return `${startDay} ${startMonth} – ${endDay} ${endMonth}${year}`
}

export function periodLabel(kind: WhoCountsPeriodKind, anchor: string, today: string): string {
  if (kind === "month") return LONG_MONTH.format(toUtcNoon(monthStart(anchor)))
  return rangeLabel(periodRange(kind, anchor), today)
}

/** „dziś”, „ten tydzień”, „ten miesiąc” albo nic dla okresu z przeszłości. */
export function currentPeriodHint(
  kind: WhoCountsPeriodKind,
  anchor: string,
  today: string,
): string | null {
  const { start, end } = periodRange(kind, anchor)
  if (today < start || today > end) return null
  if (kind === "day") return "dziś"
  if (kind === "week") return "ten tydzień"
  return "ten miesiąc"
}

// ── Stan pary „teraz” ──────────────────────────────────────────────────────

export type WhoCountsTone = "neutral" | "info" | "success" | "danger" | "warning"

/** Kolejność filtrów stanu: od przed wysyłką do zakończeń. */
export const STATE_ORDER: readonly RecruitmentActivityState[] = [
  "before_client",
  "waiting",
  "at_client",
  "hired",
  "rejected_by_client",
  "ended",
  "job_closed",
]

export const STATE_FILTER_LABELS: Record<RecruitmentActivityState, string> = {
  before_client: "Przed wysłaniem",
  waiting: "Czekają na klienta",
  at_client: "U klienta",
  hired: "Zatrudnienia",
  rejected_by_client: "Klient odrzucił",
  ended: "Inne zakończenia",
  job_closed: "Rekrutacja zamknięta",
}

export const STATE_TONES: Record<RecruitmentActivityState, WhoCountsTone> = {
  before_client: "neutral",
  waiting: "neutral",
  at_client: "info",
  hired: "success",
  rejected_by_client: "danger",
  ended: "warning",
  job_closed: "warning",
}

const AT_CLIENT_STAGES: Record<string, string> = {
  client_interview: "Rozmowa u klienta",
  acceptance: "Klient zaakceptował",
  negotiation: "Negocjacje",
}

function daysBetween(from: string, to: string): number {
  return Math.round((toUtcNoon(to).getTime() - toUtcNoon(from).getTime()) / 86_400_000)
}

/** Tekst kolumny „Teraz”. `null` = stary kształt odpowiedzi bez stanu. */
export function stateText(
  item: RecruitmentActivityDetailItem,
  today: string,
  options: { withTerm?: boolean } = {},
): { label: string; tone: WhoCountsTone } | null {
  const state = item.state ?? null
  if (!state) return null
  const tone = STATE_TONES[state]
  const reason = item.state_reason ? ` · ${item.state_reason}` : ""
  const since = item.state_since ? warsawDay(item.state_since) : null
  // Ile dni para stoi w obecnym etapie: „ · od dziś”, „ · 3 dni”.
  const inStage = since ? ` · ${daysInStage(since, today)}` : ""
  // Etap z procesu klienta w nawiasie (prośba Olafa 27.11.2026, wariant A3).
  const stageName = item.state_stage_name?.trim() || null
  switch (state) {
    case "waiting":
      return { label: `Czeka na klienta${inStage}`, tone }
    case "at_client": {
      const label = AT_CLIENT_STAGES[item.state_stage ?? ""] ?? "U klienta"
      return options.withTerm && item.state_stage === "client_interview" && item.client_interview_at
        ? { label: `${label} · ${formatTerm(item.client_interview_at)}`, tone }
        : { label, tone }
    }
    case "hired":
      return { label: since ? `Zatrudnienie ${dayMonth(since)}` : "Zatrudnienie", tone }
    case "rejected_by_client":
      return { label: `Klient odrzucił${reason}`, tone }
    case "ended": {
      const where = stageName ? ` (na ${stageName})` : ""
      return {
        label:
          item.state_stage === "withdrawn"
            ? `Rezygnacja kandydata${where}${reason}`
            : `Odrzucenie u nas${where}${reason}`,
        tone,
      }
    }
    case "job_closed":
      return { label: "Rekrutacja zamknięta", tone }
    case "before_client":
      return {
        label: `Przed wysłaniem do klienta${stageName ? ` (${stageName})` : ""}${inStage}`,
        tone,
      }
  }
}

function daysInStage(since: string, today: string): string {
  const days = Math.max(daysBetween(since, today), 0)
  return days === 0 ? "od dziś" : `${days} ${pluralPl(days, "dzień", "dni", "dni")}`
}

// ── Wiersze i podsumowanie ─────────────────────────────────────────────────

export interface WhoCountsDay {
  day: string
  label: string
  items: RecruitmentActivityDetailItem[]
}

/** Wiersze strony pogrupowane po dniu osiągnięcia (od najnowszego, jak przyszły). */
export function groupByDay(
  items: readonly RecruitmentActivityDetailItem[],
  today: string,
): WhoCountsDay[] {
  const groups: WhoCountsDay[] = []
  for (const item of items) {
    const day = warsawDay(item.reached_at)
    const last = groups[groups.length - 1]
    if (last && last.day === day) {
      last.items.push(item)
      continue
    }
    const weekday = WEEKDAY.format(toUtcNoon(day))
    const label = day === today
      ? `Dziś · ${weekday} ${dayMonth(day)}`
      : `${weekday[0].toUpperCase()}${weekday.slice(1)} ${dayMonth(day)}${day.slice(0, 4) === today.slice(0, 4) ? "" : `.${day.slice(0, 4)}`}`
    groups.push({ day, label, items: [item] })
  }
  return groups
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).format(new Date(iso))
}

const SHORT_WEEKDAY = new Intl.DateTimeFormat("pl-PL", {
  weekday: "short",
  timeZone: "Europe/Warsaw",
})

/** „śr 11.11, 10:00” w kalendarzu firmy. */
export function formatTerm(iso: string): string {
  const weekday = SHORT_WEEKDAY.format(new Date(iso)).replace(".", "")
  return `${weekday} ${dayMonth(warsawDay(iso))}, ${formatTime(iso)}`
}

export type InterviewTermKind = "today" | "upcoming" | "past" | "tentative" | "none"

export interface InterviewTerm {
  kind: InterviewTermKind
  label: string
  hint: string | null
}

/** Komórka „Termin rozmowy”: potwierdzony termin, propozycja albo brak. */
export function interviewTerm(
  item: RecruitmentActivityDetailItem,
  today: string,
): InterviewTerm {
  const at = item.client_interview_at
  const tentative = item.client_interview_tentative_at
  // Para zamknięta: termin jest historią, nawet gdy wypada dziś albo później.
  const closed = item.state === "rejected_by_client" || item.state === "ended"
  if (at) {
    const days = daysBetween(today, warsawDay(at))
    if (closed) {
      return { kind: "past", label: formatTerm(at), hint: days >= 0 ? "proces zakończony" : null }
    }
    if (days === 0) return { kind: "today", label: `Dziś, ${formatTime(at)}`, hint: null }
    if (days > 0) {
      return {
        kind: "upcoming",
        label: formatTerm(at),
        hint: days === 1 ? "jutro" : `za ${days} dni`,
      }
    }
    // Po minionej rundzie otwarta propozycja mówi o następnej.
    if (!tentative) return { kind: "past", label: formatTerm(at), hint: null }
  }
  if (tentative) return { kind: "tentative", label: formatTerm(tentative), hint: "do potwierdzenia" }
  return { kind: "none", label: "Brak terminu", hint: null }
}

/**
 * Układ „po terminie”: kolejność daje serwer (`order=term`), tu tylko podział
 * na grupy według tego, co pokazuje komórka terminu.
 */
export function groupByTerm(
  items: readonly RecruitmentActivityDetailItem[],
  today: string,
): WhoCountsDay[] {
  const groups: Record<"upcoming" | "past" | "none", WhoCountsDay> = {
    upcoming: { day: "upcoming", label: "Przed nami", items: [] },
    past: { day: "past", label: "Termin minął", items: [] },
    none: { day: "none", label: "Bez terminu w kalendarzu", items: [] },
  }
  for (const item of items) {
    const { kind } = interviewTerm(item, today)
    groups[kind === "none" || kind === "past" ? kind : "upcoming"].items.push(item)
  }
  return Object.values(groups).filter((group) => group.items.length > 0)
}

/** „6.11, 14:53”: kiedy etap wpisano, pod osobą, która to zrobiła. */
export function formatReached(iso: string): string {
  return `${dayMonth(warsawDay(iso))}, ${formatTime(iso)}`
}

/** „3.11.2026” bez przesunięć strefy — `start_on` to sama data. */
export function formatDay(day: string): string {
  return `${dayMonth(day)}.${day.slice(0, 4)}`
}

const ROLE_SHORT: Record<string, string> = {
  delivery_lead: "DL",
  head_of_recruitment: "Head of Recruitment",
  admin: "admin",
}

/** Kto kliknął etap: „Ty”, imię z dopiskiem roli albo „—”. */
export function moverText(
  person: RecruitmentActivityPerson | null | undefined,
  viewerId: number | null,
): string {
  if (!person) return "—"
  if (viewerId !== null && person.id === viewerId) return "Ty"
  const role = ROLE_SHORT[person.role]
  return role ? `${person.name} (${role})` : person.name
}

export function countNoun(metric: WhoCountsMetric, count: number): string {
  const [one, few, many] = WHO_COUNTS_METRICS[metric].noun
  return `${count} ${pluralPl(count, one, few, many)}`
}

/**
 * „23 rekomendacje · 21 osób · CV wysłane przez Ciebie: 7, pozostałe: 16”.
 * „Pozostałe”, nie „przez kogoś innego”: wiersz z importu nie ma autora ruchu.
 */
export function summaryParts(
  response: RecruitmentActivityDetailResponse,
  metric: WhoCountsMetric,
  viewerId: number | null,
): string[] {
  const total = response.period_total ?? response.total
  const parts = [countNoun(metric, total)]
  if (total === 0) return parts
  // Wpisy DynaReportera są w liczbie, ale nie na liście — reszta podsumowania
  // opisuje tylko wiersze listy.
  const history = response.history_total ?? 0
  const listed = total - history
  const people = response.people ?? 0
  if (people > 0 && people !== listed) {
    parts.push(`${people} ${pluralPl(people, "osoba", "osoby", "osób")}`)
  }
  if (history > 0) parts.push(`${history} z DynaReportera (do 11.10.2026)`)
  const self = response.moved_by_credited
  if (
    metric !== "verification" &&
    response.scope === "person" &&
    typeof self === "number" &&
    listed > 0
  ) {
    const other = listed - self
    const mine = viewerId !== null && response.subject?.id === viewerId
    const verb = metric === "recommendation" ? "CV wysłane" : "Etap wpisany"
    parts.push(
      mine
        ? `${verb} przez Ciebie: ${self}, pozostałe: ${other}`
        : `${verb} przez tę osobę: ${self}, pozostałe: ${other}`,
    )
  }
  return parts
}

// ── Marża placementów (decyzje Artura 27.11.2026) ─────────────────────────

/** Czego brakuje, gdy marży nie ma — podpowiedź na „—”. */
export const MARGIN_MISSING_TEXT: Record<NonNullable<RecruitmentActivityMargin["missing"]>, string> = {
  no_contract: "Brak kontraktu do tej pary",
  missing_rates: "Brak stawki w kontrakcie i w rekrutacji",
  fx_missing: "Brak kursu waluty z dnia startu",
}

export const MARGIN_HIDDEN_TEXT = "Kwoty tylko klientów z Twojego portfela"

/**
 * Wiersz marży pod podsumowaniem listy placementów. Suma z całego okresu
 * (wszystkie strony), z wierszy, które odbiorca widzi; bez prawa do kwot — nic.
 */
export function marginSummaryParts(response: RecruitmentActivityDetailResponse): string[] {
  const summary = response.margin_summary
  if (!response.margin_scope || !summary) return []
  const total = `${formatMoney(summary.per_hour, "PLN", "hourly")} · ${formatWholeMoney(summary.per_month)}/mies.`
  const parts =
    response.margin_scope === "portfolio"
      ? [
          `Marża Twoich klientów (${summary.counted} ${pluralPl(summary.counted, "placement", "placementy", "placementów")}): ${total}`,
        ]
      : [`Marża łącznie: ${total}`]
  if (summary.from_recruitment > 0) {
    parts.push(`${summary.from_recruitment} ze stawką klienta z rekrutacji`)
  }
  if (summary.negative > 0) parts.push(`${summary.negative} na minus`)
  if (summary.missing > 0) parts.push(`${summary.missing} bez marży (brak stawki)`)
  if (summary.hidden > 0) {
    parts.push(
      `${summary.hidden} ${pluralPl(summary.hidden, "placement", "placementy", "placementów")} klientów spoza Twojego portfela`,
    )
  }
  return parts
}

/**
 * Zdanie pod podsumowaniem, gdy część liczby to tygodniowe wpisy DynaReportera
 * (decyzja Artura 17.10.2026: do 11.10.2026 wynik to wpis w DynaReporterze).
 */
export function historyNote(response: RecruitmentActivityDetailResponse): string | null {
  const history = response.history_total ?? 0
  if (history <= 0) return null
  return `Dni do 11.10.2026 pochodzą z tygodniowych wpisów w DynaReporterze (${history}). Liczą się do wyniku, ale DynaReporter nie zapisywał kandydatów, więc nie ma ich na liście.`
}

/** Filtry stanu z liczbami całego okresu; tylko stany, które wystąpiły. */
export function stateFilters(
  response: RecruitmentActivityDetailResponse,
): { state: RecruitmentActivityState; label: string; count: number }[] {
  const states = response.states ?? {}
  return STATE_ORDER.flatMap((state) => {
    const count = states[state] ?? 0
    return count > 0 ? [{ state, label: STATE_FILTER_LABELS[state], count }] : []
  })
}

/** Znaczek „2 rekrutacje”, gdy ta sama osoba liczy się w okresie więcej niż raz. */
export function candidateJobsBadge(item: RecruitmentActivityDetailItem): string | null {
  const jobs = item.candidate_jobs ?? 1
  return jobs > 1 ? `${jobs} ${pluralPl(jobs, "rekrutacja", "rekrutacje", "rekrutacji")}` : null
}

export const WHO_COUNTS_FOOTNOTES: Record<WhoCountsMetric, string> = {
  verification:
    "Liczy się pierwsze wejście pary na „QC CV” albo dalej po weryfikacji, w danej rekrutacji.",
  recommendation:
    "Liczy się pierwsza wysyłka CV osoby do klienta w danej rekrutacji. Zasługa idzie do osoby, która zweryfikowała kandydata, także gdy CV wysłał Delivery Lead. Ta sama osoba w dwóch rekrutacjach to dwie rekomendacje.",
  interview:
    "Liczy się pierwsza rozmowa u klienta w danej rekrutacji, przypisana osobie, która zweryfikowała kandydata.",
  acceptance:
    "Liczy się pierwsza akceptacja klienta w danej rekrutacji, przypisana osobie, która zweryfikowała kandydata.",
  placement:
    "Liczy się pierwsze zatrudnienie osoby w danej rekrutacji, przypisane osobie, która zweryfikowała kandydata.",
}

// ── Lista całego zespołu otwarta z lejka (25.10.2026) ───────────────────────

export interface TeamListReconcile {
  /** „Do tego 1 rekomendacja bez osoby z zasługą.” — `null`, gdy takich nie ma. */
  unattributed: string | null
  /** Zdanie o różnicy z klikniętą liczbą — `null`, gdy lista się z nią zgadza. */
  mismatch: string | null
}

/**
 * Lejek liczy pierwsze wejście pary na etap, a lista zasługę jak cele i wyścigi
 * (pierwszy zaakceptowany weryfikator). Zwykle to ta sama liczba; gdy nie,
 * ekran mówi obie zamiast udawać, że się zgadzają (staging 25.10.2026:
 * rekomendacje 447 + 1 bez zasługi = 448 jak lejek, weryfikacje 506 + 1 = 507
 * przy 506 w lejku).
 */
export function teamListReconcile(
  metric: WhoCountsMetric,
  clicked: number | null,
  team: number,
  unattributed: number,
): TeamListReconcile {
  const [one, few, many] = WHO_COUNTS_METRICS[metric].noun
  const listed = team + unattributed
  return {
    unattributed:
      unattributed > 0
        ? `Do tego ${unattributed} ${pluralPl(unattributed, one, few, many)} bez osoby z zasługą.`
        : null,
    mismatch:
      clicked !== null && clicked !== listed
        ? `Lejek pokazuje ${clicked}, lista ${listed}: lejek liczy pierwsze wejście pary na etap, lista — zasługę tak jak cele i wyścigi.`
        : null,
  }
}

/** Akceptacje liczymy od 12.10.2026 — wcześniej „nie liczono”, nie zero. */
export function countedSince(metric: WhoCountsMetric, range: DayRange): "none" | "partial" | "full" {
  if (metric !== "acceptance" || range.start >= NEXUS_FIRST_DAY) return "full"
  return range.end < NEXUS_FIRST_DAY ? "none" : "partial"
}
