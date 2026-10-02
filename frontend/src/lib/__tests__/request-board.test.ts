import { describe, expect, it } from "vitest"

import cases from "@/lib/__fixtures__/request-work-state-cases.json"
import type { BoardRequest, RequestBoard } from "@/lib/api/requestAllocation"
import {
  EMPTY_FILTERS,
  boardPeople,
  deadlineLabel,
  filtersFromParams,
  filtersToParams,
  groupRequests,
  hasActiveFilters,
  leadOptions,
  loadSummary,
  matchesFilters,
  needsRecruiter,
  orderLoad,
  orderRequests,
  pendingProposalCount,
  requestWord,
  unstaffedCount,
} from "@/lib/request-board"
import { visibleState } from "@/lib/request-work-state"

const TODAY = "2026-09-24"

function req(partial: Partial<BoardRequest> & { job_id: number }): BoardRequest {
  return {
    title: `Request ${partial.job_id}`,
    client_name: "Nordea",
    category_id: 2,
    deadline: null,
    sent: 0,
    champion: false,
    people: [],
    ...partial,
  }
}

const board: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [
    { category_id: 1, name: "Infra", slug: "infrastructure_operations", total: 1, searching: 1, champion: 0 },
    { category_id: 2, name: "Development", slug: "software_development", total: 3, searching: 2, champion: 1 },
  ],
  requests: [
    req({ job_id: 1, category_id: 1, title: "DevOps Engineer", client_name: "Polkomtel", deadline: "2026-09-30", priority_level: "p1", delivery_lead: { id: 31, name: "Gosia Delivery" } }),
    req({ job_id: 2, title: "Senior Java Developer", deadline: "2026-09-26", delivery_lead: { id: 32, name: "Adam Lider" }, people: [{ user_id: 7, name: "Anna Przykładowa", proposed: false, source: "auto" }] }),
    req({ job_id: 3, title: "React Developer", sent: 3, champion: true, deadline: "2026-09-28", priority_level: "accepting" }),
    // Sama propozycja automatu — nikt jeszcze nie pracuje.
    req({ job_id: 4, title: "Kotlin Developer", sent: 1, deadline: "2026-09-20", delivery_lead: { id: 31, name: "Gosia Delivery" }, people: [{ user_id: 8, name: "Bartek Testowy", proposed: true, source: "auto" }] }),
  ],
  load: [],
  changes: [],
}

describe("visibleState", () => {
  it.each(cases.cases)("$work_state + champion=$champion → $visible", (c) => {
    expect(visibleState(c.work_state, c.champion ? "2026-09-24T09:00:00Z" : null)).toBe(c.visible)
  })
})

