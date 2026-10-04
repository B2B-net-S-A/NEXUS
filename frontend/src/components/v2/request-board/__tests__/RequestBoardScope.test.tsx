import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { RequestBoard as RequestBoardData } from "@/lib/api/requestAllocation"

// Kontener `RequestBoard` (kafelek pulpitu): dane z `useRequestBoard`, filtry
// z adresu albo z zakresu kafelka. Sieć, router i uprawnienia są atrapami.
const mocks = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
  board: null as unknown,
}))

vi.mock("@/lib/api", () => ({ default: {}, api: {} }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(mocks.search),
}))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock("@/lib/api/requestAllocation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/requestAllocation")>()),
  useRequestBoard: () => ({
    data: mocks.board,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  }),
}))
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => false }))
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showInfo: vi.fn(), showSuccess: vi.fn() }),
}))

import { RequestBoard } from "@/components/v2/request-board/RequestBoard"

const board: RequestBoardData = {
  mode: "shadow",
  availability_known: true,
  viewer: { user_id: 31, primary_category_id: 4 },
  changes_since: null,
  groups: [
    { category_id: 2, name: "Development", slug: "software_development", total: 1, searching: 1, champion: 0 },
    { category_id: 4, name: "QA", slug: "security_quality", total: 1, searching: 1, champion: 0 },
  ],
  requests: [
    { job_id: 1, title: "Senior Java Developer", client_name: "Klient Gamma", category_id: 2, deadline: null, sent: 0, champion: false, people: [], delivery_lead: { id: 31, name: "Gosia Delivery" } },
    { job_id: 3, title: "Tester automatyzujący", client_name: "Klient Beta", category_id: 4, deadline: null, sent: 0, champion: false, people: [], delivery_lead: null },
  ],
  load: [],
  changes: [],
}

beforeEach(() => {
  mocks.search = ""
  mocks.replace.mockReset()
  mocks.board = board
})

describe("RequestBoard — zakres kafelka", () => {
  it("„Moja kategoria” bez `rb_*` w adresie: tylko kategoria widza, linia filtra, adres nietknięty", async () => {
    const user = userEvent.setup()
    render(<RequestBoard scope="my_category" />)
    expect(screen.getByRole("region", { name: "QA" })).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "Development" })).not.toBeInTheDocument()
    expect(screen.getByText("Filtr: Twoja kategoria")).toBeInTheDocument()
    // Samo wyświetlenie nie wpisuje zakresu do adresu.
    expect(mocks.replace).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "Pokaż wszystkie" }))
    expect(screen.getByRole("region", { name: "Development" })).toBeInTheDocument()
    expect(screen.queryByText("Filtr: Twoja kategoria")).not.toBeInTheDocument()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it("„Moje jako DL”: requesty, w których widz jest Delivery Leadem", () => {
    render(<RequestBoard scope="my_lead" />)
    expect(screen.getByRole("region", { name: "Development" })).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument()
    expect(
      screen.getByText("Filtr: requesty, w których jesteś Delivery Leadem"),
    ).toBeInTheDocument()
  })

  it("adres z `rb_cat` wygrywa z zakresem", () => {
    mocks.search = "rb_cat=2"
    render(<RequestBoard scope="my_category" />)
    expect(screen.getByRole("region", { name: "Development" })).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument()
    expect(screen.queryByText("Filtr: Twoja kategoria")).not.toBeInTheDocument()
  })

  it("zmiana filtra przez człowieka zapisuje się w adresie razem z zakresem", async () => {
    const user = userEvent.setup()
    render(<RequestBoard scope="my_category" />)
    await user.click(screen.getByRole("button", { name: /Bez rekrutera/ }))
    expect(mocks.replace).toHaveBeenCalledWith("/dashboard?rb_cat=4&rb_nobody=1", { scroll: false })
  })

  it("widz bez kategorii: wszystkie requesty, bez linii filtra", () => {
    mocks.board = { ...board, viewer: { user_id: 31, primary_category_id: null } }
    render(<RequestBoard scope="my_category" />)
    expect(screen.getByRole("region", { name: "Development" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "QA" })).toBeInTheDocument()
    expect(screen.queryByText(/^Filtr:/)).not.toBeInTheDocument()
  })
})
