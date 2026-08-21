import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { JobPriorityContext } from "@/components/v2/priority-work/JobPriorityContext"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getJobContext: vi.fn(),
    },
  }
})

function renderContext() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <JobPriorityContext jobId={101} />
    </QueryClientProvider>,
  )
}

/** Błąd w kształcie, w jakim dostarcza go axios (`error.response.status`). */
function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: { detail: "x" } },
  })
}

describe("JobPriorityContext — treść zależna od trybu", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 9,
        email: "recruiter@example.com",
        name: "Alicja Recruiter",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })
  })

  it("przy mode=off NIE twierdzi, że nie wolno dodawać nowych kandydatów", async () => {
    // Stan produkcyjny (`/api/health` → priority_work: disabled) na dowolnej
    // rekrutacji z żywym pipeline'em: carry_over_count > 0, bo `open_process()`
    // leci przy każdym wejściu kandydata do rekrutacji.
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "off",
      plan: null,
      assignments: [],
      carry_over_count: 3,
      blockers: [],
    })

    renderContext()

    expect(
      await screen.findByText("Brak aktywnego assignmentu"),
    ).toBeInTheDocument()
    // Zdanie fałszywe przy mode=off — i sprzeczne z `ModeNotice` w tej samej
    // karcie („Obowiązują dotychczasowe zasady pracy").
    expect(screen.queryByText(/ale nie dodawać nowych/)).not.toBeInTheDocument()
    expect(
      screen.getByTestId("priority-work-off-notice"),
    ).toBeInTheDocument()
  })

  it("przy mode=shadow mówi o wykrywaniu, nie o blokadzie", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "shadow",
      plan: null,
      assignments: [],
      carry_over_count: 2,
      blockers: [],
    })

    renderContext()

    expect(
      await screen.findByText(/wykrywane, ale nie blokowane/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/ale nie dodawać nowych/)).not.toBeInTheDocument()
  })

  it("przy mode=enforce ograniczenie ZOSTAJE wypowiedziane", async () => {
    // Druga strona granicy: gdy tryb naprawdę egzekwuje, komunikat musi być.
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "enforce",
      plan: null,
      assignments: [],
      carry_over_count: 1,
      blockers: [],
    })

    renderContext()

    expect(
      await screen.findByText(/ale nie dodawać nowych/),
    ).toBeInTheDocument()
  })
})

describe("JobPriorityContext — 403 to nie awaria", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 9,
        email: "sourcer@example.com",
        name: "Bartek Sourcer",
        role: "sourcer",
        roles: ["sourcer"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })
  })

  it("brak członkostwa w zespole rekrutacji nie maluje czerwonego alertu", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockRejectedValue(httpError(403))

    const { container } = renderContext()

    await waitFor(() => {
      expect(vi.mocked(priorityWorkApi.getJobContext)).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(container.querySelector("[role='alert']")).toBeNull()
    })
    expect(
      screen.queryByText(/Nie udało się pobrać kontekstu Priority Work/),
    ).not.toBeInTheDocument()
  })

  it("realna awaria (500) NADAL pokazuje blok błędu", async () => {
    // Granica w drugą stronę: cichnięcie na wszystkim zamieniłoby awarię
    // w pustkę, czyli defekt tej samej klasy, tylko odwrotny.
    vi.mocked(priorityWorkApi.getJobContext).mockRejectedValue(httpError(500))

    renderContext()

    expect(
      await screen.findByText(/Nie udało się pobrać kontekstu Priority Work/),
    ).toBeInTheDocument()
  })
})
