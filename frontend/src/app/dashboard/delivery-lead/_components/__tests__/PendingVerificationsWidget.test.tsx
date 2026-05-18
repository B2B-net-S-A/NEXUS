import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { ToastProvider } from "@/components/Toast"
import type { PendingVerificationItem } from "@/lib/api"

import { PendingVerificationsWidget } from "../PendingVerificationsWidget"

// Mock the pipelineApi helpers — widget calls listMyPendingVerifications or
// listPendingVerifications based on `mine` prop and acceptVerification/rejectVerification
// on mutations.
const listMineMock = vi.fn()
const listAllMock = vi.fn()
vi.mock("@/lib/api", () => ({
  pipelineApi: {
    listMyPendingVerifications: () => listMineMock(),
    listPendingVerifications: () => listAllMock(),
    acceptVerification: vi.fn(),
    rejectVerification: vi.fn(),
  },
  default: {},
}))

function makeItem(overrides: Partial<PendingVerificationItem> = {}): PendingVerificationItem {
  return {
    candidate_stage_id: 1,
    candidate_id: 11,
    candidate_name: "Jan Kowalski",
    job_id: 21,
    job_title: "Senior Dev",
    expected_rate_value: "450.00",
    expected_rate_unit: "hourly",
    expected_rate_currency: "PLN",
    budget_max_at_move: 400,
    moved_at: "2026-05-18T10:00:00Z",
    moved_by: 7,
    moved_by_name: "Recruiter Test",
    notes: null,
    ...overrides,
  }
}

function renderWidget(props: { mine?: boolean } = {}) {
  // Fresh QueryClient per test so cache doesn't leak between cases.
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <PendingVerificationsWidget mine={props.mine ?? true} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("PendingVerificationsWidget", () => {
  beforeEach(() => {
    listMineMock.mockReset()
    listAllMock.mockReset()
  })

  it("renders empty state ('Wszystkie weryfikacje przejrzane') when API returns []", async () => {
    listMineMock.mockResolvedValueOnce({ data: [] })
    renderWidget({ mine: true })
    await waitFor(() => {
      expect(screen.getByText(/wszystkie weryfikacje przejrzane/i)).toBeInTheDocument()
    })
    expect(listMineMock).toHaveBeenCalledTimes(1)
  })

  it("renders item with candidate name, job, rate when API returns 1 item", async () => {
    listMineMock.mockResolvedValueOnce({ data: [makeItem()] })
    renderWidget({ mine: true })
    await waitFor(() => {
      expect(screen.getByText("Jan Kowalski")).toBeInTheDocument()
    })
    expect(screen.getByText("Senior Dev")).toBeInTheDocument()
    expect(screen.getByText(/450/)).toBeInTheDocument()
    // Accept + Reject buttons rendered
    expect(screen.getByRole("button", { name: /akceptuj/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /odrzu/i })).toBeInTheDocument()
  })

  it("uses `listMine` endpoint when mine=true and `listAll` when mine=false", async () => {
    listAllMock.mockResolvedValueOnce({ data: [] })
    renderWidget({ mine: false })
    await waitFor(() => {
      expect(listAllMock).toHaveBeenCalledTimes(1)
    })
    expect(listMineMock).not.toHaveBeenCalled()
  })

  it("shows 'Zobacz wszystkie (N) →' link when more than 3 items", async () => {
    const items = Array.from({ length: 5 }, (_, i) =>
      makeItem({
        candidate_stage_id: 100 + i,
        candidate_id: 200 + i,
        candidate_name: `Kand${i}`,
      }),
    )
    listMineMock.mockResolvedValueOnce({ data: items })
    renderWidget({ mine: true })
    await waitFor(() => {
      expect(screen.getByText(/zobacz wszystkie \(5\)/i)).toBeInTheDocument()
    })
  })
})
