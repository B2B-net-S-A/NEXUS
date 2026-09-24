import { describe, expect, it } from "vitest"

import cases from "@/lib/__fixtures__/request-work-state-cases.json"
import type { BoardRequest, RequestBoard } from "@/lib/api/requestAllocation"
import {
  EMPTY_FILTERS,
  deadlineLabel,
  filtersFromParams,
  filtersToParams,
  groupRequests,
  matchesFilters,
  orderRequests,
  requestWord,
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
    req({ job_id: 1, category_id: 1, title: "DevOps Engineer", client_name: "Polkomtel", deadline: "2026-09-30" }),
    req({ job_id: 2, title: "Senior Java Developer", deadline: "2026-09-26", people: [{ user_id: 7, name: "Anna Przykładowa", role: "recruiter", proposed: false, source: "auto" }] }),
    req({ job_id: 3, title: "React Developer", sent: 3, champion: true, deadline: "2026-09-28" }),
    req({ job_id: 4, title: "Kotlin Developer", sent: 1, deadline: "2026-09-20" }),
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

  it("who matches any person on the request", () => {
    expect(
      board.requests.filter((r) => matchesFilters(r, { ...EMPTY_FILTERS, who: "7" }, TODAY)).map((r) => r.job_id),
    ).toEqual([2])
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