describe("filters", () => {
  it("round-trip through the URL keeps unrelated params", () => {
    const base = new URLSearchParams("tab=x")
    const filters = { ...EMPTY_FILTERS, client: "Nordea", due: "late" as const, who: "7" }
    const params = filtersToParams(filters, base)
    expect(params.get("tab")).toBe("x")
    expect(filtersFromParams(params)).toEqual(filters)
  })

  it("ignores unknown due/sent values from a hand-edited URL", () => {
    const parsed = filtersFromParams(new URLSearchParams("rb_due=soon&rb_sent=9"))
    expect(parsed.due).toBe("")
    expect(parsed.sent).toBe("")
  })

  it("Delivery Lead, priorytet i „Bez rekrutera” żyją w adresie pod kluczami rb_", () => {
    const filters = { ...EMPTY_FILTERS, lead: "31", prio: "p1" as const, nobody: "1" as const }
    const params = filtersToParams(filters, new URLSearchParams())
    expect(params.toString()).toBe("rb_lead=31&rb_prio=p1&rb_nobody=1")
    expect(filtersFromParams(params)).toEqual(filters)
    expect(hasActiveFilters(filters)).toBe(true)
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false)
  })

  it("nieznany priorytet i przełącznik spoza „1” z ręcznie wpisanego adresu nic nie filtrują", () => {
    const parsed = filtersFromParams(new URLSearchParams("rb_prio=p9&rb_nobody=tak"))
    expect(parsed.prio).toBe("")
    expect(parsed.nobody).toBe("")
  })

  it("title search ignores Polish characters and case", () => {
    const row = req({ job_id: 9, title: "Specjalista ds. bezpieczeństwa" })
    expect(matchesFilters(row, { ...EMPTY_FILTERS, q: "BEZPIECZENSTWA" }, TODAY)).toBe(true)
  })

  it("deadline buckets", () => {
    const late = req({ job_id: 1, deadline: "2026-09-20" })
    const week = req({ job_id: 2, deadline: "2026-09-30" })
    const none = req({ job_id: 3 })
    const f = (due: "late" | "week" | "two" | "none") => ({ ...EMPTY_FILTERS, due })
    expect([late, week, none].filter((r) => matchesFilters(r, f("late"), TODAY)).map((r) => r.job_id)).toEqual([1])
    expect([late, week, none].filter((r) => matchesFilters(r, f("week"), TODAY)).map((r) => r.job_id)).toEqual([2])
    expect([late, week, none].filter((r) => matchesFilters(r, f("none"), TODAY)).map((r) => r.job_id)).toEqual([3])
  })

  it("sent buckets keep champions apart", () => {
    const f = (sent: "0" | "12" | "3" | "champ") => ({ ...EMPTY_FILTERS, sent })
    const ids = (sent: "0" | "12" | "3" | "champ") =>
      board.requests.filter((r) => matchesFilters(r, f(sent), TODAY)).map((r) => r.job_id)
    expect(ids("0")).toEqual([1, 2])
    expect(ids("12")).toEqual([4])
    expect(ids("3")).toEqual([])
    expect(ids("champ")).toEqual([3])
  })

  const idsFor = (filters: Partial<typeof EMPTY_FILTERS>) =>
    board.requests
      .filter((r) => matchesFilters(r, { ...EMPTY_FILTERS, ...filters }, TODAY))
      .map((r) => r.job_id)

  it("„Rekruter” liczy osobę, która pracuje — propozycja automatu to za mało", () => {
    expect(idsFor({ who: "7" })).toEqual([2])
    // Bartek ma przy requeście 4 tylko propozycję.
    expect(idsFor({ who: "8" })).toEqual([])
  })

  it("Delivery Lead: po id, a `none` = requesty bez Delivery Leada", () => {
    expect(idsFor({ lead: "31" })).toEqual([1, 4])
    expect(idsFor({ lead: "32" })).toEqual([2])
    expect(idsFor({ lead: "none" })).toEqual([3])
    expect(leadOptions(board)).toEqual({
      options: [
        { id: "32", name: "Adam Lider" },
        { id: "31", name: "Gosia Delivery" },
      ],
      hasNone: true,
    })
    expect(leadOptions({ requests: board.requests.filter((r) => r.delivery_lead) }).hasNone).toBe(false)
  })

  it("priorytet: brak pola z serwera to P2 (stan domyślny)", () => {
    expect(idsFor({ prio: "p1" })).toEqual([1])
    expect(idsFor({ prio: "accepting" })).toEqual([3])
    expect(idsFor({ prio: "p2" })).toEqual([2, 4])
  })

  it("„Bez rekrutera”: nikt nie pracuje — także przy samej propozycji; champion się nie liczy", () => {
    expect(board.requests.filter(needsRecruiter).map((r) => r.job_id)).toEqual([1, 4])
    expect(idsFor({ nobody: "1" })).toEqual([1, 4])
    // Liczba na przełączniku = tyle wierszy zostanie przy pozostałych filtrach.
    expect(unstaffedCount(board, EMPTY_FILTERS, TODAY)).toBe(2)
    expect(unstaffedCount(board, { ...EMPTY_FILTERS, lead: "32" }, TODAY)).toBe(0)
    expect(unstaffedCount(board, { ...EMPTY_FILTERS, cat: "1", nobody: "1" }, TODAY)).toBe(1)
  })
})

