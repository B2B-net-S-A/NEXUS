import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AdminTeamStructurePage from "./page"

const mocks = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replaceUrl: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  authUser: {
    id: 1,
    name: "Admin",
    role: "admin",
    roles: ["admin"],
  } as {
    id: number
    name: string
    role: string
    roles: string[]
  },
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.params,
  usePathname: () => "/settings/team-structure",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: mocks.replaceUrl }) }))
vi.mock("@/components/v2/competence-team/CompetenceTeamPanel", () => ({
  CompetenceTeamPanel: () => <div>Panel kategorii kompetencji</div>,
}))

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
    put: mocks.put,
  },
}))

vi.mock("@/store/auth", () => ({
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({
      hydrated: true,
      user: mocks.authUser,
    }),
}))

const categories = [
  { id: 1, slug: "engineering", name_pl: "Engineering", name_en: "Engineering" },
  { id: 2, slug: "sales", name_pl: "Sprzedaż", name_en: "Sales" },
  { id: 3, slug: "cloud", name_pl: "Cloud", name_en: "Cloud" },
]

const summary = {
  categories: [
    {
      category: categories[0],
      first_priority: [{ user_id: 10, name: "Anna TAC", priority: 1 }],
      second_priority: [],
    },
    {
      category: categories[1],
      first_priority: [],
      second_priority: [{ user_id: 10, name: "Anna TAC", priority: 2 }],
    },
    {
      category: categories[2],
      first_priority: [],
      second_priority: [],
    },
  ],
  delivery_leads: [],
  dl_clients: [
    {
      delivery_lead: { id: 30, name: "Dorota DL" },
      clients: [],
    },
  ],
  totals: {},
}

interface TestUser {
  id: number
  name: string
  email: string
  role: string
  roles?: string[]
}

const baseUsers: TestUser[] = [
  { id: 10, name: "Anna TAC", email: "anna@example.com", role: "recruiter" },
  {
    id: 20,
    name: "Bartek Rekruter",
    email: "bartek@example.com",
    role: "recruiter",
  },
  {
    id: 30,
    name: "Dorota DL",
    email: "dorota@example.com",
    role: "delivery_lead",
  },
]

let users: TestUser[] = baseUsers

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminTeamStructurePage />
    </QueryClientProvider>,
  )
}

describe("AdminTeamStructurePage — kompetencje i raportowanie", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.params = new URLSearchParams()
    users = baseUsers
    mocks.authUser = {
      id: 1,
      name: "Admin",
      role: "admin",
      roles: ["admin"],
    }
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/team-structure/summary") {
        return Promise.resolve({ data: summary })
      }
      if (url.startsWith("/api/users?")) {
        return Promise.resolve({ data: users })
      }
      if (url === "/api/clients") {
        return Promise.resolve({ data: [] })
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    mocks.put.mockResolvedValue({ data: { ok: true } })
    mocks.post.mockResolvedValue({ data: { ok: true } })
  })

  it("Finance widzi pełne przypisania read-only bez katalogów i mutacji", async () => {
    mocks.authUser = {
      id: 44,
      name: "Finance",
      role: "finance",
      roles: ["finance"],
    }

    renderPage()

    expect(await screen.findByText("Kompetencje zespołu")).toBeInTheDocument()
    expect(screen.getByText("Engineering")).toBeInTheDocument()
    expect(screen.getAllByText("Anna TAC")).toHaveLength(2)
    expect(screen.getByText("Klienci Delivery Leadów")).toBeInTheDocument()
    expect(screen.getByText("Dorota DL")).toBeInTheDocument()
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /zapisz/i })).not.toBeInTheDocument()
    expect(mocks.put).not.toHaveBeenCalled()
    expect(mocks.post).not.toHaveBeenCalled()
    expect(mocks.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/api\/users/))
    expect(mocks.get).not.toHaveBeenCalledWith("/api/clients")
  })

  it("domyślnie zakładka „Kategorie” z panelem kategorii; zmiana zakładki idzie do adresu", async () => {
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByRole("heading", { level: 1, name: "Zespół rekrutacji" })).toBeInTheDocument()
    expect(screen.getByText("Panel kategorii kompetencji")).toBeInTheDocument()
    // Osobny edytor „1. Kompetencje zespołu rekrutacji” zapisywał te same
    // priorytety 1/2 — od 20.10.2026 jest tylko panel kategorii.
    expect(screen.queryByText("1. Kompetencje zespołu rekrutacji")).not.toBeInTheDocument()
    expect(screen.queryByText(/Zespół Delivery Leada/)).not.toBeInTheDocument()

    await user.click(screen.getByRole("tab", { name: "Delivery Leadzi i klienci" }))
    expect(mocks.replaceUrl).toHaveBeenCalledWith("/settings/team-structure?zakladka=dl")
  })

  it("nie oferuje ręcznej relacji TAC do DL i wyjaśnia relacje klientowe", async () => {
    mocks.params = new URLSearchParams("zakladka=dl")
    renderPage()

    expect(
      await screen.findByText(/skład zespołu dl wynika z relacji przy kliencie/i),
    ).toBeInTheDocument()
    // Funkcja TAC wyłączona w UI (22.09.2026) — tekst nie wspomina TAC-ów.
    expect(
      screen.getByText(/Delivery Leadów przypisujesz do klientów/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/klient ↔ TAC/i)).not.toBeInTheDocument()
    expect(
      screen.getByText(/raportują organizacyjnie do Head of Recruitment/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /przypisz tac/i }),
    ).not.toBeInTheDocument()
    expect(mocks.post).not.toHaveBeenCalled()
    expect(mocks.get).not.toHaveBeenCalledWith(
      "/api/team-structure/tac-delivery-leads",
    )
  })

  it("uwzględnia role dodatkowe w dostępie i katalogu osób", async () => {
    mocks.authUser = {
      id: 2,
      name: "Hanna Hybrid",
      role: "recruiter",
      roles: ["recruiter", "head_of_recruitment"],
    }
    users = [
      ...baseUsers,
      {
        id: 40,
        name: "Daria Hybrid",
        email: "daria@example.com",
        role: "delivery_lead",
        roles: ["delivery_lead", "recruiter"],
      },
    ]

    mocks.params = new URLSearchParams("zakladka=dl")
    renderPage()

    expect(
      await screen.findByRole("option", { name: "Daria Hybrid" }),
    ).toBeInTheDocument()
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/users?roles=recruiter&roles=delivery_lead",
    )
  })
})
