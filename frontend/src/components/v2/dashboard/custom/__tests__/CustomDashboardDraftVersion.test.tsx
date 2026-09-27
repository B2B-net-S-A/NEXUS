import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useEffect } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import { USER_DASHBOARD_QUERY_KEY, type DashboardTile } from "@/lib/api/userDashboard"
import { useAuthStore, type User } from "@/store/auth"

import { CustomDashboard } from "../CustomDashboard"

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
      post: async (url: string) => {
        throw new Error(`nieoczekiwane POST ${url}`)
      },
    },
  }
})

vi.mock("@/components/v2/dashboard/custom/TileContent", () => ({
  TileContent: ({ tile }: { tile: DashboardTile }) => <div>treść {tile.type}</div>,
}))

// jsdom nie ma szerokości — siatka zgłosiłaby tryb listy i schowała
// „Edytuj układ”. Atrapa zgłasza siatkę i pozwala przesunąć kafelek.
vi.mock("../DashboardGrid", () => ({
  DashboardGrid: ({
    tiles,
    editing,
    onModeChange,
    onLayoutChange,
  }: {
    tiles: DashboardTile[]
    editing: boolean
    onModeChange?: (mode: "grid" | "list") => void
    onLayoutChange: (tiles: DashboardTile[]) => void
  }) => {
    useEffect(() => {
      onModeChange?.("grid")
    }, [onModeChange])
    return (
      <div>
        {tiles.map((t) => (
          <span key={t.id}>kafelek {t.id}</span>
        ))}
        {editing ? (
          <button
            type="button"
            onClick={() => onLayoutChange(tiles.map((t) => ({ ...t, x: t.x + 1 })))}
          >
            przesuń
          </button>
        ) : null}
      </div>
    )
  },
}))

const recruiter = {
  id: 7,
  email: "r@example.com",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  is_active: true,
} as unknown as User

beforeEach(() => {
  getMock.mockReset()
  saveMock.mockReset()
  useAuthStore.setState({ user: recruiter, hydrated: true })
})

describe("tryb edycji pulpitu (R10-N1-2)", () => {
  it("szkic zapisuje się z wersją, z której powstał, nie z pobranej po powrocie do karty", async () => {
    const tileA: DashboardTile = {
      id: "a",
      type: "note",
      x: 0,
      y: 0,
      w: 4,
      h: 2,
      config: { title: "A" },
    }
    getMock.mockResolvedValue({ tiles: [tileA], version: 3, dropped_tiles: [] })
    saveMock.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "DASHBOARD_VERSION_CONFLICT" } } },
    })
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <CustomDashboard />
        </ToastProvider>
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole("button", { name: /Edytuj układ/ }))
    fireEvent.click(screen.getByRole("button", { name: "przesuń" }))

    // Inna karta dodała kafelek (v4); powrót do tej karty pobrał pulpit ponownie.
    getMock.mockResolvedValue({
      tiles: [tileA, { ...tileA, id: "b", x: 4 }],
      version: 4,
      dropped_tiles: [],
    })
    await act(async () => {
      await client.refetchQueries({ queryKey: USER_DASHBOARD_QUERY_KEY })
      // Powiadomienia react-query idą przez setTimeout(0) — niech pulpit się przerysuje.
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(client.getQueryData<{ version: number }>(USER_DASHBOARD_QUERY_KEY)?.version).toBe(4)

    fireEvent.click(screen.getByRole("button", { name: /Zapisz układ/ }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    expect(saveMock.mock.calls[0][1]).toBe(3)
    expect(await screen.findByText(/zmieniony w innej karcie/)).toBeInTheDocument()
  })
})
