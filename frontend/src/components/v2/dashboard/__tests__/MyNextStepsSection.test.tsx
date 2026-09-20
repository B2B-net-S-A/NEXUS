import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { MyNextStepsSection } from "@/components/v2/dashboard/MyNextStepsSection"
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared"
import { getMyNextSteps, type MyNextStepsResponse } from "@/lib/my-next-steps-api"

vi.mock("@/lib/my-next-steps-api", () => ({
  myNextStepsQueryKey: ["my-next-steps"],
  getMyNextSteps: vi.fn(),
}))

const getSteps = vi.mocked(getMyNextSteps)

function item(id: number, name: string, days = 1, extra: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id,
    candidate_id: 100 + id,
    stage: "new",
    name,
    lastname: "Test",
    days_in_stage: days,
    ...extra,
  }
}

function column(stage: string, items: KanbanItem[], extra: Partial<KanbanColumn> = {}): KanbanColumn {
  return { stage, category: "internal", count: items.length, items, ...extra }
}

function response(jobs: MyNextStepsResponse["jobs"], truncated = false): MyNextStepsResponse {
  return { jobs, truncated }
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MyNextStepsSection />
    </QueryClientProvider>,
  )
}

describe("MyNextStepsSection", () => {
  beforeEach(() => {
    getSteps.mockReset()
  })

  it("groups cards by recruitment and links each person to the board dock", async () => {
    getSteps.mockResolvedValue(
      response([
        {
          job_id: 9,
          title: "Java Developer",
          client_name: "Bank SA",
          view: {
            job_id: 9,
            columns: [
              column("new", [item(1, "Anna", 0)]),
              column("screening", [item(2, "Borys", 9, { stage: "screening" })]),
            ],
          },
        },
        {
          job_id: 12,
          title: "QA Engineer",
          client_name: null,
          view: { job_id: 12, columns: [column("new", [item(3, "Cezary", 0)])] },
        },
      ]),
    )

    renderSection()

    const javaHeading = await screen.findByRole("heading", { name: /Java Developer/ }, { timeout: 5000 })
    expect(javaHeading).toHaveTextContent("Bank SA")
    const javaList = screen.getByRole("list", { name: /Java Developer/ })
    expect(within(javaList).getAllByRole("listitem")).toHaveLength(2)
    expect(within(javaList).getByRole("link", { name: /Anna Test/ })).toHaveAttribute(
      "href",
      "/jobs/9?candidate=101",
    )
    expect(screen.getByRole("list", { name: /QA Engineer/ })).toBeInTheDocument()

    // Zaległy screening: ton „due” i pierwszy na liście.
    const due = within(javaList).getByText("Uzupełnij arkusz screeningu")
    expect(due.closest("[data-tone]")).toHaveAttribute("data-tone", "due")
    expect(within(javaList).getAllByRole("listitem")[0]).toHaveTextContent("Borys")
  })

  it("skips hired and closed cards", async () => {
    getSteps.mockResolvedValue(
      response([
        {
          job_id: 9,
          title: "Java Developer",
          client_name: null,
          view: {
            job_id: 9,
            columns: [
              column("new", [item(1, "Anna", 0)]),
              column("hired", [item(4, "Dorota", 3, { stage: "hired" })], {
                category: "terminal",
                terminal_type: "hired",
              }),
              column("rejected", [item(5, "Emil", 3, { stage: "rejected" })], {
                category: "terminal",
                terminal_type: "rejected",
              }),
            ],
          },
        },
      ]),
    )

    renderSection()

    expect(await screen.findByRole("link", { name: /Anna Test/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText(/Dorota/)).toBeNull()
    expect(screen.queryByText(/Emil/)).toBeNull()
  })

  it("shows five cards per recruitment and expands the rest", async () => {
    const items = Array.from({ length: 7 }, (_, i) => item(i + 1, `Osoba${i + 1}`, 0))
    getSteps.mockResolvedValue(
      response(
        [
          {
            job_id: 9,
            title: "Java Developer",
            client_name: null,
            view: { job_id: 9, columns: [column("new", items)] },
          },
        ],
        true,
      ),
    )

    renderSection()

    const list = await screen.findByRole("list", { name: /Java Developer/ }, { timeout: 5000 })
    expect(within(list).getAllByRole("listitem")).toHaveLength(5)
    await userEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie (7)" }))
    expect(within(list).getAllByRole("listitem")).toHaveLength(7)
    expect(screen.getByText(/Pokazano 1 rekrutacji z najbliższym terminem/)).toBeInTheDocument()
  })

  it("renders the empty state only after a successful response", async () => {
    getSteps.mockResolvedValue(response([]))
    renderSection()
    expect(await screen.findByText("Brak kart do obsłużenia", {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it("renders a 403 as a permission notice, not as an empty list", async () => {
    getSteps.mockImplementation(() =>
      Promise.reject(Object.assign(new Error("Forbidden"), { response: { status: 403 } })),
    )
    renderSection()
    expect(await screen.findByText("Brak uprawnień", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText("Brak kart do obsłużenia")).toBeNull()
  })
})

describe("cardCountLabel", () => {
  it("odmienia liczbę kart po polsku", async () => {
    const { cardCountLabel } = await import("../MyNextStepsSection");
    expect([1, 2, 3, 5, 12, 22, 25].map(cardCountLabel)).toEqual([
      "1 karta", "2 karty", "3 karty", "5 kart", "12 kart", "22 karty", "25 kart",
    ]);
  });
});
