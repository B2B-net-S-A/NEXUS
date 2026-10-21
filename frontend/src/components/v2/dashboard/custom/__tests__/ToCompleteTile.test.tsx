import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

// `null` = awaria odczytu kolejki (500): kafelek nie może jej pokazać jak pustki.
let queue: Record<string, unknown> | null = {}
let hiddenPanels: string[] = []

vi.mock("@/lib/api", () => {
  const api = {
    get: async (url: string) => {
      if (url === "/api/users/me/dashboard") {
        return { data: { tiles: [], version: 1, hidden_panels: hiddenPanels } }
      }
      if (url === "/api/board-tasks") {
        if (queue === null) throw Object.assign(new Error("boom"), { response: { status: 500 } })
        return { data: { window_days: 14, cpro_to_send: [], cpro_sent: [], ...queue } }
      }
      return { data: [] }
    },
  }
  return {
    __esModule: true,
    default: api,
    api,
    b2bGeneratorApi: { generated: vi.fn(), updateGenerated: vi.fn() },
  }
})
vi.mock("@/components/v2/pages/B2BContractGeneratorV2", () => ({
  ConfirmFullySignedDialog: () => null,
}))
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}))

import { useAuthStore } from "@/store/auth"

import { ToCompleteTile } from "../ToCompleteTile"

const since = new Date(Date.now() - 3 * 86_400_000).toISOString()

function agreement(over: Record<string, unknown> = {}) {
  return {
    generated_id: 55,
    contract_number: "1601/2026",
    reason: "closed_signed_active",
    candidate_id: 21,
    candidate_name: "Ewa Zielińska",
    job_id: 31,
    job_title: "Java Developer",
    client_name: "Bank Północny",
    since,
    requested_by_name: null,
    contract_id: 812,
    ...over,
  }
}

const pending = {
  autoclose_on: null,
  items: [
    {
      job_id: 71,
      title: "Analityk danych",
      client_name: "Bank Kappa",
      kind: "published_not_handed_off",
      created_at: since,
      delivery_lead_name: "Anna Lis",
      missing: ["Budżet PLN/h"],
    },
  ],
}

const fix = {
  job_id: 81,
  title: "Programista Java",
  reasons: [{ code: "prose_rows", text: "zdania w wymaganiach" }],
  can_apply: true,
  rows: 4,
  talk: 2,
}

function renderTile() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToCompleteTile />
    </QueryClientProvider>,
  )
}

describe("ToCompleteTile — „Do uzupełnienia”", () => {
  beforeEach(() => {
    hiddenPanels = []
    useAuthStore.setState({ user: { id: 1, role: "head_of_recruitment" }, realUser: null } as never)
  })

  it("trzy listy z liczbami; z umów tylko „do zamknięcia” — podpis zostaje w panelu", async () => {
    queue = {
      pending_jobs: pending,
      requirement_fixes: [fix, { ...fix, job_id: 82, title: "Tester" }],
      agreements: {
        to_confirm: [agreement({ generated_id: 54, reason: "requested", candidate_name: "Jan Bąk" })],
        to_close: [agreement()],
        waiting_on_others: [],
      },
    }
    renderTile()
    const switcher = await screen.findByRole("group", { name: "Rodzaj zaległości" })
    expect(within(switcher).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Umowy1",
      "Rekrutacje1",
      "Wymagania2",
    ])
    expect(screen.getByRole("region", { name: "Umowy do zamknięcia" })).toHaveTextContent("Ewa Zielińska")
    expect(screen.queryByRole("region", { name: "Umowy do potwierdzenia" })).toBeNull()
    expect(screen.queryByText("Jan Bąk")).toBeNull()
    expect(screen.getByRole("link", { name: "Sprawdź: Ewa Zielińska" })).toHaveAttribute(
      "href",
      "/contracts/812",
    )
    expect(screen.getByRole("region", { name: "Rekrutacje do dokończenia albo zamknięcia" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "Wymagania do poprawy" })).toBeTruthy()
  })

  it("wąski kafelek: przełącznik pokazuje jedną listę naraz", async () => {
    queue = { pending_jobs: pending, requirement_fixes: [fix] }
    renderTile()
    const switcher = await screen.findByRole("group", { name: "Rodzaj zaległości" })
    expect(within(switcher).getByRole("button", { name: /Rekrutacje/ })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByTestId("to-complete-fixes").className).toContain("hidden")
    await userEvent.click(within(switcher).getByRole("button", { name: /Wymagania/ }))
    expect(within(switcher).getByRole("button", { name: /Wymagania/ })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByTestId("to-complete-fixes").className).not.toContain("hidden")
    expect(screen.getByTestId("to-complete-jobs").className).toContain("hidden")
  })

  it("jedna lista → bez przełącznika", async () => {
    queue = { requirement_fixes: [fix] }
    renderTile()
    await screen.findByRole("region", { name: "Wymagania do poprawy" })
    expect(screen.queryByRole("group", { name: "Rodzaj zaległości" })).toBeNull()
  })

  it("nic do uzupełnienia → jedno zdanie", async () => {
    queue = { pending_jobs: null, requirement_fixes: [], agreements: { to_confirm: [], to_close: [], waiting_on_others: [] } }
    renderTile()
    expect(await screen.findByText("Nic do uzupełnienia.")).toBeTruthy()
  })

  it("awaria liczenia wymagań (`null`) → zdanie o awarii, nie „Nic do uzupełnienia.”", async () => {
    queue = { requirement_fixes: null }
    renderTile()
    expect(await screen.findByText("Nie udało się policzyć „Wymagań do poprawy” — odśwież pulpit.")).toBeTruthy()
    expect(screen.queryByText("Nic do uzupełnienia.")).toBeNull()
  })

  it("awaria odczytu kolejki → komunikat z ponowieniem, nie pusty kafelek", async () => {
    queue = null
    renderTile()
    expect(await screen.findByText("Nie udało się wczytać list „Do uzupełnienia”.")).toBeTruthy()
    expect(screen.queryByText("Nic do uzupełnienia.")).toBeNull()
  })

  it("lista odznaczona w „Listy nad pulpitem” jest w kafelku pusta, jak w panelu", async () => {
    hiddenPanels = ["requirement_fixes"]
    queue = { pending_jobs: pending, requirement_fixes: [fix] }
    renderTile()
    await screen.findByRole("region", { name: "Rekrutacje do dokończenia albo zamknięcia" })
    expect(screen.queryByRole("region", { name: "Wymagania do poprawy" })).toBeNull()
  })
})
