import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling"
import { useAuthStore, type User } from "@/store/auth"

import { TodayCycleTile } from "../TodayCycleTile"

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
      <TodayCycleTile />
    </QueryClientProvider>,
  )
}

const pair = {
  candidate_id: 11,
  candidate_name: "Anna Nowak",
  candidate_email: null,
  job_id: 22,
  job_title: "Tester",
  client_id: 3,
  client_name: "Bank A",
}

function overview(partial: Record<string, unknown>) {
  return {
    generated_at: new Date().toISOString(),
    scope: "mine",
    call_window_minutes: 30,
    items: [],
    agenda: [],
    todos: [],
    truncated: false,
    ...partial,
  }
}

function userWith(roles: string[]) {
  return { id: 7, email: "x@example.com", name: "X", role: roles[0], roles, is_active: true } as unknown as User
}

beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: userWith(["recruiter"]), hydrated: true })
})

describe("TodayCycleTile", () => {
  it("pusty dzień: komunikat i link do Rozmów u klienta", async () => {
    getMock.mockResolvedValue({ data: overview({}) })
    renderTile()
    expect(await screen.findByText("Na dziś nie ma rozmów ani prepów.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Rozmowy u klienta →" })).toHaveAttribute("href", "/calendar")
    expect(getMock).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "mine" } })
  })

  it("błąd to komunikat z ponowieniem, nie pustka", async () => {
    getMock.mockRejectedValue(new Error("boom"))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
    expect(screen.queryByText("Na dziś nie ma rozmów ani prepów.")).toBeNull()
  })

  it("pokazuje pilne zadania na górze i tylko dzisiejszą agendę (DL: zakres rekrutacji)", async () => {
    useAuthStore.setState({ user: userWith(["delivery_lead"]), hydrated: true })
    const now = new Date()
    const nextWeek = new Date(now.getTime() + 7 * 86_400_000)
    getMock.mockResolvedValue({
      data: overview({
        todos: [
          { ...pair, kind: "slots_pick", priority: 3, due: null, event_id: null, slot_request_id: 5 },
          { ...pair, kind: "call_now", priority: 1, due: now.toISOString(), event_id: 9, slot_request_id: null },
        ],
        agenda: [
          { ...pair, kind: "prep2", start: nextWeek.toISOString(), end: null, event_id: 2, slot_request_id: null, online_meeting_url: null, done: false },
          { ...pair, kind: "interview", start: now.toISOString(), end: null, event_id: 1, slot_request_id: null, online_meeting_url: null, done: false },
        ],
      }),
    })
    renderTile()
    expect(await screen.findByText("Zadzwoń teraz")).toBeInTheDocument()
    expect(screen.queryByText("Terminy czekają na kandydata")).toBeNull()
    expect(screen.getByText(/Rozmowa u klienta · Anna Nowak/)).toBeInTheDocument()
    expect(screen.queryByText(/Prep 2 ·/)).toBeNull()
    const urgentLink = screen.getByText("Zadzwoń teraz").closest("a")
    expect(urgentLink).toHaveAttribute("href", "/calendar?cycle=11-22")
    expect(getMock).toHaveBeenCalledWith("/api/interview-cycle", { params: { scope: "jobs" } })
  })

  describe("odpytywanie (18.11.2026: bez stałej minuty)", () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] })
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it("bez granic w danych: siatka bezpieczeństwa z lib/polling, nie co minutę", async () => {
      getMock.mockResolvedValue({ data: overview({}) })
      renderTile()
      await vi.advanceTimersByTimeAsync(0)
      expect(getMock).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(getMock).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(WS_BACKED_SAFETY_POLL_MS - 60_000)
      expect(getMock).toHaveBeenCalledTimes(2)
    })

    it("koniec rozmowy za 2 min: dociąga tuż po nim („Zadzwoń teraz” nie czeka 5 min)", async () => {
      const now = Date.now()
      getMock.mockResolvedValue({
        data: overview({
          call_window_minutes: 30,
          agenda: [
            {
              ...pair,
              kind: "interview",
              start: new Date(now - 58 * 60_000).toISOString(),
              end: new Date(now + 2 * 60_000).toISOString(),
              event_id: 1,
              slot_request_id: null,
              online_meeting_url: null,
              done: false,
            },
          ],
        }),
      })
      renderTile()
      await vi.advanceTimersByTimeAsync(0)
      expect(getMock).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(2 * 60_000 - 5_000)
      expect(getMock).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(10_000)
      expect(getMock).toHaveBeenCalledTimes(2)
    })
  })
})
