import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useAuthStore, type User } from "@/store/auth"

import { TeamSignalsTile } from "../TeamSignalsTile"

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
      <TeamSignalsTile />
    </QueryClientProvider>,
  )
}

// Zalogowana osoba jak na pulpicie — bez niej odrzucenie zapytania wycieka
// do testu jako nieobsłużone.
beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: { id: 7, role: "admin", roles: ["admin"] } as unknown as User, hydrated: true })
})

describe("TeamSignalsTile", () => {
  it("pusta lista = nic nie przekracza progów", async () => {
    getMock.mockResolvedValue({ data: { items: [] } })
    renderTile()
    expect(await screen.findByText("Nic nie przekracza progów.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Insights → Zespół" })).toHaveAttribute("href", "/insights?tab=zespol")
  })

  it("błąd to komunikat z ponowieniem", async () => {
    getMock.mockRejectedValue(new Error("boom"))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
    expect(screen.queryByText("Nic nie przekracza progów.")).toBeNull()
  })

  it("wiersze prowadzą do adresu, raportu albo tabeli Zespołu", async () => {
    getMock.mockResolvedValue({
      data: {
        items: [
          { kind: "no_one_sent", count: 4, label: "rekrutacji bez wysłanych", report: null, href: "/jobs?open=1&sent=none" },
          { kind: "stale_jobs", count: 2, label: "rekrutacji bez ruchu", report: "bez-ruchu" },
          { kind: "low_precision", count: 1, label: "osób z niską precyzją", report: null, user_ids: [5] },
          { kind: "stale_postings", count: 3, label: "zgłoszeń czeka", report: null },
        ],
      },
    })
    renderTile()
    expect((await screen.findByText("rekrutacji bez wysłanych")).closest("a")).toHaveAttribute(
      "href",
      "/jobs?open=1&sent=none",
    )
    expect(screen.getByText("rekrutacji bez ruchu").closest("a")).toHaveAttribute(
      "href",
      "/insights?tab=raporty&report=bez-ruchu",
    )
    expect(screen.getByText("osób z niską precyzją").closest("a")).toHaveAttribute("href", "/insights?tab=zespol")
    expect(screen.getByText("zgłoszeń czeka").closest("a")).toBeNull()
    expect(screen.getByText("4")).toHaveClass("text-destructive")
    expect(screen.getByText("2")).toHaveClass("text-warning")
  })
})
