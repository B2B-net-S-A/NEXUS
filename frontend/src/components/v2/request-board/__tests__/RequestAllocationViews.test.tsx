import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({ default: {}, api: {} }))

import { CompetenceTeamView } from "@/components/v2/competence-team/CompetenceTeamPanel"
import { RequestBoardView } from "@/components/v2/request-board/RequestBoard"
import { RequestReviewView } from "@/components/v2/request-review/RequestReview"
import type {
  CompetenceTeam,
  RequestBoard,
  ReviewResponse,
} from "@/lib/api/requestAllocation"
import { EMPTY_FILTERS, type BoardFilters } from "@/lib/request-board"

const TODAY = "2026-09-24"

const board: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [
    { category_id: 2, name: "Development", slug: "software_development", total: 2, searching: 1, champion: 1 },
    { category_id: 4, name: "QA", slug: "security_quality", total: 1, searching: 1, champion: 0 },
  ],
  requests: [
    { job_id: 1, title: "Senior Java Developer", client_name: "Klient Gamma", category_id: 2, deadline: "2026-09-23", sent: 0, champion: false, people: [{ user_id: 7, name: "Anna Przykładowa", role: "recruiter", proposed: true, source: "auto" }] },
    { job_id: 2, title: "React Developer", client_name: "Klient Alfa", category_id: 2, deadline: "2026-09-28", sent: 3, champion: true, people: [] },
    { job_id: 3, title: "Tester automatyzujący", client_name: "Klient Beta", category_id: 4, deadline: null, sent: 0, champion: false, people: [] },
  ],
  load: [
    { user_id: 7, name: "Anna Przykładowa", count: 1, leave_until: null, requests: [{ job_id: 1, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-09-23", proposed: true }] },
    { user_id: 8, name: "Bartek Testowy", count: 0, leave_until: "2026-09-29", requests: [] },
  ],
  changes: [],
}

function Board({ canEdit = false }: { canEdit?: boolean }) {
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS)
  return (
    <RequestBoardView
      board={board}
      today={TODAY}
      filters={filters}
      onFilters={setFilters}
      canEdit={canEdit}
      onAddPerson={vi.fn()}
      onRemovePerson={vi.fn()}
    />
  )
}

describe("RequestBoardView", () => {
  it("groups by category, marks champion and overdue deadline", () => {
    render(<Board />)
    const dev = screen.getByRole("region", { name: "Development" })
    expect(within(dev).getByText("2 requesty")).toBeInTheDocument()
    expect(within(dev).getByText("Champion")).toBeInTheDocument()
    expect(within(dev).getByText("23.09.2026")).toHaveClass("text-destructive")
    expect(screen.getByText(/propozycja/)).toBeInTheDocument()
    expect(screen.getByText(/Brak świeżych danych o urlopach/)).toBeInTheDocument()
  })

  it("filters by who works and shows N z M", async () => {
    const user = userEvent.setup()
    render(<Board />)
    await user.selectOptions(screen.getByLabelText("Kto pracuje"), "7")
    expect(screen.getByText("Pokazuję 1 z 3")).toBeInTheDocument()
    expect(screen.getByText("1 z 2 requestów")).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Wyczyść filtry" }))
    expect(screen.getByText("Pokazuję 3 z 3")).toBeInTheDocument()
  })

  it("load panel expands a person and shows leave", async () => {
    const user = userEvent.setup()
    render(<Board />)
    const panel = screen.getByRole("region", { name: "Obłożenie" })
    expect(within(panel).getByText("urlop do 29.09.2026")).toBeInTheDocument()
    const anna = within(panel).getByRole("button", { name: /Anna Przykładowa/ })
    expect(anna).toHaveAttribute("aria-expanded", "false")
    await user.click(anna)
    expect(anna).toHaveAttribute("aria-expanded", "true")
    expect(within(panel).getByText(/Senior Java Developer · Klient Gamma \(propozycja\)/)).toBeInTheDocument()
  })

  it("editors see add/remove controls, others do not", () => {
    const { unmount } = render(<Board />)
    expect(screen.queryByRole("button", { name: /Dodaj osobę do/ })).not.toBeInTheDocument()
    unmount()
    render(<Board canEdit />)
    expect(screen.getAllByRole("button", { name: /Dodaj osobę do/ }).length).toBe(2)
    expect(screen.getByRole("button", { name: "Zdejmij Anna Przykładowa z requestu" })).toBeInTheDocument()
  })
})

const team: CompetenceTeam = {
  categories: [
    { id: 4, slug: "security_quality", name: "QA", requests_searching: 1, first: [], second: [] },
  ],
  unassigned: [{ user_id: 5, name: "Ewa Fikcyjna", roles: ["recruiter"], allocation_excluded: false, assignment_id: null }],
  excluded: [],
  people: [{ user_id: 5, name: "Ewa Fikcyjna", roles: ["recruiter"], allocation_excluded: false, assignment_id: null }],
  rules: { sourcer_threshold: 15, review_time: "08:30" },
}

describe("CompetenceTeamView", () => {
  it("adds a person to 1st priority and excludes from allocation", async () => {
    const user = userEvent.setup()
    const actions = { assign: vi.fn(), remove: vi.fn(), exclude: vi.fn(), saveRules: vi.fn() }
    render(<CompetenceTeamView team={team} actions={actions} />)
    await user.click(screen.getByRole("button", { name: "Dodaj osobę do: QA, 1. priorytet" }))
    await user.type(screen.getByLabelText("Szukaj osoby"), "ewa")
    await user.click(screen.getByRole("button", { name: /Ewa Fikcyjna/ }))
    expect(actions.assign).toHaveBeenCalledWith(5, 4, 1)
    await user.click(screen.getByRole("button", { name: "Poza przydziałem" }))
    expect(actions.exclude).toHaveBeenCalledWith(5, true)
  })

  it("saves rules as numbers", async () => {
    const user = userEvent.setup()
    const actions = { assign: vi.fn(), remove: vi.fn(), exclude: vi.fn(), saveRules: vi.fn() }
    render(<CompetenceTeamView team={team} actions={actions} />)
    const threshold = screen.getByRole("spinbutton")
    await user.clear(threshold)
    await user.type(threshold, "20")
    await user.click(screen.getByRole("button", { name: "Zapisz zasady" }))
    expect(actions.saveRules).toHaveBeenCalledWith({ sourcer_threshold: 20, review_time: "08:30" })
  })
})

const review: ReviewResponse = {
  tab: "to_review",
  counts: { to_review: 2, searching: 0, champion: 0, client_silent: 0, finished: 0 },
  rows: [
    { job_id: 31, title: "Senior Java Developer", client_name: null, delivery_lead_name: null, deadline: null, state: "to_review", state_label: "Do przejrzenia", last_work_at: null, last_cv_at: null, sent_total: 0, applications_14d: 0, suggested_state: "searching", suggestion_reason: "Nowy request" },
    { job_id: 32, title: "Scrum Master", client_name: null, delivery_lead_name: null, deadline: null, state: "to_review", state_label: "Do przejrzenia", last_work_at: null, last_cv_at: null, sent_total: 1, applications_14d: 0, suggested_state: "client_silent", suggestion_reason: "CV wysłane 63 dni temu, potem cisza" },
  ],
}

describe("RequestReviewView", () => {
  it("accepts suggestions for the selected rows", async () => {
    const user = userEvent.setup()
    const actions = { setState: vi.fn(), dropChampion: vi.fn() }
    render(
      <RequestReviewView
        data={review}
        tab="to_review"
        onTab={vi.fn()}
        mine={false}
        onMine={vi.fn()}
        q=""
        onQ={vi.fn()}
        actions={actions}
      />,
    )
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Senior Java Developer" }))
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Scrum Master" }))
    await user.click(screen.getByRole("button", { name: "Przyjmij podpowiedzi (2)" }))
    expect(actions.setState).toHaveBeenCalledWith([
      { job_id: 31, state: "searching" },
      { job_id: 32, state: "client_silent" },
    ])
  })
})
