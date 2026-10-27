// Pulpit „Requesty i obłożenie" (makieta C6) — filtry i grupowanie po stronie
// przeglądarki. Requestów „Szukamy" jest kilkadziesiąt, więc nie ma po co
// pytać serwera przy każdej zmianie filtra. Czyste funkcje — testy w
// `__tests__/request-board.test.ts`.

import type {
  BoardGroup,
  BoardPerson,
  BoardRequest,
  LoadPerson,
  RequestBoard,
} from "@/lib/api/requestAllocation"
import type { RequestBoardScope } from "@/lib/api/userDashboard"
import { hasRecruiterRole } from "@/lib/job-collaborators"
import {
  hasRecruiter,
  proposedRecruiters,
  workingRecruiters,
  type RecruiterLike,
} from "@/lib/job-team"
import { defaultSortForScope, encodeJobsListUrl } from "@/lib/jobs-url-filters"
import { pluralPl } from "@/lib/plural-pl"
import {
  isPriorityLevel,
  priorityLevelOf,
  type PriorityLevel,
} from "@/lib/request-priority"

export type DueFilter = "late" | "week" | "two" | "none"
export type SentFilter = "0" | "12" | "3" | "champ"

/**
 * Filtry pulpitu. Pola-listy przyjmują kilka wartości naraz (prośba Head of
 * Recruitment 27.10.2026): w obrębie jednego filtra wystarczy dowolna
 * z zaznaczonych, między filtrami muszą zgadzać się wszystkie. Pusta lista =
 * filtr wyłączony.
 */
export interface BoardFilters {
  q: string
  client: string[]
  /** Id Delivery Leadów; `none` = request bez Delivery Leada. */
  lead: string[]
  due: DueFilter[]
  sent: SentFilter[]
  /**
   * Własny przedział „Wysłani” — liczby całkowite jako tekst z pola, pusty =
   * bez tej granicy. Liczy się razem z zaznaczonymi pozycjami (dowolna
   * z nich wystarczy) i jak one pomija requesty z championem.
   */
  sentFrom: string
  sentTo: string
  /** „Rekruter” — id osób, które PRACUJĄ nad requestem (propozycja to za mało). */
  who: string[]
  cat: string[]
  prio: PriorityLevel[]
  /** „Bez rekrutera”: `1` = tylko requesty, przy których nikt nie pracuje. */
  nobody: "" | "1"
}

export const EMPTY_FILTERS: BoardFilters = {
  q: "",
  client: [],
  lead: [],
  due: [],
  sent: [],
  sentFrom: "",
  sentTo: "",
  who: [],
  cat: [],
  prio: [],
  nobody: "",
}

export const DUE_OPTIONS: { value: DueFilter; label: string }[] = [
  { value: "late", label: "Po terminie" },
  { value: "week", label: "Do 7 dni" },
  { value: "two", label: "Do 14 dni" },
  { value: "none", label: "Bez terminu" },
]

export const SENT_OPTIONS: { value: SentFilter; label: string }[] = [
  { value: "0", label: "Nikt nie wysłany" },
  { value: "12", label: "1–2 wysłane" },
  { value: "3", label: "3 i więcej" },
  { value: "champ", label: "Mają championa" },
]

/** Parametry adresu — link z daily otwiera ten sam widok. */
const URL_KEYS: Record<keyof BoardFilters, string> = {
  q: "rb_q",
  client: "rb_client",
  lead: "rb_lead",
  due: "rb_due",
  sent: "rb_sent",
  sentFrom: "rb_sent_from",
  sentTo: "rb_sent_to",
  who: "rb_who",
  cat: "rb_cat",
  prio: "rb_prio",
  nobody: "rb_nobody",
}

/** Granica przedziału z pola albo adresu: liczba całkowita ≥ 0, inaczej pusto. */
export function sentBound(raw: string): string {
  const text = raw.trim()
  return /^\d{1,4}$/.test(text) ? String(Number(text)) : ""
}

