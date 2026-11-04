import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useAuthStore, type User } from "@/store/auth"

import { MyPeopleBody } from "../SmallTiles"

const getMock = vi.fn()

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = { get: (...args: unknown[]) => getMock(...args) }
  return { ...actual, api, default: api }
})

function renderTile() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MyPeopleBody />
    </QueryClientProvider>,
  )
}

const summary = {
  total: 12,
  new_matches: 0,
  jobs_with_matches: 0,
  latest_matches: [],
  idle_count: 4,
  idle_top: [],
  idle_days: 30,
}

// Zalogowana osoba jak na pulpicie — bez niej odrzucenie zapytania wycieka
// do testu jako nieobsłużone.
beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: { id: 7, role: "admin", roles: ["admin"] } as unknown as User, hydrated: true })
})

describe("MyPeopleBody", () => {
  it("bez dopasowań: zdanie o dzwonku, bez liczby czekających", async () => {
    getMock.mockResolvedValue({ data: summary })
    renderTile()
    expect(await screen.findByText(/Brak nowych dopasowań/)).toBeInTheDocument()
    expect(screen.queryByText("12")).toBeNull()
  })

  it("błąd to komunikat z ponowieniem", async () => {
    getMock.mockRejectedValue(new Error("boom"))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
  })

  it("nowe dopasowania z linkiem „Dodaj”", async () => {
    getMock.mockResolvedValue({
      data: {
        ...summary,
        new_matches: 3,
        jobs_with_matches: 2,
        latest_matches: [
          { job_id: 5, job_title: "Tester", candidate_id: 1, full_name: "Anna Nowak", score: 81.4, created_at: "2026-10-04T08:00:00Z" },
        ],
      },
    })
    renderTile()
    expect(await screen.findByText("3 nowe dopasowania w 2 rekrutacjach")).toBeInTheDocument()
    expect(screen.getByText("81")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Dodaj: Anna Nowak/ })).toHaveAttribute("href", "/jobs/5?people=1")
  })
})
