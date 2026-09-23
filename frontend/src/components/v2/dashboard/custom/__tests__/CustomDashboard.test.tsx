import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import type { DashboardTile } from "@/lib/api/userDashboard"
import { useAuthStore, type User } from "@/store/auth"

// `vi.mock` niżej jest podnoszony nad importy, więc pulpit dostaje podmienione zależności.
import { CustomDashboard as CustomDashboardLazy } from "../CustomDashboard"

const getMock = vi.fn()
const saveMock = vi.fn()
let searchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
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

// Treść kafelków to widżety z własnymi zapytaniami — tu testujemy pulpit,
// nie widżety, więc podmieniamy je na znacznik typu.
vi.mock("@/components/v2/dashboard/custom/TileContent", () => ({
  TileContent: ({ tile }: { tile: DashboardTile }) => <div>treść {tile.type}</div>,
}))
vi.mock("@/components/candidate-contact/ContactOversightPanel", () => ({
  ContactOversightPanel: () => <div id="nadzor-kontaktu">panel nadzoru</div>,
}))

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <CustomDashboardLazy />
      </ToastProvider>
    </QueryClientProvider>,
  )
}


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
  window.location.hash = ""
  searchParams = new URLSearchParams()
})

describe("własny pulpit", () => {
  it("pusty pulpit pokazuje polecane dla roli i dodaje wszystkie jednym zapisem", async () => {
    getMock.mockResolvedValue({ tiles: [], version: 0, dropped_tiles: [] })
    saveMock.mockImplementation(async (tiles: DashboardTile[]) => ({
      tiles,
      version: 1,
      dropped_tiles: [],
    }))
    renderDashboard()

    expect(await screen.findByText("Twój pulpit jest pusty")).toBeInTheDocument()
    expect(screen.getByText("Polecane dla roli Rekruter")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Dodaj wszystkie 4" }))

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    const [tiles, version] = saveMock.mock.calls[0]
    expect(version).toBe(0)
    expect(tiles.map((t: DashboardTile) => t.type)).toEqual([
      "metric_number",
      "my_recruitments",
      "my_next_steps",
      "calendar_today",
    ])
    expect(await screen.findByText("treść my_recruitments")).toBeInTheDocument()
  })

  it("konflikt wersji mówi o innej karcie i wczytuje pulpit ponownie", async () => {
    getMock.mockResolvedValue({ tiles: [], version: 3, dropped_tiles: [] })
    saveMock.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "DASHBOARD_VERSION_CONFLICT" } } },
    })
    renderDashboard()

    fireEvent.click(await screen.findByRole("button", { name: "Dodaj Moje rekrutacje" }))

    expect(
      await screen.findByText(/zmieniony w innej karcie/),
    ).toBeInTheDocument()
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2))
    expect(saveMock.mock.calls[0][1]).toBe(3)
  })

  it("usunięcie kafelka z menu zapisuje od razu, bez trybu edycji", async () => {
    const tiles: DashboardTile[] = [
      { id: "a", type: "note", x: 0, y: 0, w: 4, h: 2, config: { title: "Moje linki" } },
      { id: "b", type: "calendar_today", x: 4, y: 0, w: 4, h: 2, config: {} },
    ]
    getMock.mockResolvedValue({ tiles, version: 5, dropped_tiles: [] })
    saveMock.mockImplementation(async (next: DashboardTile[]) => ({
      tiles: next,
      version: 6,
      dropped_tiles: [],
    }))
    renderDashboard()

    const menu = await screen.findByRole("button", { name: "Menu kafelka Moje linki" })
    fireEvent.pointerDown(menu, { button: 0, ctrlKey: false })
    fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń z pulpitu" }))

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    expect(saveMock.mock.calls[0][0].map((t: DashboardTile) => t.id)).toEqual(["b"])
    expect(saveMock.mock.calls[0][1]).toBe(5)
  })

  it("druga akcja w trakcie zapisu nie idzie ze starą wersją (FE-N07)", async () => {
    const tiles: DashboardTile[] = [
      { id: "a", type: "note", x: 0, y: 0, w: 4, h: 2, config: { title: "Moje linki" } },
      { id: "b", type: "note", x: 4, y: 0, w: 4, h: 2, config: { title: "Inne" } },
    ]
    getMock.mockResolvedValue({ tiles, version: 5, dropped_tiles: [] })
    let release: (v: unknown) => void = () => {}
    saveMock.mockImplementationOnce(
      (next: DashboardTile[]) =>
        new Promise((resolve) => {
          release = () => resolve({ tiles: next, version: 6, dropped_tiles: [] })
        }),
    )
    saveMock.mockImplementation(async (next: DashboardTile[]) => ({
      tiles: next,
      version: 7,
      dropped_tiles: [],
    }))
    renderDashboard()

    const open = async (title: string) => {
      const menu = await screen.findByRole("button", { name: `Menu kafelka ${title}` })
      fireEvent.pointerDown(menu, { button: 0, ctrlKey: false })
    }
    await open("Moje linki")
    fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń z pulpitu" }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))

    // W trakcie zapisu menu drugiego kafelka ma wyłączone akcje.
    await open("Inne")
    const remove = await screen.findByRole("menuitem", { name: "Usuń z pulpitu" })
    expect(remove).toHaveAttribute("data-disabled")
    fireEvent.click(remove)
    expect(saveMock).toHaveBeenCalledTimes(1)

    release(null)
    await waitFor(() => expect(screen.queryByText("treść note")).toBeInTheDocument())
    // Po zapisie kolejna akcja idzie z NOWĄ wersją i nowym układem.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" })
    await open("Inne")
    fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń z pulpitu" }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(2))
    expect(saveMock.mock.calls[1][1]).toBe(6)
    expect(saveMock.mock.calls[1][0]).toEqual([])
  })

  it("pominięte kafelki są zgłoszone, a nie znikają bez słowa", async () => {
    getMock.mockResolvedValue({
      tiles: [{ id: "a", type: "note", x: 0, y: 0, w: 4, h: 2, config: {} }],
      version: 1,
      dropped_tiles: [{ id: "x", type: "stary_typ" }],
    })
    renderDashboard()
    expect(
      await screen.findByText(/Jeden kafelek nie jest już dostępny/),
    ).toBeInTheDocument()
  })

  it("link z alertu SLA w parametrze ?panel= (FE-N09) też pokazuje nadzór", async () => {
    useAuthStore.setState({
      user: { ...recruiter, role: "head_of_recruitment", roles: ["head_of_recruitment"] } as User,
      hydrated: true,
    })
    getMock.mockResolvedValue({ tiles: [], version: 0, dropped_tiles: [] })
    const view = renderDashboard()
    await screen.findByText("Twój pulpit jest pusty")
    expect(screen.queryByText("panel nadzoru")).toBeNull()
    // Miękka nawigacja: ten sam pulpit, nowy parametr w adresie.
    searchParams = new URLSearchParams("panel=nadzor-kontaktu")
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    view.rerender(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <CustomDashboardLazy />
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText("panel nadzoru")).toBeInTheDocument()
  })

  it("link z alertu SLA pokazuje nadzór kontaktów, choć nie ma go na pulpicie", async () => {
    useAuthStore.setState({
      user: { ...recruiter, role: "head_of_recruitment", roles: ["head_of_recruitment"] } as User,
      hydrated: true,
    })
    window.location.hash = "#nadzor-kontaktu"
    getMock.mockResolvedValue({ tiles: [], version: 0, dropped_tiles: [] })
    renderDashboard()
    expect(await screen.findByText("panel nadzoru")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Dodaj na stałe" })).toBeInTheDocument()
  })
})
