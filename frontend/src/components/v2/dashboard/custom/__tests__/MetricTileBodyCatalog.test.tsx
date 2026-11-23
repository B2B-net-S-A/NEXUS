/**
 * Kafelek metryki pyta katalog, zanim policzy (23.11.2026).
 *
 * Delivery Lead bez klientów w portfelu dostawał na pulpicie 3 × 403
 * `metric_scope_denied` (kontrakty, zamówienia, kwoty). Reguła serwera zostaje
 * („odmowa, nie zero”, decyzja Artura 26.09.2026) — katalog mówi o niej z góry,
 * więc kafelek pokazuje zdanie z katalogu i nie woła `/evaluate`.
 */
import * as React from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
  },
}))

import { MetricTileBody } from "../MetricTileBody"
import type { MetricDefinition } from "@/lib/api/userDashboard"

const EMPTY_PORTFOLIO =
  "Nie masz przypisanych klientów — kontrakty i zamówienia liczysz tylko dla swojego portfela."

function catalog(contractsAvailable: boolean) {
  return {
    sources: [
      {
        key: "contracts",
        label: "Kontrakty",
        available: contractsAvailable,
        reason: contractsAvailable ? null : EMPTY_PORTFOLIO,
        measures: [],
        group_by: [],
        filters: [],
        supports_author: false,
      },
    ],
    authors: ["me"],
    stages: [],
    periods: [],
  }
}

const METRIC = { source: "contracts", measure: "active_now" } as MetricDefinition

function renderTile() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MetricTileBody metric={METRIC} type="metric_number" poll={false} />
    </QueryClientProvider>,
  )
}

describe("MetricTileBody — źródło niedostępne w katalogu", () => {
  beforeEach(() => {
    mocks.get.mockReset()
    mocks.post.mockReset()
  })

  it("pusty portfel: zdanie z katalogu i żadnego liczenia", async () => {
    mocks.get.mockResolvedValue({ data: catalog(false) })
    renderTile()
    expect(await screen.findByText(EMPTY_PORTFOLIO)).toBeTruthy()
    expect(screen.getByText("Brak dostępu")).toBeTruthy()
    expect(mocks.post).not.toHaveBeenCalled()
  })

  it("źródło dostępne: kafelek liczy jak dotąd", async () => {
    mocks.get.mockResolvedValue({ data: catalog(true) })
    mocks.post.mockResolvedValue({
      data: {
        value: 12,
        previous_value: null,
        series: [],
        unit: "count",
        scope_applied: "portfolio",
        notes: [],
        period: { key: "now", label: "Teraz", start: "", end: "" },
      },
    })
    renderTile()
    expect(await screen.findByText("12")).toBeTruthy()
    expect(mocks.post).toHaveBeenCalledWith("/api/dashboard-metrics/evaluate", METRIC)
  })

  it("awaria katalogu nie blokuje kafelka — decyduje serwer przy liczeniu", async () => {
    mocks.get.mockRejectedValue(new Error("network"))
    mocks.post.mockResolvedValue({
      data: {
        value: 3,
        previous_value: null,
        series: [],
        unit: "count",
        scope_applied: "all",
        notes: [],
        period: { key: "now", label: "Teraz", start: "", end: "" },
      },
    })
    renderTile()
    await waitFor(() => expect(mocks.post).toHaveBeenCalled())
    expect(await screen.findByText("3")).toBeTruthy()
  })
})
