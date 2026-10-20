import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  closingMargin,
  rateText,
  type ClosingCandidateRow,
  type ClosingCandidatesResponse,
} from "@/lib/closing-candidates"

import { ClosingCandidatesTile } from "../ClosingCandidatesTile"

// Brak odpowiedzi = awaria (500): kafelek nie może jej pokazać jak pustej listy.
let response: ClosingCandidatesResponse | null = null

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = {
    get: async () => {
      if (response === null) throw Object.assign(new Error("boom"), { response: { status: 500 } })
      return { data: response }
    },
  }
  return { ...actual, api, default: api }
})

function row(over: Partial<ClosingCandidateRow> = {}): ClosingCandidateRow {
  return {
    candidate_id: 1,
    candidate_name: "Jan Przykładowy",
    job_id: 10,
    job_title: "Senior Java Developer",
    job_working_title: null,
    client_name: "Bank Północny",
    step: "accepted",
    since: new Date().toISOString(),
    delivery_lead_name: "Anna Nowak",
    recruiter_name: "Piotr Zieliński",
    candidate_rate_value: "120.00",
    candidate_rate_unit: "hourly",
    candidate_rate_currency: "PLN",
    client_rate_value: "1200.00",
    client_rate_unit: "daily",
    client_rate_currency: "PLN",
    ...over,
  }
}

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe("closingMargin i rateText", () => {
  it("liczy marżę w PLN/h z MD po stronie klienta", () => {
    const margin = closingMargin(row())
    expect(margin).toMatchObject({ kind: "ok", hourly: 30, percent: 20 })
  })

  it("strata jest ujemna, a nie zerem", () => {
    const margin = closingMargin(row({ client_rate_value: "100", client_rate_unit: "hourly" }))
    expect(margin).toMatchObject({ kind: "ok", hourly: -20, negative: true })
  })

  it("bez stawki kandydata albo w obcej walucie nie zmyśla liczby", () => {
    expect(closingMargin(row({ candidate_rate_value: null, candidate_rate_unit: null }))).toMatchObject({
      kind: "not_comparable",
      reason: "candidate_rate",
    })
    expect(closingMargin(row({ client_rate_currency: "EUR" }))).toMatchObject({
      kind: "not_comparable",
      reason: "currency",
    })
    expect(closingMargin(row({ client_rate_unit: null }))).toEqual({ kind: "empty" })
    expect(closingMargin(row({ client_rate_value: null }))).toEqual({ kind: "empty" })
  })

  it("stawka w PLN/h, ryczałt i obca waluta z jednostką", () => {
    expect(rateText("1200.00", "daily", "PLN")).toBe("150 zł/h")
    expect(rateText("20000", "monthly", "EUR")).toMatch(/^20\s000 EUR\/mc$/)
    expect(rateText(null, "hourly", "PLN")).toBeNull()
  })
})

describe("ClosingCandidatesTile", () => {
  beforeEach(() => {
    response = null
  })

  it("pokazuje klienta, krok, koszt, przychód, marżę, DL i rekrutera", async () => {
    response = { rows: [row()], total: 1, show_client_rate: true }
    render(wrap(<ClosingCandidatesTile />))
    expect(await screen.findByRole("link", { name: "Jan Przykładowy" })).toHaveAttribute(
      "href",
      "/jobs/10?candidate=1",
    )
    expect(screen.getByText("Zaakceptowany")).toBeInTheDocument()
    expect(screen.getByText(/Bank Północny/)).toBeInTheDocument()
    expect(screen.getByText("120 zł/h")).toBeInTheDocument()
    expect(screen.getByText("150 zł/h")).toBeInTheDocument()
    expect(screen.getByText("30 zł/h")).toBeInTheDocument()
    expect(screen.getByText("Anna Nowak")).toBeInTheDocument()
    expect(screen.getByText("Piotr Zieliński")).toBeInTheDocument()
  })

  it("bez prawa do stawki do klienta nie ma przychodu ani marży", async () => {
    response = {
      rows: [row({ client_rate_value: null, client_rate_unit: null, client_rate_currency: null })],
      total: 1,
      show_client_rate: false,
    }
    render(wrap(<ClosingCandidatesTile />))
    expect(await screen.findByText("120 zł/h")).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Przychód" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Marża" })).not.toBeInTheDocument()
  })

  it("mówi, ile pokazano z ilu", async () => {
    response = { rows: [row()], total: 64, show_client_rate: true }
    render(wrap(<ClosingCandidatesTile />))
    expect(await screen.findByText(/Pokazano 1 z 64/)).toBeInTheDocument()
  })

  it("pusta lista po sukcesie, awaria jako błąd", async () => {
    response = { rows: [], total: 0, show_client_rate: true }
    const { unmount } = render(wrap(<ClosingCandidatesTile />))
    expect(await screen.findByText(/Nikt nie czeka/)).toBeInTheDocument()
    unmount()
    response = null
    render(wrap(<ClosingCandidatesTile />))
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów/i })).toBeInTheDocument()
    expect(screen.queryByText(/Nikt nie czeka/)).not.toBeInTheDocument()
  })
})
