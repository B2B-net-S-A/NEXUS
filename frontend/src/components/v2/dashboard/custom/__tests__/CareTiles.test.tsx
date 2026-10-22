/**
 * Kafelki opieki (22.10.2026): „Moja opieka” liczy karty tablicy po terminie
 * i do piątku, „Zagrożeni konsultanci” — wiersze ze zdrowiem „Ryzyko”.
 * Awaria to blok błędu, nigdy „0”; zamknięty moduł opieki chowa kafelki
 * w katalogu (`hrTileGate`). Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

let routes: Record<string, unknown> = {}

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = {
    get: async (url: string) => {
      const key = Object.keys(routes).find((route) => url === route || url.startsWith(route))
      if (key === undefined) {
        throw Object.assign(new Error("boom"), { response: { status: 500 } })
      }
      return { data: routes[key] }
    },
  }
  return { ...actual, api, default: api }
})

import type { CareBoard, CareBoardCard } from "@/lib/api/care-board"
import type { ConsultantRow } from "@/lib/api/care"
import type { HrConfig, HrModuleKey } from "@/lib/api/hr"
import { HR_TILE_TYPES, hrTileGate } from "@/lib/dashboard-tiles/catalog"

import type { CaseCard } from "@/lib/api/admin-cases"

import { CareAtRiskTile, CareMineTile, atRiskRows, careMineCards, careMineRows } from "../CareTiles"

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function card(key: string, due: string | null, overdue: number): CareBoardCard {
  return {
    key,
    kind: "contact",
    column: "new",
    title: `Rozmowa ${key}`,
    subtitle: null,
    reason_label: null,
    due_on: due,
    overdue_days: overdue,
    scheduled_at: null,
    retry_on: null,
    note_excerpt: null,
    contract_id: null,
    client_id: 1,
    client_name: "Bank Przykładowy",
    owner_user_id: 1,
    owner_name: "Kamil Testowy",
    health: null,
  }
}

const BOARD: CareBoard = {
  today: "2026-10-22",
  week_end: "2026-10-23",
  cards: [
    card("a", "2026-10-20", 2),
    card("b", "2026-10-23", 0),
    card("c", "2026-10-30", 0),
    card("d", "2026-10-15", 7),
  ],
  done: { this_week: 0, recent: [] },
}

function row(id: number, name: string, level: "ok" | "watch" | "risk" | null): ConsultantRow {
  return {
    contract_id: id,
    candidate_name: name,
    client_name: "Bank Przykładowy",
    health: level ? { level, label: level, reasons: level === "risk" ? ["chce zmiany projektu"] : [] } : null,
  } as unknown as ConsultantRow
}

beforeEach(() => {
  routes = {}
})

describe("careMineCards", () => {
  it("po terminie (najstarszy pierwszy) i do piątku; dalsze terminy poza kafelkiem", () => {
    const { overdue, thisWeek } = careMineCards(BOARD)
    expect(overdue.map((c) => c.key)).toEqual(["d", "a"])
    expect(thisWeek.map((c) => c.key)).toEqual(["b"])
  })
})

function caseCard(id: number, due: string | null, overdue: boolean, status: CaseCard["status"] = "new"): CaseCard {
  return {
    id,
    title: `Sprawa ${id}`,
    area: "administration",
    priority: "P2",
    status,
    due_on: due,
    follow_up_on: null,
    overdue,
    assignee: { id: 1, name: "Kamil Testowy" },
    subject_user: null,
    contract: null,
    source: "mail",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-20T08:00:00Z",
    updated_at: "2026-10-20T08:00:00Z",
    closed_at: null,
  }
}

describe("careMineRows", () => {
  it("sprawy przypisane do mnie po terminie i do piątku dochodzą do kolejki (S2)", () => {
    const { overdue, thisWeek } = careMineRows(BOARD, [
      caseCard(7, "2026-10-18", true),
      caseCard(8, "2026-10-23", false),
      caseCard(9, "2026-10-29", false),
      caseCard(10, "2026-10-19", true, "done"),
    ])
    expect(overdue.map((r) => r.key)).toEqual(["d", "case:7", "a"])
    expect(thisWeek.map((r) => r.key)).toEqual(["b", "case:8"])
    const late = overdue.find((r) => r.key === "case:7")!
    expect(late.href).toBe("/people/cases/7")
    expect(late.sub).toBe("Sprawa · 4 dni po terminie")
  })
})

describe("atRiskRows", () => {
  it("tylko „Ryzyko”; serwer bez pola zdrowia = nikt", () => {
    const rows = [row(1, "Zofia Z", "risk"), row(2, "Adam A", "watch"), row(3, "Bartek B", "risk"), row(4, "C", null)]
    expect(atRiskRows(rows).map((r) => r.contract_id)).toEqual([3, 1])
  })
})

describe("CareMineTile / CareAtRiskTile", () => {
  it("„Moja opieka” mówi, ile po terminie i do piątku", async () => {
    routes = { "/api/care/board": BOARD }
    wrap(<CareMineTile />)
    expect(await screen.findByText("2 po terminie")).toBeInTheDocument()
    expect(screen.getByText(/1 do piątku/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Opieka → Do zrobienia" })).toHaveAttribute("href", "/care")
  })

  it("„Moja opieka” liczy też moje sprawy; bez dostępu do Spraw — same karty", async () => {
    routes = {
      "/api/care/board": BOARD,
      "/api/cases": { items: [caseCard(7, "2026-10-18", true)], total: 1, truncated: false, done_this_month: 0, can_manage: false },
    }
    wrap(<CareMineTile />)
    expect(await screen.findByText("3 po terminie")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Sprawa 7" })).toHaveAttribute("href", "/people/cases/7")
  })

  it("awaria spraw (500) to zdanie pod listą, karty opieki zostają", async () => {
    routes = { "/api/care/board": BOARD }
    wrap(<CareMineTile />)
    expect(await screen.findByText(/Spraw nie udało się wczytać/)).toBeInTheDocument()
    expect(screen.getByText("2 po terminie")).toBeInTheDocument()
  })

  it("awaria tablicy to blok błędu, nie „0”", async () => {
    wrap(<CareMineTile />)
    expect(await screen.findByText(/Nie udało się załadować danych/)).toBeInTheDocument()
    expect(screen.queryByText(/po terminie/)).toBeNull()
  })

  it("„Zagrożeni konsultanci” z powodem i linkiem do karty", async () => {
    routes = {
      "/api/care/consultants": {
        today: "2026-10-22",
        months: { this: { from: "", to: "" }, next: { from: "", to: "" } },
        items: [row(41, "Anna Kontraktorska", "risk"), row(42, "Michał Konsultantowy", "ok")],
        total: 2,
        feedback_visible: true,
      },
    }
    wrap(<CareAtRiskTile />)
    const link = await screen.findByRole("link", { name: "Anna Kontraktorska" })
    expect(link).toHaveAttribute("href", "/care?contract=41")
    expect(screen.getByText("Bank Przykładowy · chce zmiany projektu")).toBeInTheDocument()
    expect(screen.queryByText("Michał Konsultantowy")).toBeNull()
  })

  it("awaria listy konsultantów to blok błędu", async () => {
    wrap(<CareAtRiskTile />)
    expect(await screen.findByText(/Nie udało się załadować danych/)).toBeInTheDocument()
  })
})

describe("bramka modułu opieki", () => {
  const MODULES: HrModuleKey[] = ["people", "leave", "time", "payroll", "lifecycle", "care", "cases", "equipment"]
  const config = (care: boolean): HrConfig =>
    ({
      program: true,
      modules: Object.fromEntries(MODULES.map((k) => [k, k === "care" && care])),
      open_modules: Object.fromEntries(MODULES.map((k) => [k, k === "care" && care])),
      me: {},
    }) as unknown as HrConfig

  it("kafelki opieki są kafelkami „Ludzi” i znikają przy zamkniętym module", () => {
    expect(HR_TILE_TYPES.has("care_mine")).toBe(true)
    expect(HR_TILE_TYPES.has("care_at_risk")).toBe(true)
    expect(hrTileGate("care_mine", config(false))).toBe("hidden")
    expect(hrTileGate("care_at_risk", undefined)).toBe("hidden")
    expect(hrTileGate("care_mine", config(true))).toEqual({ ok: true })
    expect(hrTileGate("care_at_risk", config(true))).toEqual({ ok: true })
  })
})
