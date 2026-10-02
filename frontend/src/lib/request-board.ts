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
import { hasRecruiter, proposedRecruiters, workingRecruiters } from "@/lib/job-team"
import { pluralPl } from "@/lib/plural-pl"
import {
  isPriorityLevel,
  priorityLevelOf,
  type PriorityLevel,
} from "@/lib/request-priority"

export type DueFilter = "" | "late" | "week" | "two" | "none"
export type SentFilter = "" | "0" | "12" | "3" | "champ"
export type PriorityFilter = "" | PriorityLevel

export interface BoardFilters {
  q: string
  client: string
  /** Id Delivery Leada albo `none` (request bez Delivery Leada). */
  lead: string
  due: DueFilter
  sent: SentFilter
  /** „Rekruter” — id osoby, która PRACUJE nad requestem (propozycja to za mało). */
  who: string
  cat: string
  prio: PriorityFilter
  /** „Bez rekrutera”: `1` = tylko requesty, przy których nikt nie pracuje. */
  nobody: "" | "1"
}

export const EMPTY_FILTERS: BoardFilters = {
  q: "",
  client: "",
  lead: "",
  due: "",
  sent: "",
  who: "",
  cat: "",
  prio: "",
  nobody: "",
}

export const DUE_OPTIONS: { value: DueFilter; label: string }[] = [
  { value: "", label: "Każdy termin" },
  { value: "late", label: "Po terminie" },
  { value: "week", label: "Do 7 dni" },
  { value: "two", label: "Do 14 dni" },
  { value: "none", label: "Bez terminu" },
]

export const SENT_OPTIONS: { value: SentFilter; label: string }[] = [
  { value: "", label: "Dowolnie" },
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
  who: "rb_who",
  cat: "rb_cat",
  prio: "rb_prio",
  nobody: "rb_nobody",
}

export function filtersFromParams(params: URLSearchParams): BoardFilters {
  const read = (key: keyof BoardFilters) => params.get(URL_KEYS[key]) ?? ""
  const due = read("due") as DueFilter
  const sent = read("sent") as SentFilter
  const prio = read("prio")
  return {
    q: read("q"),
    client: read("client"),
    lead: read("lead"),
    due: DUE_OPTIONS.some((o) => o.value === due) ? due : "",
    sent: SENT_OPTIONS.some((o) => o.value === sent) ? sent : "",
    who: read("who"),
    cat: read("cat"),
    prio: isPriorityLevel(prio) ? prio : "",
    nobody: read("nobody") === "1" ? "1" : "",
  }
}

export function filtersToParams(
  filters: BoardFilters,
  base: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of Object.keys(URL_KEYS) as (keyof BoardFilters)[]) {
    const value = filters[key]
    if (value) next.set(URL_KEYS[key], value)
    else next.delete(URL_KEYS[key])
  }
  return next
}

export function hasActiveFilters(filters: BoardFilters): boolean {
  return Object.values(filters).some(Boolean)
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
 * Chip z „Akceptuj” kończyłby się wtedy samym błędem.
 */
export function boardPeople(
  request: Pick<BoardRequest, "people"> & Partial<Pick<BoardRequest, "champion">>,
): BoardPerson[] {
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

export function matchesFilters(
  request: BoardRequest,
  filters: BoardFilters,
  today: string,
): boolean {
  if (filters.q && !fold(request.title).includes(fold(filters.q.trim()))) return false
  if (filters.client && request.client_name !== filters.client) return false
  if (filters.cat) {
    const cat = filters.cat === "none" ? null : Number(filters.cat)
    if ((request.category_id ?? null) !== cat) return false
  }
  if (filters.lead) {
    const lead = filters.lead === "none" ? null : Number(filters.lead)
    if ((request.delivery_lead?.id ?? null) !== lead) return false
  }
  if (filters.prio && priorityLevelOf(request) !== filters.prio) return false
  // „Rekruter” znaczy to samo co na liście rekrutacji: osoba pracuje nad
  // requestem. Propozycja automatu przed akceptacją nikogo nie przypisuje.
  if (
    filters.who &&
    !workingRecruiters(request.people).some((p) => String(p.user_id) === filters.who)
  )
    return false
  if (filters.nobody && !needsRecruiter(request)) return false
  const days = daysToDeadline(request.deadline, today)
  if (filters.due === "late" && !(days !== null && days < 0)) return false
  if (filters.due === "week" && !(days !== null && days >= 0 && days <= 7)) return false
  if (filters.due === "two" && !(days !== null && days >= 0 && days <= 14)) return false
  if (filters.due === "none" && days !== null) return false
  if (filters.sent === "0" && !(request.sent === 0 && !request.champion)) return false
  if (filters.sent === "12" && !(request.sent >= 1 && request.sent <= 2 && !request.champion))
    return false
  if (filters.sent === "3" && !(request.sent >= 3 && !request.champion)) return false
  if (filters.sent === "champ" && !request.champion) return false
  return true
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

/** Od najbardziej obłożonej osoby; liczą się requesty w pracy, nie propozycje. */
export function orderLoad(load: readonly LoadPerson[]): LoadPerson[] {
  return [...load].sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "pl"),
  )
}

/**
 * Liczba przy osobie: „2” albo „2 + 1” (requesty w pracy + propozycje czekające
 * na akceptację) oraz to samo słowami — dla czytnika ekranu i podpowiedzi.
 */
export function loadSummary(person: Pick<LoadPerson, "count" | "proposed">): {
  label: string
  spoken: string
} {
  const proposed = person.proposed ?? 0
  const working = `${person.count} ${requestWord(person.count)}`
  if (proposed <= 0) return { label: String(person.count), spoken: working }
  return {
    label: `${person.count} + ${proposed}`,
    spoken: `${working} · ${proposed} ${pluralPl(proposed, "propozycja", "propozycje", "propozycji")} do akceptacji`,
  }
}
