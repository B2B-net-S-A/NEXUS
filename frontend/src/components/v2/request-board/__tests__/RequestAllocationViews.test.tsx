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

const anna = { user_id: 7, name: "Anna Przykładowa" }
const bartek = { user_id: 8, name: "Bartek Testowy" }
const celina = { user_id: 9, name: "Celina Wzorcowa" }

const board: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [
    { category_id: 2, name: "Development", slug: "software_development", total: 3, searching: 2, champion: 1 },
    { category_id: 4, name: "QA", slug: "security_quality", total: 1, searching: 1, champion: 0 },
  ],
  requests: [
    // Sama propozycja automatu — to jeszcze nie praca.
    { job_id: 1, title: "Senior Java Developer", client_name: "Klient Gamma", category_id: 2, deadline: "2026-09-23", sent: 0, champion: false, priority_level: "p1", delivery_lead: { id: 31, name: "Gosia Delivery" }, opened_effective_at: "2026-09-20T08:00:00Z", people: [{ ...anna, proposed: true, source: "auto", via: "assignment", assigned_by_name: null }] },
    { job_id: 2, title: "React Developer", client_name: "Klient Alfa", category_id: 2, deadline: "2026-09-28", sent: 3, champion: true, priority_level: "p2", delivery_lead: null, opened_effective_at: null, people: [] },
    { job_id: 3, title: "Tester automatyzujący", client_name: "Klient Beta", category_id: 4, deadline: null, sent: 0, champion: false, priority_level: "accepting", delivery_lead: { id: 32, name: "Henryk Kierujący" }, opened_effective_at: "2026-09-01T08:00:00Z", people: [] },
    // Dwie pracujące osoby: prowadzący i osoba z przypisania.
    { job_id: 4, title: "Kotlin Developer", client_name: "Klient Delta", category_id: 2, deadline: "2026-10-07", sent: 1, champion: false, priority_level: "p2", delivery_lead: { id: 31, name: "Gosia Delivery" }, opened_effective_at: "2026-09-12T08:00:00Z", people: [
      { ...bartek, proposed: false, source: "owner", via: "owner", assigned_by_name: null },
      { ...celina, proposed: false, source: "manual", via: "assignment", assigned_by_name: "Henryk Kierujący" },
    ] },
  ],
  load: [
    { ...bartek, count: 1, proposed: 0, leave_until: "2026-09-29", requests: [{ job_id: 4, title: "Kotlin Developer", client_name: "Klient Delta", deadline: "2026-10-07", proposed: false }] },
    { ...anna, count: 2, proposed: 1, leave_until: null, requests: [
      { job_id: 11, title: "Data Engineer", client_name: "Klient Beta", deadline: null, proposed: false },
      { job_id: 12, title: "DevOps Engineer", client_name: "Klient Alfa", deadline: "2026-09-30", proposed: false },
      { job_id: 1, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-09-23", proposed: true },
    ] },
    { ...celina, count: 1, proposed: 0, leave_until: null, requests: [{ job_id: 4, title: "Kotlin Developer", client_name: "Klient Delta", deadline: "2026-10-07", proposed: false }] },
  ],
  changes: [],
}

interface BoardProps {
  canStaff?: boolean
  canDecide?: boolean
  data?: RequestBoard
  onAddPerson?: () => void
  onRemovePerson?: () => void
  onAcceptProposal?: () => void
  busyKeys?: ReadonlySet<string>
}

function Board({
  canStaff = false,
  canDecide = false,
  data = board,
  onAddPerson = vi.fn(),
  onRemovePerson = vi.fn(),
  onAcceptProposal = vi.fn(),
  busyKeys,
}: BoardProps) {
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS)
  return (
    <RequestBoardView
      board={data}
      today={TODAY}
      filters={filters}
      onFilters={setFilters}
      canStaff={canStaff}
      canDecide={canDecide}
      onAddPerson={onAddPerson}
      onRemovePerson={onRemovePerson}
      onAcceptProposal={onAcceptProposal}
      busyKeys={busyKeys}
    />
  )
}

/** Wiersz requestu: najbliższy przodek linku z tytułem, który jest siatką kolumn. */
function rowOf(title: string): HTMLElement {
  const row = screen.getByRole("link", { name: title }).closest("div.grid")
  if (!(row instanceof HTMLElement)) throw new Error(`brak wiersza: ${title}`)
  return row
}

