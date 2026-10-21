import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import type { DashboardTile } from "@/lib/api/userDashboard"
import { useAuthStore, type User } from "@/store/auth"

import { CustomDashboard } from "../CustomDashboard"

// „Do uzupełnienia” (21.10.2026): pulpit mówi panelowi, czy kafelek stoi na
// siatce, i daje mu „Przenieś na pulpit”. Panel ma własne testy — tu znacznik.

const getMock = vi.fn()
const saveMock = vi.fn()

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    api: {
      get: async (url: string) => {
        if (url === "/api/users/me/dashboard") return { data: await getMock() }
        throw new Error(`nieoczekiwane GET ${url}`)
      },
      put: async (url: string, body: { tiles: DashboardTile[]; expected_version: number }) => {
        if (url !== "/api/users/me/dashboard") throw new Error(`nieoczekiwane PUT ${url}`)
        return { data: await saveMock(body.tiles, body.expected_version) }
      },
    },
  }
})

vi.mock("@/components/v2/dashboard/custom/TileContent", () => ({
  TileContent: ({ tile }: { tile: DashboardTile }) => <div>treść {tile.type}</div>,
}))
vi.mock("@/components/v2/dashboard/DlSendQueueBand", () => ({
  DlSendQueueBand: () => null,
  showsDlSendBand: () => false,
}))
vi.mock("@/components/v2/dashboard/BoardTasksPanel", () => ({
  BoardTasksPanel: (p: {
    toCompleteOnGrid?: boolean
    onMoveToComplete?: () => void
    onKeepToComplete?: () => void
  }) => (
    <div role="region" aria-label="Czeka na Ciebie">
      <p>kafelek na pulpicie: {p.toCompleteOnGrid ? "tak" : "nie"}</p>
      {p.onMoveToComplete ? (
        <>
          <button type="button" onClick={p.onMoveToComplete}>
            Przenieś na pulpit
          </button>
          <button type="button" onClick={p.onKeepToComplete}>
            Zostaw tutaj
          </button>
        </>
      ) : null}
    </div>
  ),
}))

const recruiter = {
  id: 7,
  email: "r@example.com",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  is_active: true,
} as unknown as User

const myWeek: DashboardTile = { id: "a", type: "my_week", x: 0, y: 0, w: 6, h: 3, config: {} }

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <CustomDashboard />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  getMock.mockReset()
  saveMock.mockReset()
  window.localStorage.clear()
  useAuthStore.setState({ user: recruiter, hydrated: true })
})

describe("pulpit — „Do uzupełnienia”", () => {
  it("„Przenieś na pulpit” stawia kafelek na górze siatki na całą szerokość i zapisuje układ", async () => {
    getMock.mockResolvedValue({ tiles: [myWeek], version: 3, dropped_tiles: [] })
    saveMock.mockImplementation(async (tiles: DashboardTile[]) => ({ tiles, version: 4, dropped_tiles: [] }))
    renderDashboard()

    expect(await screen.findByText("kafelek na pulpicie: nie")).toBeInTheDocument()
    fireEvent.click(await screen.findByRole("button", { name: "Przenieś na pulpit" }))

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    const [tiles, version] = saveMock.mock.calls[0]
    expect(version).toBe(3)
    expect(tiles.map((t: DashboardTile) => [t.type, t.x, t.y, t.w])).toEqual([
      ["to_complete", 0, 0, 12],
      ["my_week", 0, 5, 6],
    ])
    expect(await screen.findByText("kafelek na pulpicie: tak")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Przenieś na pulpit" })).toBeNull()
  })

  it("kafelek już stoi na pulpicie → panel o tym wie i nie proponuje przeniesienia", async () => {
    getMock.mockResolvedValue({
      tiles: [myWeek, { id: "b", type: "to_complete", x: 6, y: 0, w: 6, h: 5, config: {} }],
      version: 3,
      dropped_tiles: [],
    })
    renderDashboard()
    expect(await screen.findByText("kafelek na pulpicie: tak")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Przenieś na pulpit" })).toBeNull()
  })

  it("kafelek w układzie, ale bez dostępu do „Rekrutacji” → listy zostają w panelu", async () => {
    useAuthStore.setState({
      user: { ...recruiter, effective_section_access: { pipeline: "none" } } as User,
      hydrated: true,
    })
    getMock.mockResolvedValue({
      tiles: [myWeek, { id: "b", type: "to_complete", x: 6, y: 0, w: 6, h: 5, config: {} }],
      version: 3,
      dropped_tiles: [],
    })
    renderDashboard()
    expect(await screen.findByText("kafelek na pulpicie: nie")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Przenieś na pulpit" })).toBeNull()
  })

  it("„Zostaw tutaj” chowa propozycję także po ponownym wejściu, bez zapisu układu", async () => {
    getMock.mockResolvedValue({ tiles: [myWeek], version: 3, dropped_tiles: [] })
    const first = renderDashboard()
    fireEvent.click(await screen.findByRole("button", { name: "Zostaw tutaj" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Przenieś na pulpit" })).toBeNull())
    first.unmount()

    renderDashboard()
    expect(await screen.findByText("kafelek na pulpicie: nie")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Przenieś na pulpit" })).toBeNull()
    expect(saveMock).not.toHaveBeenCalled()
  })
})
