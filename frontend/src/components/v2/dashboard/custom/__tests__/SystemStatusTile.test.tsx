import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useAuthStore, type User } from "@/store/auth"

import { readCheck, SystemStatusTile } from "../SystemStatusTile"

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
      <SystemStatusTile />
    </QueryClientProvider>,
  )
}

function toneOf(key: string) {
  const row = document.querySelector(`[data-check="${key}"]`)
  return row?.querySelector("[data-tone]")?.getAttribute("data-tone")
}

// Zalogowana osoba jak na pulpicie — bez niej odrzucenie zapytania wycieka
// do testu jako nieobsłużone.
beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: { id: 7, role: "admin", roles: ["admin"] } as unknown as User, hydrated: true })
})

describe("readCheck", () => {
  it("unknown i brak sondy to „Nie wiadomo”, nie OK", () => {
    expect(readCheck("unknown").tone).toBe("unknown")
    expect(readCheck(undefined).tone).toBe("unknown")
    expect(readCheck("healthy").tone).toBe("ok")
    expect(readCheck("configured").tone).toBe("ok")
    expect(readCheck("unconfigured").tone).toBe("off")
    expect(readCheck("degraded: stale 3d")).toEqual({ tone: "warn", detail: "Nieaktualne od 3d" })
    expect(readCheck("unhealthy: stalled order_mail")).toEqual({
      tone: "fail",
      detail: "Zawieszone: order_mail",
    })
    expect(readCheck({ status: "degraded", detail: "Ostatni bieg padł" })).toEqual({
      tone: "warn",
      detail: "Ostatni bieg padł",
    })
  })
})

describe("SystemStatusTile", () => {
  it("bez sond (sukces) nic nie jest OK", async () => {
    getMock.mockResolvedValue({ data: { status: "healthy", version: "unknown", checks: {} } })
    renderTile()
    expect(await screen.findByText("Baza danych")).toBeInTheDocument()
    expect(screen.queryByText("OK")).toBeNull()
    expect(screen.getAllByText("Nie wiadomo").length).toBeGreaterThan(0)
  })

  it("błąd to komunikat z ponowieniem", async () => {
    getMock.mockRejectedValue(new Error("boom"))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
  })

  it("pokazuje wersję i stan sond", async () => {
    getMock.mockResolvedValue({
      data: {
        status: "healthy",
        version: "abcdef1234567",
        checks: {
          database: "healthy",
          voyage: "unknown",
          traffit: "degraded",
          order_mail: "unconfigured",
          background_tasks: "crashed: traffit_sync",
          anthropic: "configured",
        },
      },
    })
    renderTile()
    expect(await screen.findByText("abcdef1")).toBeInTheDocument()
    expect(toneOf("database")).toBe("ok")
    expect(toneOf("voyage")).toBe("unknown")
    expect(toneOf("traffit")).toBe("warn")
    expect(toneOf("order_mail")).toBe("off")
    expect(toneOf("background_tasks")).toBe("fail")
    expect(toneOf("anthropic")).toBe("ok")
    expect(toneOf("qdrant")).toBe("unknown")
    expect(screen.getByText("traffit_sync")).toBeInTheDocument()
  })
})
