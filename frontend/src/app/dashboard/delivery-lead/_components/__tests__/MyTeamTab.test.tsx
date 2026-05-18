import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { MyTeamTab } from "../tabs/MyTeamTab"

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
      <MyTeamTab />
    </QueryClientProvider>,
  )
}

describe("MyTeamTab", () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it("renders empty state ('Nie masz przypisanych TAC') when API returns []", async () => {
    getMock.mockResolvedValueOnce({ data: [] })
    renderTab()
    await waitFor(() => {
      expect(screen.getByText(/nie masz przypisanych tac/i)).toBeInTheDocument()
    })
  })

  it("renders table with TAC name + metrics", async () => {
    getMock.mockResolvedValueOnce({
      data: [
        {
          tac_user_id: 42,
          tac_name: "Anna TAC",
          tac_email: "anna@b2bnet.pl",
          active_jobs: 3,
          active_candidates: 17,
          assignment_created_at: "2026-01-15T10:00:00Z",
        },
      ],
    })
    renderTab()
    await waitFor(() => {
      expect(screen.getByText("Anna TAC")).toBeInTheDocument()
    })
    expect(screen.getByText("anna@b2bnet.pl")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
    expect(screen.getByText("17")).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith("/api/team-structure/my-team")
  })

  it("renders error state on API failure", async () => {
    getMock.mockRejectedValueOnce(new Error("boom"))
    renderTab()
    await waitFor(() => {
      expect(screen.getByText(/nie udało się pobrać zespołu/i)).toBeInTheDocument()
    })
  })
})