export function filtersFromParams(params: URLSearchParams): BoardFilters {
  // Kilka wartości = powtórzony klucz (`rb_cat=1&rb_cat=2`), nie przecinek:
  // nazwa klienta może go zawierać. Stary link z jedną wartością czyta się tak samo.
  const list = (key: keyof BoardFilters) => [
    ...new Set(params.getAll(URL_KEYS[key]).filter(Boolean)),
  ]
  const known = <T extends string>(key: keyof BoardFilters, allowed: (v: string) => boolean) =>
    list(key).filter(allowed) as T[]
  return {
    q: params.get(URL_KEYS.q) ?? "",
    client: list("client"),
    lead: list("lead"),
    due: known<DueFilter>("due", (v) => DUE_OPTIONS.some((o) => o.value === v)),
    sent: known<SentFilter>("sent", (v) => SENT_OPTIONS.some((o) => o.value === v)),
    sentFrom: sentBound(params.get(URL_KEYS.sentFrom) ?? ""),
    sentTo: sentBound(params.get(URL_KEYS.sentTo) ?? ""),
    who: list("who"),
    cat: list("cat"),
    prio: known<PriorityLevel>("prio", isPriorityLevel),
    nobody: params.get(URL_KEYS.nobody) === "1" ? "1" : "",
  }
}

export function filtersToParams(
  filters: BoardFilters,
  base: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of Object.keys(URL_KEYS) as (keyof BoardFilters)[]) {
    next.delete(URL_KEYS[key])
    const value = filters[key]
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item) next.append(URL_KEYS[key], item)
    }
  }
  return next
}

/** Filtry tak, jak widzi je osoba: „Wysłani” to jedno pole z przedziałem. */
function activeFields(filters: BoardFilters): boolean[] {
  return [
    Boolean(filters.q),
    filters.client.length > 0,
    filters.lead.length > 0,
    filters.due.length > 0,
    isSentActive(filters),
    filters.who.length > 0,
    filters.cat.length > 0,
    filters.prio.length > 0,
    Boolean(filters.nobody),
  ]
}

export function isSentActive(filters: Pick<BoardFilters, "sent" | "sentFrom" | "sentTo">): boolean {
  return filters.sent.length > 0 || Boolean(filters.sentFrom) || Boolean(filters.sentTo)
}

export function hasActiveFilters(filters: BoardFilters): boolean {
  return activeFields(filters).some(Boolean)
}

/** Ile filtrów ma wartość inną niż domyślna (pusta) — licznik przy „Pokazuję”. */
export function activeFilterCount(filters: BoardFilters): number {
  return activeFields(filters).filter(Boolean).length
}

/** Czy adres niesie własne filtry pulpitu — wtedy wygrywają z zakresem kafelka. */
export function hasUrlFilters(params: URLSearchParams): boolean {
  return Object.values(URL_KEYS).some((key) => Boolean(params.get(key)))
}

/** Przedział słowami: „3–5”, „od 3”, „do 5”; pusto bez granic. */
export function sentRangeLabel(filters: Pick<BoardFilters, "sentFrom" | "sentTo">): string {
  const [from, to] = sentRange(filters)
  if (from !== null && to !== null) return from === to ? `${from}` : `${from}–${to}`
  if (from !== null) return `od ${from}`
  if (to !== null) return `do ${to}`
  return ""
}

/** Granice przedziału jako liczby; odwrócone („od 5 do 2”) czytamy jako 2–5. */
function sentRange(
  filters: Pick<BoardFilters, "sentFrom" | "sentTo">,
): [number | null, number | null] {
  const from = filters.sentFrom ? Number(filters.sentFrom) : null
  const to = filters.sentTo ? Number(filters.sentTo) : null
  if (from !== null && to !== null && from > to) return [to, from]
  return [from, to]
}

type BoardViewer = RequestBoard["viewer"]

/**
 * Filtry startowe kafelka z jego zakresu: „Moja kategoria” = główna kategoria
 * osoby, która patrzy; „Moje jako Delivery Lead” = requesty, w których ona jest
 * DL-em. Bez danych o widzu (starszy backend) albo bez kategorii — nic, czyli
 * wszystkie requesty: lepiej pokazać za dużo niż pustą tabelę.
 */
