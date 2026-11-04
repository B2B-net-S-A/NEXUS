import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { AllocationRulesView } from "@/components/v2/competence-team/AllocationRulesPanel"
import { DEFAULT_TEAM_RULES } from "@/lib/allocation-rules"
import type { AllocationPreview, AllocationPreviewSide } from "@/lib/api/requestAllocation"

const side = (over: Partial<AllocationPreviewSide> = {}): AllocationPreviewSide => ({
  pool: 40,
  empty: 0,
  new_people: 0,
  new_requests: 0,
  waiting: 0,
  proposals_dropped: 0,
  at_limit: 0,
  team: 13,
  people: [],
  auto_waits_for_leave: false,
  ...over,
})

const preview: AllocationPreview = {
  today: side(),
  draft: side({
    pool: 186,
    empty: 144,
    new_people: 144,
    new_requests: 144,
    waiting: 2,
    people: [{ user_id: 7, name: "Ewa Fikcyjna", p1_now: 6, new: 13, new_p1: 0 }],
  }),
}

function renderView(overrides: Partial<Parameters<typeof AllocationRulesView>[0]> = {}) {
  const props = {
    saved: { rules: DEFAULT_TEAM_RULES, mode: "auto" as const },
    preview,
    previewError: null,
    previewLoading: false,
    history: [],
    historyError: null,
    saving: false,
    onDraft: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  }
  render(<AllocationRulesView {...props} />)
  return props
}

describe("AllocationRulesView", () => {
  it("bez zmian zapis jest wyłączony", () => {
    renderView()
    expect(screen.getByRole("button", { name: "Zapisz zasady" })).toBeDisabled()
    expect(screen.getByText("Nic nie zmieniasz.")).toBeInTheDocument()
  })

  it("zmiana zasad: szkic idzie do podglądu, zapis wysyła tryb i zasady", async () => {
    const user = userEvent.setup()
    const props = renderView()
    await user.click(screen.getByRole("checkbox", { name: "Także P2" }))
    await user.selectOptions(screen.getByLabelText("Limit na osobę"), "6")
    await user.click(screen.getByRole("radio", { name: "Proponuje" }))
    expect(props.onDraft).toHaveBeenLastCalledWith({
      rules: { ...DEFAULT_TEAM_RULES, include_p2: true, max_load: 6 },
      mode: "shadow",
    })
    const impact = screen.getByRole("complementary", { name: "Co się zmieni" })
    expect(within(impact).getByText("Zmieniasz 3:")).toBeInTheDocument()
    await user.click(within(impact).getByRole("button", { name: "Zapisz zasady" }))
    expect(props.onSave).toHaveBeenCalledWith({
      rules: { ...DEFAULT_TEAM_RULES, include_p2: true, max_load: 6 },
      mode: "shadow",
    })
  })

  it("podgląd: liczby z przebiegu na sucho, różnica i kto dostanie najwięcej", () => {
    renderView()
    const impact = screen.getByRole("complementary", { name: "Co się zmieni" })
    expect(within(impact).getByText("Nowych przydziałów").nextSibling).toHaveTextContent(
      "144(+144)",
    )
    expect(within(impact).getByText("Ewa Fikcyjna")).toBeInTheDocument()
    expect(within(impact).getByText(/Już przydzielonych nikt nie traci/)).toBeInTheDocument()
  })

  it("awaria podglądu nie wygląda jak zero", () => {
    renderView({ preview: undefined, previewError: new Error("boom") })
    expect(screen.getByRole("alert")).toHaveTextContent(/podglądu|boom/)
    expect(screen.queryByText("Nowych przydziałów")).not.toBeInTheDocument()
  })

  it("historia: kto i co zmienił", () => {
    renderView({
      history: [
        {
          at: "2026-10-29T10:00:00Z",
          actor_name: "Olaf Testowy",
          changed: { max_load: [null, 6] },
        },
      ],
    })
    expect(screen.getByText(/Olaf Testowy/)).toBeInTheDocument()
    expect(screen.getByText("Limit P1 na osobę: bez limitu → 6")).toBeInTheDocument()
  })
})
