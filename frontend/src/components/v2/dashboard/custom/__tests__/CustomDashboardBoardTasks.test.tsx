import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import type { DashboardTile } from "@/lib/api/userDashboard"
import { useAuthStore, type User } from "@/store/auth"

import { CustomDashboard } from "../CustomDashboard"

// „Czeka na Ciebie” jako kafelek (23.10.2026): Head of Recruitment i admin
// przesuwają panel i usuwają go jak inne kafelki. Panel ma własne testy — tu
// tylko to, gdzie stoi i co zapisuje pulpit.

const getMock = vi.fn()
const saveMock = vi.fn()
const panelMock = vi.fn()

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
      put: async (url: string, body: { tiles?: DashboardTile[]; expected_version?: number; hidden?: boolean }) => {
        if (url === "/api/users/me/dashboard") {
          return { data: await saveMock(body.tiles, body.expected_version) }
        }
        const panel = url.match(/^\/api\/users\/me\/dashboard\/panels\/([a-z_]+)$/)
        if (panel) return { data: await panelMock(panel[1], body.hidden) }
        throw new Error(`nieoczekiwane PUT ${url}`)
      },
    },
  }
})

vi.mock("@/components/v2/dashboard/DlSendQueueBand", () => ({
  DlSendQueueBand: () => null,
  showsDlSendBand: () => false,
}))
vi.mock("@/components/v2/dashboard/EsignCompanyBand", () => ({
  EsignCompanyBand: () => null,
}))
vi.mock("@/components/v2/dashboard/BoardTasksPanel", () => ({
  BoardTasksPanel: (p: { inTile?: boolean; onMoveToGrid?: () => void; onRemovePanel?: () => void }) => (
    <div role="region" aria-label="Czeka na Ciebie">
      <p>{p.inTile ? "panel w kafelku" : "panel nad siatką"}</p>
      {p.onMoveToGrid ? (
        <button type="button" onClick={p.onMoveToGrid}>
          Postaw jako kafelek na pulpicie
        </button>
      ) : null}
      {p.onRemovePanel ? (
        <button type="button" onClick={p.onRemovePanel}>
          Usuń panel z pulpitu
        </button>
      ) : null}
    </div>
  ),
}))
vi.mock("@/components/v2/dashboard/custom/MyWeekTile", async () => {
  const actual = await vi.importActual<object>("@/components/v2/dashboard/custom/MyWeekTile")
  return { ...actual, MyWeekTile: () => <p>mój tydzień</p> }
})

function user(role: string): User {
  return {
    id: 7,
    email: "u@example.com",
    name: "Osoba",
    role,
    roles: [role],
    is_active: true,
  } as unknown as User
}

const myWeek: DashboardTile = { id: "a", type: "my_week", x: 0, y: 0, w: 6, h: 3, config: {} }
const boardTile: DashboardTile = { id: "b", type: "board_tasks", x: 0, y: 3, w: 12, h: 6, config: {} }

function layout(tiles: DashboardTile[], hidden: string[] = []) {
  return { tiles, version: 3, dropped_tiles: [], hidden_panels: hidden }
}

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
  panelMock.mockReset()
  window.localStorage.clear()
  useAuthStore.setState({ user: user("head_of_recruitment"), hydrated: true })
})

describe("pulpit — „Czeka na Ciebie” jako kafelek", () => {
  it("„Postaw jako kafelek” stawia kafelek na górze siatki, a panel znika znad siatki", async () => {
    getMock.mockResolvedValue(layout([myWeek]))
    saveMock.mockImplementation(async (tiles: DashboardTile[]) => ({ ...layout(tiles), version: 4 }))
    renderDashboard()

    expect(await screen.findByText("panel nad siatką")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Postaw jako kafelek na pulpicie" }))

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    const [tiles, version] = saveMock.mock.calls[0]
    expect(version).toBe(3)
    expect(tiles.map((t: DashboardTile) => [t.type, t.x, t.y, t.w])).toEqual([
      ["board_tasks", 0, 0, 12],
      ["my_week", 0, 6, 6],
    ])
    expect(await screen.findByText("panel w kafelku")).toBeInTheDocument()
    expect(screen.queryByText("panel nad siatką")).toBeNull()
    expect(screen.getAllByText(/^panel (w kafelku|nad siatką)$/)).toHaveLength(1)
  })

  it("kafelek na pulpicie: panel tylko w kafelku, bez menu przenoszenia", async () => {
    getMock.mockResolvedValue(layout([myWeek, boardTile]))
    renderDashboard()
    expect(await screen.findByText("panel w kafelku")).toBeInTheDocument()
    expect(screen.queryByText("panel nad siatką")).toBeNull()
    expect(screen.queryByRole("button", { name: "Postaw jako kafelek na pulpicie" })).toBeNull()
  })

  it("usunięcie kafelka zapisuje układ i chowa panel — nie wraca nad siatkę", async () => {
    getMock.mockResolvedValue(layout([myWeek, boardTile]))
    saveMock.mockImplementation(async (tiles: DashboardTile[]) => ({ ...layout(tiles, ["board_tasks"]), version: 4 }))
    panelMock.mockImplementation(async () => ({ ...layout([myWeek, boardTile], ["board_tasks"]) }))
    renderDashboard()

    await screen.findByText("panel w kafelku")
    await userEvent.click(screen.getByRole("button", { name: "Menu kafelka Czeka na Ciebie" }))
    await userEvent.click(await screen.findByRole("menuitem", { name: "Usuń z pulpitu" }))

    await waitFor(() => expect(panelMock).toHaveBeenCalledWith("board_tasks", true))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    expect(saveMock.mock.calls[0][0].map((t: DashboardTile) => t.type)).toEqual(["my_week"])
    await waitFor(() => expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull())
  })

  it("„Usuń panel z pulpitu” nad siatką zapisuje ukrycie całego panelu", async () => {
    getMock.mockResolvedValue(layout([myWeek]))
    panelMock.mockImplementation(async () => layout([myWeek], ["board_tasks"]))
    renderDashboard()
    fireEvent.click(await screen.findByRole("button", { name: "Usuń panel z pulpitu" }))
    await waitFor(() => expect(panelMock).toHaveBeenCalledWith("board_tasks", true))
    await waitFor(() => expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull())
    expect(saveMock).not.toHaveBeenCalled()
  })

  it("rekruter: panel zawsze nad siatką, bez menu; kafelek z cudzego układu pokazuje „Brak dostępu”", async () => {
    useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    getMock.mockResolvedValue(layout([myWeek, boardTile], ["board_tasks"]))
    renderDashboard()
    expect(await screen.findByText("panel nad siatką")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Postaw jako kafelek na pulpicie" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Usuń panel z pulpitu" })).toBeNull()
    expect(screen.queryByText("panel w kafelku")).toBeNull()
    expect(screen.getByText("Dla Head of Recruitment i admina")).toBeInTheDocument()
  })
})