export function scopeFilters(
  scope: RequestBoardScope | null | undefined,
  viewer: BoardViewer,
): Partial<BoardFilters> {
  if (!viewer) return {}
  if (scope === "my_category") {
    return viewer.primary_category_id == null
      ? {}
      : { cat: [String(viewer.primary_category_id)] }
  }
  if (scope === "my_lead") return { lead: [String(viewer.user_id)] }
  return {}
}

/** Linia pod nagłówkiem kafelka, gdy działa filtr zakresu. */
export const SCOPE_LABEL: Record<Exclude<RequestBoardScope, "all">, string> = {
  my_category: "Filtr: Twoja kategoria",
  my_lead: "Filtr: requesty, w których jesteś Delivery Leadem",
}

/** Wartość filtra `cat` dla grupy pulpitu (`none` = bez kategorii). */
export function groupCatValue(group: Pick<BoardGroup, "category_id">): string {
  return group.category_id === null ? "none" : String(group.category_id)
}

/**
 * „Następna kategoria →” na daily: po kolei grupy pulpitu, z ostatniej
 * z powrotem na „Wszystkie” (`""`). Nieznana wartość = pierwsza grupa.
 */
export function nextCategory(
  groups: readonly Pick<BoardGroup, "category_id">[],
  current: string,
): string {
  if (groups.length === 0) return ""
  const values = groups.map(groupCatValue)
  if (!current) return values[0]
  const index = values.indexOf(current)
  if (index < 0) return values[0]
  return index === values.length - 1 ? "" : values[index + 1]
}

const WEEKDAY_GENITIVE: Record<string, string> = {
  Mon: "poniedziałku",
  Tue: "wtorku",
  Wed: "środy",
  Thu: "czwartku",
  Fri: "piątku",
  Sat: "soboty",
  Sun: "niedzieli",
}

/**
 * Początek okna „Zmiany od wczoraj” słowami, w czasie firmy (Europe/Warsaw):
 * `od piątku 9:30`. `null` = backend nie podał okna.
 */
export function changesSinceLabel(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Warsaw",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date)
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? ""
  const day = WEEKDAY_GENITIVE[get("weekday")]
  if (!day) return null
  return `od ${day} ${Number(get("hour"))}:${get("minute")}`
}

/** Bez polskich znaków i wielkości liter — tak szuka pole „Stanowisko” i lista osób. */
export const fold = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toLowerCase()

