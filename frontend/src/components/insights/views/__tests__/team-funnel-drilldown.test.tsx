/**
 * Lejek zespołu otwiera listę osób za liczbą (prośba Artura, decyzje 25.10.2026).
 *
 * Reguły pod ochroną:
 *
 * 1. **Liczba jest przyciskiem tylko dla ról z wglądem w zespół** — reszta
 *    (np. Rada nadzorcza w widoku Firma) widzi same liczby, bez nazwisk.
 * 2. **Klik zapisuje `?kto=…&osoba=zespol`** — „Wstecz” zamyka listę.
 * 3. **Otwarta lista pyta o cały zespół** w dniach okresu z lejka.
 * 4. **Pary bez osoby z zasługą i różnica z klikniętą liczbą są powiedziane**,
 *    a nie ukryte (staging 25.10.2026: rekomendacje 447 + 1 = 448).
 */
import * as React from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  push: vi.fn(),
  params: new URLSearchParams(),
}))

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => mocks.params,
}))
vi.mock("@/lib/url-selection", () => ({
  useUrlWriter: () => ({ pushUrl: mocks.push, replaceUrl: vi.fn() }),
}))

import { TeamFunnelPanel } from "../team/TeamFunnelPanel"
import { useAuthStore } from "@/store/auth"
import type { RecruitmentFunnelResponse } from "@/lib/insights-api"

function stage(stageKey: string, label: string, count: number) {
  return { stage: stageKey, label, count, mapped_from_traffit: true, share_pct: null, counted_from: null }
}

const FUNNEL = {
  period: {
    kind: "month",
    start: "2026-10-01T00:00:00+02:00",
    end: "2026-11-01T00:00:00+01:00",
    timezone: "Europe/Warsaw",
  },
  stages: [
    stage("verified", "Zweryfikowany", 506),
    stage("cv_sent", "CV wysłane", 448),
    stage("client_interview", "Rozmowa z klientem", 73),
    stage("acceptance", "Akceptacja", 16),
    stage("hired", "Zatrudniony", 0),
  ],
  conversions: [],
  coverage: {
    stage_moves_total: 0,
    stage_moves_manual: 0,
    manual_pct: null,
    unattributed_moves: 0,
    stages_not_mapped_from_traffit: [],
  },
} as unknown as RecruitmentFunnelResponse

function detail(params: Record<string, unknown>) {
  const unattributed = params.scope === "unattributed"
  const total = unattributed ? 1 : 447
  return {
    generated_at: "2026-10-25T10:00:00Z",
    metric: params.metric,
    window: "range",
    page: 1,
    page_size: Number(params.page_size),
    total,
    items: [],
    scope: unattributed ? "unattributed" : "team",
    period_total: total,
    history_total: 0,
    people: 0,
    states: {},
  }
}

function renderPanel(canOpenList: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TeamFunnelPanel
        funnel={FUNNEL}
        previous={undefined}
        previousLabel={undefined}
        inFlight={undefined}
        period={{ period: "month", offset: 0 }}
        canOpenList={canOpenList}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mocks.get.mockReset()
  mocks.push.mockReset()
  mocks.params = new URLSearchParams()
  mocks.get.mockImplementation((_url: string, config: { params: Record<string, unknown> }) =>
    Promise.resolve({ data: detail(config.params) }),
  )
  useAuthStore.setState({
    user: { id: 289, name: "HoR", role: "head_of_recruitment", roles: ["head_of_recruitment"] },
  } as never)
})

describe("TeamFunnelPanel — lista za liczbą", () => {
  it("bez wglądu w zespół liczby są tylko do czytania", () => {
    renderPanel(false)
    expect(screen.getByText("506")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Pokaż osoby/ })).toBeNull()
  })

  it("klik w liczbę zapisuje listę zespołu w adresie; zero zostaje zwykłą liczbą", () => {
    renderPanel(true)
    fireEvent.click(screen.getByRole("button", { name: "Rekomendacje: 448. Pokaż osoby" }))
    expect(mocks.push).toHaveBeenCalledWith(expect.stringContaining("kto=rekomendacje&osoba=zespol"))
    expect(screen.queryByRole("button", { name: /Placementy: 0/ })).toBeNull()
  })

  it("otwarta lista pyta o cały zespół w dniach okresu i mówi o parach bez zasługi", async () => {
    mocks.params = new URLSearchParams("kto=rekomendacje&osoba=zespol")
    renderPanel(true)
    expect(await screen.findByText("Kto się liczy · Cały zespół")).toBeInTheDocument()
    expect(await screen.findByText(/Do tego 1 rekomendacja bez osoby z zasługą\./)).toBeInTheDocument()
    // 447 + 1 = 448 jak w lejku — bez zdania o różnicy.
    expect(screen.queryByText(/Lejek pokazuje/)).toBeNull()

    const teamCall = mocks.get.mock.calls
      .map((call) => call[1].params)
      .find((params) => params.scope === "team" && Number(params.page_size) > 1)
    expect(teamCall).toMatchObject({
      metric: "recommendation",
      window: "range",
      date_from: "2026-10-01",
      date_to: "2026-10-31",
    })

    fireEvent.click(screen.getByRole("button", { name: "Pokaż" }))
    expect(await screen.findByText("Kto się liczy · Bez osoby z zasługą")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "← Cały zespół" })).toBeInTheDocument()
  })
})
