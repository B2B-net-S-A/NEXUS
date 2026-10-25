/**
 * Kafelek „Wyniki zespołu” (prośba Head of Recruitment, decyzje 25.10.2026).
 *
 * Reguły pod ochroną:
 *
 * 1. **Okres na kafelku** — liczby i lista idą z trasy listy „Kto się liczy”
 *    z zakresem zespołu i dniami od–do wybranego okresu.
 * 2. **Klik w liczbę rozwija listę osób** (zwarte wiersze) i zwija ją drugi klik.
 * 3. **Akceptacje sprzed 12.10.2026 to „—”**, nie zero — wtedy ich nie liczono.
 * 4. **Okres pamięta przeglądarka per kafelek**; zepsuty wpis = okres domyślny.
 */
import * as React from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}))

import { TeamResultsTile, parseStoredPeriod, presetRange } from "../TeamResultsTile"
import { useAuthStore } from "@/store/auth"

const TOTALS: Record<string, number> = {
  verification: 506,
  recommendation: 447,
  acceptance: 16,
  placement: 15,
}

function detailResponse(params: Record<string, unknown>) {
  const metric = String(params.metric)
  const listed = Number(params.page_size) === 1 ? [] : [
    {
      candidate: { id: 7, name: "Kandydat Testowy", href: "/candidates/7" },
      job: { id: 3, title: "Analityk", client_name: "Klient Testowy", href: "/jobs/3" },
      credited_user: { id: 2, name: "Rekruterka Testowa", role: "recruiter" },
      reached_at: "2026-10-22T10:51:00+02:00",
      state: "hired",
    },
  ]
  return {
    generated_at: "2026-10-25T10:00:00Z",
    metric,
    window: "range",
    page: 1,
    page_size: Number(params.page_size),
    total: TOTALS[metric],
    items: listed,
    scope: "team",
    period_total: TOTALS[metric],
    history_total: 0,
    people: 1,
    states: {},
  }
}

function renderTile(tileId = "tile-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TeamResultsTile tileId={tileId} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mocks.get.mockReset()
  mocks.get.mockImplementation((_url: string, config: { params: Record<string, unknown> }) =>
    Promise.resolve({ data: detailResponse(config.params) }),
  )
  window.localStorage.clear()
  useAuthStore.setState({
    user: { id: 289, name: "HoR", role: "head_of_recruitment", roles: ["head_of_recruitment"] },
  } as never)
})

describe("TeamResultsTile", () => {
  it("liczy cztery etapy zespołu w okresie i rozwija listę osób po kliknięciu", async () => {
    renderTile()
    const placements = await screen.findByRole("button", { name: "Placementy: 15. Pokaż osoby" })
    expect(screen.getByRole("button", { name: "Weryfikacje: 506. Pokaż osoby" })).toBeInTheDocument()

    const call = mocks.get.mock.calls[0][1].params
    expect(call).toMatchObject({ scope: "team", window: "range" })
    expect(call.date_from).toMatch(/^\d{4}-\d{2}-01$/)

    fireEvent.click(placements)
    const list = await screen.findByTestId("who-counts-list")
    expect(await within(list).findByText("Kandydat Testowy")).toBeInTheDocument()
    expect(within(list).getByText(/liczy się: Rekruterka Testowa/)).toBeInTheDocument()
    // Zwarte wiersze, nie szeroka tabela.
    expect(within(list).queryByRole("table")).toBeNull()

    fireEvent.click(placements)
    expect(screen.queryByTestId("who-counts-list")).toBeNull()
  })

  it("akceptacje okresu sprzed 12.10.2026 to „—” bez listy", async () => {
    window.localStorage.setItem(
      "nexus:team-results:tile-1",
      JSON.stringify({ preset: "custom", custom: { start: "2026-09-01", end: "2026-09-30" } }),
    )
    renderTile()
    const acceptance = await screen.findByRole("button", { name: "Akceptacje: —. Pokaż osoby" })
    expect(acceptance).toBeDisabled()
    expect(within(acceptance).getByText("liczone od 12.10")).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Placementy: 15. Pokaż osoby" })).toBeInTheDocument(),
    )
  })

  it("zapamiętuje wybrany okres per kafelek", async () => {
    renderTile("tile-9")
    fireEvent.click(await screen.findByRole("button", { name: "Kwartał" }))
    await waitFor(() =>
      expect(JSON.parse(window.localStorage.getItem("nexus:team-results:tile-9") ?? "{}").preset).toBe(
        "this_quarter",
      ),
    )
  })
})

describe("presetRange i parseStoredPeriod", () => {
  it("okresy liczone od dnia kalendarza firmy", () => {
    expect(presetRange("this_month", "2026-10-25")).toEqual({ start: "2026-10-01", end: "2026-10-25" })
    expect(presetRange("last_month", "2026-10-25")).toEqual({ start: "2026-09-01", end: "2026-09-30" })
    // 25.10.2026 to niedziela — tydzień od poniedziałku 19.10.
    expect(presetRange("this_week", "2026-10-25")).toEqual({ start: "2026-10-19", end: "2026-10-25" })
    expect(presetRange("last_week", "2026-10-25")).toEqual({ start: "2026-10-12", end: "2026-10-18" })
    expect(presetRange("this_quarter", "2026-11-03")).toEqual({ start: "2026-10-01", end: "2026-11-03" })
  })

  it("zepsuty albo obcy wpis w przeglądarce = okres domyślny", () => {
    expect(parseStoredPeriod(null)).toBeNull()
    expect(parseStoredPeriod("{nie json")).toBeNull()
    expect(parseStoredPeriod(JSON.stringify({ preset: "rok", custom: { start: "2026-01-01", end: "2026-01-02" } }))).toBeNull()
    expect(parseStoredPeriod(JSON.stringify({ preset: "custom", custom: { start: "2026-13-01", end: "2026-01-02" } }))).toBeNull()
    expect(
      parseStoredPeriod(JSON.stringify({ preset: "last_month", custom: { start: "2026-09-01", end: "2026-09-30" } })),
    ).toEqual({ preset: "last_month", custom: { start: "2026-09-01", end: "2026-09-30" } })
  })
})