/** Dni do terminu (ujemne = po terminie); `null` = brak terminu. */
export function daysToDeadline(deadline: string | null, today: string): number | null {
  if (!deadline) return null
  const ms = Date.parse(`${deadline}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)
  return Math.round(ms / 86_400_000)
}

export function deadlineLabel(deadline: string | null, today: string): string {
  const days = daysToDeadline(deadline, today)
  if (days === null) return "brak terminu"
  if (days < 0) return `po terminie ${-days} ${-days === 1 ? "dzień" : "dni"}`
  if (days === 0) return "dziś"
  if (days === 1) return "jutro"
  return `za ${days} dni`
}

// ── Kto pracuje nad requestem ───────────────────────────────────────────────

/**
 * Osoby do pokazania przy requeście: pracujący, a propozycja automatu tylko
 * wtedy, gdy nie pracuje nikt i request nie ma championa. Propozycja przy
 * obsadzonym requeście albo przy requeście z championem (ten wypada z puli
 * automatu) jest już nieaktualna — serwer nie pokazuje jej Head of Recruitment
 * i odmawia akceptacji (409), a automat wycofa ją przy najbliższym przebiegu.
 * Chip z „Akceptuj” kończyłby się wtedy samym błędem. Ta sama reguła
 * w kolumnie „Rekruter” listy rekrutacji (osoby z `recruitersOf`).
 */
export function boardPeople<T extends RecruiterLike = BoardPerson>(request: {
  people: readonly T[]
  champion?: boolean
}): T[] {
  const working = workingRecruiters(request.people)
  if (working.length > 0 || request.champion) return working
  return proposedRecruiters(request.people)
}

/**
 * „Bez rekrutera”: szukamy kandydatów, a nikt nad requestem nie pracuje.
 * Sama propozycja automatu to jeszcze nie przydział. Request z championem
 * się nie liczy — tam nikt już nie szuka i nikogo nie da się dodać.
 */
export function needsRecruiter(
  request: Pick<BoardRequest, "people" | "champion">,
): boolean {
  return !request.champion && !hasRecruiter(request.people)
}

/** Ile propozycji automatu czeka na decyzję (requesty bez pracującej osoby). */
export function pendingProposalCount(board: Pick<RequestBoard, "requests">): number {
  return board.requests.reduce(
    (sum, request) => sum + boardPeople(request).filter((p) => p.proposed).length,
    0,
  )
}

function matchesDue(due: DueFilter, days: number | null): boolean {
  if (due === "none") return days === null
  if (days === null) return false
  if (due === "late") return days < 0
  return days >= 0 && days <= (due === "week" ? 7 : 14)
}

/** Pozycje 0 / 1–2 / 3+ i własny przedział pomijają requesty z championem. */
function matchesSent(sent: SentFilter, request: BoardRequest): boolean {
  if (sent === "champ") return request.champion
  if (request.champion) return false
  if (sent === "0") return request.sent === 0
  if (sent === "12") return request.sent >= 1 && request.sent <= 2
  return request.sent >= 3
}

function matchesSentFilter(request: BoardRequest, filters: BoardFilters): boolean {
  if (!isSentActive(filters)) return true
  if (filters.sent.some((sent) => matchesSent(sent, request))) return true
  const [from, to] = sentRange(filters)
  if (from === null && to === null) return false
  return (
    !request.champion &&
    (from === null || request.sent >= from) &&
    (to === null || request.sent <= to)
  )
}

export function matchesFilters(
  request: BoardRequest,
  filters: BoardFilters,
  today: string,
): boolean {
  // Pole „Stanowisko” znajduje request także po numerze u klienta (Nordea).
  if (
    filters.q &&
    !fold(`${request.title} ${request.client_reference ?? ""}`).includes(fold(filters.q.trim()))
  )
    return false
  if (filters.client.length > 0 && !filters.client.includes(request.client_name ?? ""))
    return false
  if (filters.cat.length > 0 && !filters.cat.includes(String(request.category_id ?? "none")))
    return false
  if (
    filters.lead.length > 0 &&
    !filters.lead.includes(String(request.delivery_lead?.id ?? "none"))
  )
    return false
  if (filters.prio.length > 0 && !filters.prio.includes(priorityLevelOf(request)))
    return false
  // „Rekruter” znaczy to samo co na liście rekrutacji: osoba pracuje nad
  // requestem. Propozycja automatu przed akceptacją nikogo nie przypisuje.
  if (
    filters.who.length > 0 &&
    !workingRecruiters(request.people).some((p) => filters.who.includes(String(p.user_id)))
  )
    return false
  if (filters.nobody && !needsRecruiter(request)) return false
  if (filters.due.length > 0) {
    const days = daysToDeadline(request.deadline, today)
    if (!filters.due.some((due) => matchesDue(due, days))) return false
  }
  return matchesSentFilter(request, filters)
}

/**
 * Ile wierszy zostanie po włączeniu „Bez rekrutera” przy POZOSTAŁYCH filtrach
 * bez zmian — liczba na przełączniku ma się zgadzać z tym, co pokaże tabela.
 */
export function unstaffedCount(
  board: Pick<RequestBoard, "requests">,
  filters: BoardFilters,
  today: string,
): number {
  const withToggle: BoardFilters = { ...filters, nobody: "1" }
  return board.requests.filter((r) => matchesFilters(r, withToggle, today)).length
}

/** W grupie: szukane od najbliższego terminu, champion na dole. */
export function orderRequests(rows: BoardRequest[]): BoardRequest[] {
  return [...rows].sort((a, b) => {
    if (a.champion !== b.champion) return a.champion ? 1 : -1
    const da = a.deadline ?? "9999-12-31"
    const db = b.deadline ?? "9999-12-31"
    if (da !== db) return da < db ? -1 : 1
    return a.job_id - b.job_id
  })
}

export interface ShownGroup extends BoardGroup {
  rows: BoardRequest[]
  shownLabel: string
  detail: string
}

export function groupRequests(
  board: RequestBoard,
  filters: BoardFilters,
  today: string,
): { groups: ShownGroup[]; shown: number; total: number } {
  let shown = 0
  const groups: ShownGroup[] = []
  for (const group of board.groups) {
    const all = board.requests.filter((r) =>
      group.category_id === null
        ? !board.groups.some((g) => g.category_id !== null && g.category_id === r.category_id)
        : r.category_id === group.category_id,
    )
    const rows = orderRequests(all.filter((r) => matchesFilters(r, filters, today)))
    shown += rows.length
    if (rows.length === 0) continue
    groups.push({
      ...group,
      rows,
      shownLabel:
        rows.length === all.length
          ? `${all.length} ${requestWord(all.length)}`
          : // „1 z 3 requestów” — po „z” zawsze dopełniacz liczby mnogiej.
            `${rows.length} z ${all.length} requestów`,
      detail: group.champion
        ? `szukamy w ${group.searching}, z championem ${group.champion}`
        : "szukamy we wszystkich",
    })
  }
  return { groups, shown, total: board.requests.length }
}

export function requestWord(n: number): string {
  return pluralPl(n, "request", "requesty", "requestów")
}

export function clientOptions(board: RequestBoard): string[] {
  return [
    ...new Set(board.requests.map((r) => r.client_name).filter(Boolean) as string[]),
  ].sort((a, b) => a.localeCompare(b, "pl"))
}

export function peopleOptions(board: RequestBoard): { id: string; name: string }[] {
  return board.load
    .map((p) => ({ id: String(p.user_id), name: p.name }))
    .sort((a, b) => a.name.localeCompare(b.name, "pl"))
}

/**
 * Delivery Leadzi requestów z pulpitu. `hasNone` = jest request bez Delivery
 * Leada — filtr dostaje wtedy pozycję „Bez Delivery Leada”, inaczej taki
 * request dałoby się znaleźć tylko przez przewijanie.
 */
export function leadOptions(board: Pick<RequestBoard, "requests">): {
  options: { id: string; name: string }[]
  hasNone: boolean
} {
  const byId = new Map<number, string>()
  let hasNone = false
  for (const request of board.requests) {
    if (request.delivery_lead) byId.set(request.delivery_lead.id, request.delivery_lead.name)
    else hasNone = true
  }
  return {
    options: [...byId]
      .map(([id, name]) => ({ id: String(id), name }))
      .sort((a, b) => a.name.localeCompare(b.name, "pl")),
    hasNone,
  }
}

// ── Obłożenie ───────────────────────────────────────────────────────────────
//
// Obłożenie liczy tylko rekrutacje P1 (prośba Head of Recruitment, decyzja
// Artura 14.10.2026): `count` i `proposed` z serwera są już P1, a rekrutacje
// bez priorytetu i „Przyjmujemy” przychodzą osobno jako `outside_p1`.

/** „1 rekrutacja P1”, „3 rekrutacje P1”, „5 rekrutacji P1”. */
export function p1Word(n: number): string {
  return pluralPl(n, "rekrutacja P1", "rekrutacje P1", "rekrutacji P1")
}

/** Liczba przy osobie w okienkach wyboru: „3 P1”. */
export function p1LoadLabel(count: number): string {
  return `${count} P1`
}

/**
 * Skala paska obłożenia: najbardziej obłożona osoba na liście ma pełny pasek
 * (propozycje się doliczają). Do 14.10.2026 stała 5 — przy obłożeniu ze
 * wszystkich priorytetów 13 z 15 osób miało pełny pasek.
 */
export function loadBarScale(load: readonly LoadPerson[]): number {
  return Math.max(1, ...load.map((person) => person.count + (person.proposed ?? 0)))
}

/** Lista rekrutacji osoby spoza P1 — te, które nie liczą się do obłożenia. */
export function outsideP1Href(userId: number): string {
  const query = encodeJobsListUrl({
    scope: "open",
    defaultScope: "open",
    keepScope: true,
    deadline: "any",
    sort: defaultSortForScope("open"),
    stages: ["searching"],
    workedBy: [userId],
    priorityLevels: ["p2", "accepting"],
  })
  return `/jobs?${query}`
}

/** Od najbardziej obłożonej osoby; liczą się requesty w pracy, nie propozycje. */
export function orderLoad(load: readonly LoadPerson[]): LoadPerson[] {
  return [...load].sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "pl"),
  )
}

/** Osoba z katalogu `/api/users` — tyle, ile potrzeba listom wyboru. */
export interface DirectoryPerson {
  id: number
  name: string
  role?: string | null
  roles?: readonly string[] | null
  is_active?: boolean | null
}

export interface RecruiterPickOption {
  user_id: number
  name: string
  /**
   * Requesty, nad którymi osoba pracuje; `null` = nie ma jej w obłożeniu
   * pulpitu (poza pulą automatu albo obłożenie się nie wczytało).
   */
  count: number | null
  /** Propozycje automatu czekające na akceptację. */
  proposed: number
  leave_until: string | null
}

/**
 * Lista wyboru w kolumnie „Rekruter” listy rekrutacji: osoby z rolą
 * rekrutera (lustro `_OWNERSHIP_ELIGIBLE_ROLES`) bez tych, które już
 * pracują, z obłożeniem z pulpitu. Kolejność jak „Zmień” przy propozycji
 * automatu: od najmniej obłożonej, osoby na urlopie na końcu; za nimi,
 * alfabetycznie, osoby spoza obłożenia — ich liczby nie znamy.
 */
export function recruiterPickOptions(
  directory: readonly DirectoryPerson[],
  load: readonly LoadPerson[] | null,
  excludeIds: readonly number[],
  query: string,
): RecruiterPickOption[] {
  const loadById = new Map((load ?? []).map((person) => [person.user_id, person]))
  const excluded = new Set(excludeIds)
  const needle = fold(query.trim())
  return directory
    .filter(
      (person) =>
        person.is_active !== false &&
        !excluded.has(person.id) &&
        hasRecruiterRole(person) &&
        (!needle || fold(person.name).includes(needle)),
    )
    .map((person) => {
      const loaded = loadById.get(person.id)
      return {
        user_id: person.id,
        name: person.name,
        count: loaded ? loaded.count : null,
        proposed: loaded?.proposed ?? 0,
        leave_until: loaded?.leave_until ?? null,
      }
    })
    .sort((a, b) => {
      if ((a.count === null) !== (b.count === null)) return a.count === null ? 1 : -1
      if (Boolean(a.leave_until) !== Boolean(b.leave_until)) return a.leave_until ? 1 : -1
      return (a.count ?? 0) - (b.count ?? 0) || a.name.localeCompare(b.name, "pl")
    })
}

/**
 * Liczba przy osobie: „2” albo „2 + 1” (rekrutacje P1 w pracy + propozycje
 * czekające na akceptację) oraz to samo słowami — dla czytnika ekranu
 * i podpowiedzi.
 */
export function loadSummary(person: Pick<LoadPerson, "count" | "proposed">): {
  label: string
  spoken: string
} {
  const proposed = person.proposed ?? 0
  const working = `${person.count} ${p1Word(person.count)}`
  if (proposed <= 0) return { label: String(person.count), spoken: working }
  return {
    label: `${person.count} + ${proposed}`,
    spoken: `${working} · ${proposed} ${pluralPl(proposed, "propozycja", "propozycje", "propozycji")} do akceptacji`,
  }
}
