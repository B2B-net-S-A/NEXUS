import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { ActiveJobsTab } from "../tabs/ActiveJobsTab"

const getMock = vi.fn()
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
}))

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ActiveJobsTab deliveryLeadId={99} />
    </QueryClientProvider>,
  )
}

describe("ActiveJobsTab", () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it("renders empty state when API returns no items", async () => {
    getMock.mockResolvedValueOnce({
      data: { items: [], total: 0, page: 1, page_size: 100 },
    })
    renderTab()
    await waitFor(() => {
      expect(
        screen.getByText(/brak aktywnych jobów przypisanych do ciebie/i),
      ).toBeInTheDocument()
    })
    // Confirm endpoint called with correct delivery_lead_id + flags
    expect(getMock).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        params: expect.objectContaining({
          delivery_lead_id: 99,
          include_stage_counts: true,
          status: "published",
        }),
      }),
    )
  })

  it("renders job with stage breakdown chips", async () => {
    getMock.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 7,
            title: "Senior Backend Dev",
            client_id: 3,
            status: "published",
            candidate_count: 5,
            stage_breakdown: {
              screening: 3,
              cv_sent: 1,
              hired: 1,
            },
            primary_owner: { id: 22, name: "Recruiter A", email: "ra@b.pl" },
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
    })
    renderTab()
    await waitFor(() => {
      expect(screen.getByText("Senior Backend Dev")).toBeInTheDocument()
    })
    expect(screen.getByText(/screening: 3/i)).toBeInTheDocument()
    expect(screen.getByText(/cv wysłane: 1/i)).toBeInTheDocument()
    expect(screen.getByText(/hired: 1/i)).toBeInTheDocument()
  })

  it("renders 'brak kandydatów' when stage_breakdown is empty", async () => {
    getMock.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 8,
            title: "Job bez kandydatów",
            client_id: null,
            status: "published",
            candidate_count: 0,
            stage_breakdown: {},
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
    })
    renderTab()
    await waitFor(() => {
      expect(screen.getByText("Job bez kandydatów")).toBeInTheDocument()
    })
    expect(screen.getByText(/brak kandydatów/i)).toBeInTheDocument()
  })
})