describe("RequestBoardView", () => {
  it("groups by category, marks champion and overdue deadline", () => {
    render(<Board />)
    const dev = screen.getByRole("region", { name: "Development" })
    expect(within(dev).getByText("3 requesty")).toBeInTheDocument()
    expect(within(dev).getByText("Champion")).toBeInTheDocument()
    // Ta sama komórka terminu co na liście rekrutacji: data i „po terminie N dni”.
    expect(within(dev).getByText("23.09.2026")).toBeInTheDocument()
    expect(within(dev).getByText("po terminie 1 dzień")).toHaveClass("text-destructive")
    expect(screen.getByText(/Brak świeżych danych o urlopach/)).toBeInTheDocument()
  })

  it("mówi, że automat tylko proponuje, i ile propozycji czeka", () => {
    render(<Board />)
    expect(
      screen.getByText(/Automat proponuje — akceptuje Head of Recruitment\./),
    ).toHaveTextContent("Na akceptację czeka 1 propozycja.")
  })

  it("w trybie „auto” mówi, że automat przydziela od razu, a Head of Recruitment może to zmienić", () => {
    render(<Board data={{ ...board, mode: "auto" }} />)
    expect(screen.getByText(/Automat przydziela od razu\./)).toHaveTextContent(
      "Rekruter prowadzący jest przypisany zaraz po przekazaniu do searchu — Head of Recruitment może go zmienić.",
    )
  })

  it("ma kolumny listy rekrutacji: kategoria, Delivery Lead, data otwarcia, priorytet", () => {
    render(<Board />)
    for (const header of ["Request", "Kategoria", "Delivery Lead", "Otwarta", "Termin", "Wysłani", "Rekruter"]) {
      // Nagłówek kolumny (filtry mają etykiety o tych samych nazwach).
      expect(screen.getAllByText(header).length).toBeGreaterThan(0)
    }
    const row = within(rowOf("Senior Java Developer"))
    expect(row.getByTitle("P1 Pilne")).toBeInTheDocument()
    // Krótka nazwa kategorii, pełna w podpowiedzi.
    expect(within(row.getByTestId("request-category-cell")).getByText("Dev")).toHaveAttribute("title", "Development")
    expect(row.getByTestId("request-lead-cell")).toHaveTextContent("Gosia Delivery")
    expect(row.getByTestId("request-opened-cell")).toHaveTextContent("20.09.2026")
    // P2 to stan domyślny — bez plakietki.
    expect(within(rowOf("Kotlin Developer")).queryByTitle(/P2/)).not.toBeInTheDocument()
    expect(within(rowOf("Tester automatyzujący")).getByTitle("Przyjmujemy kandydatów")).toBeInTheDocument()
    // Request bez Delivery Leada i daty otwarcia: kreska, nie pusta komórka.
    const champion = within(rowOf("React Developer"))
    expect(champion.getByTestId("request-lead-cell")).toHaveTextContent("—")
    expect(champion.getByTestId("request-opened-cell")).toHaveTextContent("—")
  })

  it("kolumny zależą od szerokości kontenera tabeli, nie okna", () => {
    render(<Board />)
    const row = rowOf("Senior Java Developer")
    // Wąski kontener (kafelek): kategoria, DL i data otwarcia stoją drobnym
    // drukiem pod tytułem, a ich kolumny są ukryte.
    expect(within(row).getByTestId("request-category-cell")).toHaveClass("hidden", "@min-[1060px]/rtable:block")
    const folded = within(row).getByTitle("Delivery Lead: Gosia Delivery")
    expect(folded).toHaveTextContent("DL: Gosia D.")
    expect(folded).toHaveClass("@min-[1060px]/rtable:hidden")
    expect(within(row).getByTitle("Otwarta 20.09.2026")).toHaveTextContent("otwarta 20.09")
    expect(within(row).getByTitle("Kategoria: Development")).toHaveTextContent("Dev")
    // Układ pulpitu nie ma reguł zależnych od szerokości okna: każdy element
    // z wariantem kontenera pyta wyłącznie o kontener.
    const responsive = [...document.querySelectorAll<HTMLElement>("[class*='/rboard:'], [class*='/rtable:']")]
    expect(responsive.length).toBeGreaterThan(5)
    for (const element of responsive) {
      expect(element.className).not.toMatch(/(?:^|\s)(?:sm|md|lg|xl|2xl):/)
    }
    expect(screen.getByRole("heading", { name: "Requesty i obłożenie" }).closest("[class*='@container/rboard']")).not.toBeNull()
    const table = row.closest(".overflow-x-auto")
    expect(table).toHaveClass("@container/rtable", "relative")
    // Pierwsza kolumna przyklejona tam, gdzie tabela się przewija.
    expect(row.firstElementChild).toHaveClass("@max-[699px]/rtable:sticky", "@max-[699px]/rtable:left-0")
  })

  it("Rekruter: pracujący jako chipy, propozycja przerywaną ramką, „Bez rekrutera” tylko gdy nie ma nikogo", () => {
    render(<Board />)
    const kotlin = within(screen.getByRole("list", { name: "Rekruter: Kotlin Developer" }))
    expect(kotlin.getAllByRole("listitem")).toHaveLength(2)
    expect(kotlin.getByText("Bartek Testowy")).toBeInTheDocument()
    // Bez dopisku roli przy osobie (podział rekruter / sourcer zniknął).
    expect(kotlin.queryByText(/sourcer|rekruter/)).not.toBeInTheDocument()

    const java = within(rowOf("Senior Java Developer"))
    expect(java.getByText("Anna Przykładowa").parentElement).toHaveAttribute("data-proposed", "true")
    // Nie decyduję o propozycjach — widzę tylko, że czeka.
    expect(java.getByText("czeka na akceptację")).toBeInTheDocument()
    expect(java.queryByRole("button", { name: /Akceptuj/ })).not.toBeInTheDocument()
    expect(java.queryByText("Bez rekrutera")).not.toBeInTheDocument()

    expect(within(rowOf("Tester automatyzujący")).getByText("Bez rekrutera")).toHaveClass(
      "bg-warning-muted",
      "text-warning-muted-foreground",
    )
    // Request z championem: nikt już nie szuka, więc brak osoby to nie alarm.
    const champion = within(rowOf("React Developer"))
    expect(champion.queryByText("Bez rekrutera")).not.toBeInTheDocument()
    expect(champion.getByText("nikt")).toBeInTheDocument()
  })

  it("osoba decydująca akceptuje propozycję i odrzuca ją „×”", async () => {
    const user = userEvent.setup()
    const onAcceptProposal = vi.fn()
    const onRemovePerson = vi.fn()
    render(<Board canStaff canDecide onAcceptProposal={onAcceptProposal} onRemovePerson={onRemovePerson} />)
    const java = within(rowOf("Senior Java Developer"))
    expect(java.queryByText("czeka na akceptację")).not.toBeInTheDocument()

    await user.click(java.getByRole("button", { name: "Akceptuj propozycję: Anna Przykładowa — Senior Java Developer" }))
    expect(onAcceptProposal).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: 1 }),
      expect.objectContaining({ user_id: 7, proposed: true }),
    )

    await user.click(java.getByRole("button", { name: "Zdejmij Anna Przykładowa" }))
    expect(onRemovePerson).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: 1 }),
      expect.objectContaining({ user_id: 7, proposed: true }),
    )
  })

  it("Delivery Lead zdejmuje pracujących, ale propozycji nie rozstrzyga", async () => {
    const user = userEvent.setup()
    const onRemovePerson = vi.fn()
    render(<Board canStaff onRemovePerson={onRemovePerson} />)
    const java = within(rowOf("Senior Java Developer"))
    expect(java.queryByRole("button", { name: "Zdejmij Anna Przykładowa" })).not.toBeInTheDocument()
    expect(java.getByText("czeka na akceptację")).toBeInTheDocument()

    await user.click(within(rowOf("Kotlin Developer")).getByRole("button", { name: "Zdejmij Celina Wzorcowa" }))
    expect(onRemovePerson).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: 4 }),
      expect.objectContaining({ user_id: 9, proposed: false }),
    )
  })

  it("w trakcie zapisu nie da się kliknąć drugi raz", () => {
    render(<Board canStaff canDecide busyKeys={new Set(["1:7"])} />)
    const java = within(rowOf("Senior Java Developer"))
    expect(java.getByRole("button", { name: /Akceptuj propozycję/ })).toBeDisabled()
    expect(java.queryByRole("button", { name: "Zdejmij Anna Przykładowa" })).not.toBeInTheDocument()
  })

  it("propozycja przy requeście, nad którym ktoś już pracuje, jest nieaktualna i znika", () => {
    const staffed: RequestBoard = {
      ...board,
      requests: board.requests.map((r) =>
        r.job_id === 4
          ? { ...r, people: [...r.people, { ...anna, proposed: true, source: "auto" }] }
          : r,
      ),
    }
    render(<Board canStaff canDecide data={staffed} />)
    const kotlin = within(rowOf("Kotlin Developer"))
    expect(kotlin.queryByText("Anna Przykładowa")).not.toBeInTheDocument()
    expect(kotlin.queryByRole("button", { name: /Akceptuj/ })).not.toBeInTheDocument()
  })

  it("filtruje po Rekruterze — liczy się osoba, która pracuje, nie propozycja", async () => {
    const user = userEvent.setup()
    render(<Board />)
    await user.selectOptions(screen.getByLabelText("Rekruter"), "9")
    expect(screen.getByText("Pokazuję 1 z 4")).toBeInTheDocument()
    expect(screen.getByText("1 z 3 requestów")).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument()
    // Anna ma tylko propozycję — to jeszcze nie jej request.
    await user.selectOptions(screen.getByLabelText("Rekruter"), "7")
    expect(screen.getByText("Pokazuję 0 z 4")).toBeInTheDocument()
    expect(screen.getByText("Żaden request nie pasuje do ustawionych filtrów.")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Wyczyść filtry" }))
    expect(screen.getByText("Pokazuję 4 z 4")).toBeInTheDocument()
  })

  it("filtruje po Delivery Leadzie i priorytecie", async () => {
    const user = userEvent.setup()
    render(<Board />)
    const lead = screen.getByLabelText("Delivery Lead")
    expect(within(lead).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Wszyscy",
      "Gosia Delivery",
      "Henryk Kierujący",
      "Bez Delivery Leada",
    ])
    await user.selectOptions(lead, "31")
    expect(screen.getByText("Pokazuję 2 z 4")).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText("Priorytet"), "p1")
    expect(screen.getByText("Pokazuję 1 z 4")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Senior Java Developer" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Kotlin Developer" })).not.toBeInTheDocument()
  })

  it("przełącznik „Bez rekrutera” obejmuje też request z samą propozycją i mówi, ile wierszy zostanie", async () => {
    const user = userEvent.setup()
    render(<Board />)
    const toggle = screen.getByRole("button", { name: /Bez rekrutera/ })
    expect(toggle).toHaveAttribute("aria-pressed", "false")
    // Java (sama propozycja) i Tester (nikt); request z championem się nie liczy.
    expect(toggle).toHaveTextContent("Bez rekrutera2")
    await user.click(toggle)
    expect(toggle).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("Pokazuję 2 z 4")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Kotlin Developer" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "React Developer" })).not.toBeInTheDocument()
    // Liczba na przełączniku idzie za pozostałymi filtrami.
    await user.selectOptions(screen.getByLabelText("Kategoria"), "4")
    expect(toggle).toHaveTextContent("Bez rekrutera1")
    expect(screen.getByText("Pokazuję 1 z 4")).toBeInTheDocument()
  })

  it("obłożenie: „2 + 1” = requesty w pracy + propozycja, kolejność po requestach w pracy", async () => {
    const user = userEvent.setup()
    render(<Board />)
    const panel = screen.getByRole("region", { name: "Obłożenie" })
    const people = within(panel).getAllByRole("button")
    // Anna (2) przed Bartkiem i Celiną (po 1) — propozycja nie podbija kolejności.
    expect(people.map((b) => b.textContent)).toEqual([
      expect.stringContaining("Anna Przykładowa"),
      expect.stringContaining("Bartek Testowy"),
      expect.stringContaining("Celina Wzorcowa"),
    ])
    const annaRow = within(panel).getByRole("button", { name: /Anna Przykładowa/ })
    expect(within(annaRow).getByText("2 + 1")).toHaveAttribute("aria-hidden", "true")
    expect(annaRow).toHaveAccessibleName("Anna Przykładowa, 2 requesty · 1 propozycja do akceptacji")
    expect(annaRow.querySelector("[data-load-proposed]")).not.toBeNull()
    const celinaRow = within(panel).getByRole("button", { name: /Celina Wzorcowa/ })
    expect(celinaRow).toHaveAccessibleName("Celina Wzorcowa, 1 request")
    expect(within(panel).getByRole("button", { name: /Bartek Testowy/ })).toHaveAccessibleName(
      "Bartek Testowy, urlop do 29.09.2026, 1 request",
    )
    expect(celinaRow.querySelector("[data-load-proposed]")).toBeNull()
    expect(within(panel).getByText("urlop do 29.09")).toHaveAttribute("title", "Urlop do 29.09.2026")
    expect(within(panel).getByText(/„\+ 1” to propozycja automatu czekająca na akceptację/)).toBeInTheDocument()

    expect(annaRow).toHaveAttribute("aria-expanded", "false")
    await user.click(annaRow)
    expect(annaRow).toHaveAttribute("aria-expanded", "true")
    expect(within(panel).getByText(/Senior Java Developer · Klient Gamma \(propozycja\)/)).toBeInTheDocument()
  })

  it("role przydzielające dodają osobę — także tę, którą automat dopiero proponuje", async () => {
    const user = userEvent.setup()
    const onAddPerson = vi.fn()
    const { unmount } = render(<Board />)
    expect(screen.queryByRole("button", { name: /Dodaj osobę do/ })).not.toBeInTheDocument()
    unmount()
    render(<Board canStaff onAddPerson={onAddPerson} />)
    // Trzy requesty bez championa; przy championie nikogo się nie dodaje.
    expect(screen.getAllByRole("button", { name: /Dodaj osobę do/ })).toHaveLength(3)
    await user.click(screen.getByRole("button", { name: "Dodaj osobę do: Senior Java Developer" }))
    const java = within(rowOf("Senior Java Developer"))
    expect(within(java.getByLabelText("Osoba")).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Wybierz osobę",
      "Bartek Testowy (1)",
      "Anna Przykładowa (2 + 1)",
      "Celina Wzorcowa (1)",
    ])
    // Dodanie nie pyta o rolę — każda dodana osoba to rekruter.
    expect(java.queryByLabelText("Rola")).not.toBeInTheDocument()
    await user.selectOptions(java.getByLabelText("Osoba"), "7")
    await user.click(java.getByRole("button", { name: "Dodaj" }))
    expect(onAddPerson).toHaveBeenCalledWith(1, 7)
  })
})