describe("kto jest przy requeście", () => {
  const working = { user_id: 7, name: "Anna Przykładowa", proposed: false, source: "manual" as const }
  const proposal = { user_id: 8, name: "Bartek Testowy", proposed: true, source: "auto" as const }

  it("propozycję pokazujemy tylko wtedy, gdy nikt nie pracuje", () => {
    expect(boardPeople({ people: [proposal] })).toEqual([proposal])
    // Ktoś już pracuje — propozycja jest nieaktualna (serwer odmówiłby akceptacji).
    expect(boardPeople({ people: [working, proposal] })).toEqual([working])
    expect(boardPeople({ people: [] })).toEqual([])
    // Request z championem wypada z puli automatu — propozycja jest nieaktualna
    // i „Akceptuj” skończyłoby się odmową.
    expect(boardPeople({ people: [proposal], champion: true })).toEqual([])
    expect(boardPeople({ people: [proposal], champion: false })).toEqual([proposal])
  })

  it("liczy propozycje czekające na decyzję", () => {
    expect(pendingProposalCount(board)).toBe(1)
    expect(
      pendingProposalCount({ requests: [req({ job_id: 9, people: [working, proposal] })] }),
    ).toBe(0)
  })
})

describe("obłożenie", () => {
  const person = (user_id: number, name: string, count: number, proposed?: number) => ({
    user_id,
    name,
    count,
    proposed,
    leave_until: null,
    requests: [],
  })

  it("kolejność po requestach w pracy; propozycje jej nie zmieniają", () => {
    const load = [person(1, "Zofia", 1, 3), person(2, "Adam", 2), person(3, "Bogna", 1)]
    expect(orderLoad(load).map((p) => p.name)).toEqual(["Adam", "Bogna", "Zofia"])
    // Wejście zostaje nietknięte.
    expect(load.map((p) => p.name)).toEqual(["Zofia", "Adam", "Bogna"])
  })

  it("„2 + 1” i to samo słowami", () => {
    expect(loadSummary(person(1, "A", 2, 1))).toEqual({
      label: "2 + 1",
      spoken: "2 requesty · 1 propozycja do akceptacji",
    })
    expect(loadSummary(person(1, "A", 0, 2))).toEqual({
      label: "0 + 2",
      spoken: "0 requestów · 2 propozycje do akceptacji",
    })
    expect(loadSummary(person(1, "A", 5, 5)).spoken).toBe("5 requestów · 5 propozycji do akceptacji")
    // Starszy backend nie oddaje `proposed` — sama liczba.
    expect(loadSummary(person(1, "A", 1))).toEqual({ label: "1", spoken: "1 request" })
    expect(loadSummary(person(1, "A", 3, 0))).toEqual({ label: "3", spoken: "3 requesty" })
  })
})

describe("grouping", () => {
  it("champion goes to the bottom of its group, the rest by deadline", () => {
    expect(orderRequests(board.requests.filter((r) => r.category_id === 2)).map((r) => r.job_id)).toEqual([4, 2, 3])
  })

  it("filtered group says N z M and empty groups disappear", () => {
    const { groups, shown, total } = groupRequests(board, { ...EMPTY_FILTERS, q: "java" }, TODAY)
    expect(total).toBe(4)
    expect(shown).toBe(1)
    expect(groups.map((g) => [g.name, g.shownLabel])).toEqual([["Development", "1 z 3 requestów"]])
  })

  it("polish plural for requests", () => {
    expect([1, 2, 5, 12, 22, 25].map(requestWord)).toEqual([
      "request",
      "requesty",
      "requestów",
      "requestów",
      "requesty",
      "requestów",
    ])
  })

  it("deadline label speaks Polish", () => {
    expect(deadlineLabel("2026-09-23", TODAY)).toBe("po terminie 1 dzień")
    expect(deadlineLabel("2026-09-25", TODAY)).toBe("jutro")
    expect(deadlineLabel(null, TODAY)).toBe("brak terminu")
  })
})
