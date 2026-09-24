import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({ default: { get: vi.fn(), patch: vi.fn() } }))

import { RequestReviewView } from "@/components/v2/request-review/RequestReview"
import type { ReviewResponse } from "@/lib/api/requestAllocation"

const row = {
  job_id: 1,
  title: "Tester manualny",
  client_name: "Klient Beta",
  delivery_lead_name: null,
  deadline: null,
  state: "finished" as const,
  state_label: "Zakończony",
  last_work_at: null,
  last_cv_at: null,
  sent_total: 0,
  applications_14d: 0,
  suggested_state: null,
  suggestion_reason: "",
}

function renderView(data: ReviewResponse, onMore = vi.fn()) {
  render(
    <RequestReviewView
      data={data}
      tab="finished"
      onTab={vi.fn()}
      mine={false}
      onMine={vi.fn()}
      q=""
      onQ={vi.fn()}
      actions={{ setState: vi.fn(), dropChampion: vi.fn() }}
      onMore={onMore}
    />,
  )
  return onMore
}

const counts = { to_review: 0, searching: 0, champion: 0, client_silent: 0, finished: 3900 }

describe("Porządek w requestach: długa zakładka idzie stronami", () => {
  it("pokazuje „Pokaż więcej” i ile z ilu, gdy są kolejne strony", async () => {
    const onMore = renderView({ tab: "finished", counts, rows: [row], total: 3900, has_more: true })
    expect(screen.getByText("Pokazano 1 z 3900.")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }))
    expect(onMore).toHaveBeenCalledTimes(1)
  })

  it("bez kolejnych stron nie ma przycisku", () => {
    renderView({ tab: "finished", counts, rows: [row], total: 1, has_more: false })
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).toBeNull()
  })
})