const team: CompetenceTeam = {
  categories: [
    { id: 4, slug: "security_quality", name: "QA", requests_searching: 1, first: [], second: [] },
  ],
  unassigned: [{ user_id: 5, name: "Ewa Fikcyjna", roles: ["recruiter"], allocation_excluded: false, assignment_id: null }],
  excluded: [],
  people: [{ user_id: 5, name: "Ewa Fikcyjna", roles: ["recruiter"], allocation_excluded: false, assignment_id: null }],
  rules: { review_time: "08:30" },
}

describe("RequestBoardView — wariant daily", () => {
  function Daily() {
    const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS)
    return (
      <RequestBoardView
        board={{ ...board, changes_since: "2026-10-02T07:30:00Z" }}
        variant="daily"
        today={TODAY}
        filters={filters}
        onFilters={setFilters}
        canStaff={false}
        canDecide={false}
        onAddPerson={vi.fn()}
        onRemovePerson={vi.fn()}
        onAcceptProposal={vi.fn()}
      />
    )
  }

  it("„Zmiany od wczoraj” na górze z oknem, kategorie jako przyciski, „Następna kategoria” po grupach", async () => {
    const user = userEvent.setup()
    render(<Daily />)
    expect(screen.getAllByRole("region", { name: "Zmiany od wczoraj" })).toHaveLength(1)
    expect(screen.getByTestId("changes-since")).toHaveTextContent("od piątku 9:30")
    expect(screen.queryByRole("link", { name: "Na daily" })).not.toBeInTheDocument()

    const segments = screen.getByRole("group", { name: "Kategorie" })
    const pressed = () =>
      within(segments)
        .getAllByRole("button", { pressed: true })
        .map((b) => b.textContent)
    expect(pressed()).toEqual(["Wszystkie· 4"])

    const next = screen.getByRole("button", { name: "Następna kategoria →" })
    await user.click(next)
    expect(pressed()).toEqual(["Development· 3"])
    expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument()
    await user.click(next)
    expect(pressed()).toEqual(["QA· 1"])
    expect(screen.queryByRole("region", { name: "Development" })).not.toBeInTheDocument()
    await user.click(next)
    expect(pressed()).toEqual(["Wszystkie· 4"])

    await user.click(within(segments).getByRole("button", { name: /^QA/ }))
    expect(pressed()).toEqual(["QA· 1"])
  })

  it("kafelek ma link „Na daily”", () => {
    render(<Board />)
    expect(screen.getByRole("link", { name: "Na daily" })).toHaveAttribute("href", "/jobs/daily")
  })
})

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

  it("zasady: sama godzina przeglądu — bez progu „sourcer wystarczy”", async () => {
    const user = userEvent.setup()
    const actions = { assign: vi.fn(), remove: vi.fn(), exclude: vi.fn(), saveRules: vi.fn() }
    render(<CompetenceTeamView team={team} actions={actions} />)
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument()
    expect(screen.queryByText(/Sourcer wystarczy/)).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Zapisz zasady" }))
    expect(actions.saveRules).toHaveBeenCalledWith({ review_time: "08:30" })
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
