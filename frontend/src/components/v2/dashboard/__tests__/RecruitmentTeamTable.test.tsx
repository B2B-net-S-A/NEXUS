import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { RecruitmentTeamTable } from "@/components/v2/dashboard/RecruitmentTeamTable"
import type {
  RecruitmentTeamTable as TableData,
  RecruitmentTeamTableRow,
} from "@/lib/dashboard-v2-api"

function row(
  overrides: Partial<RecruitmentTeamTableRow> & { user_id: number; name: string },
): RecruitmentTeamTableRow {
  return {
    role: "recruiter",
    verifications: 0,
    recommendations: 0,
    interviews: 0,
    acceptances: 0,
    placements: 0,
    cv_to_base: 0,
    precision_pct: null,
    precision_verified_30d: 0,
    precision_sent_30d: 0,
    ...overrides,
  }
}

function tableData(rows: RecruitmentTeamTableRow[]): TableData {
  return {
    precision_target_pct: 75,
    rows,
    totals: {
      verifications: rows.reduce((a, r) => a + r.verifications, 0),
      recommendations: rows.reduce((a, r) => a + r.recommendations, 0),
      interviews: rows.reduce((a, r) => a + r.interviews, 0),
      acceptances: rows.reduce((a, r) => a + r.acceptances, 0),
      placements: rows.reduce((a, r) => a + r.placements, 0),
      cv_to_base: rows.reduce((a, r) => a + r.cv_to_base, 0),
      precision_pct: null,
      people: rows.length,
    },
  }
}

describe("RecruitmentTeamTable", () => {
  it("aggregates footer precision from visible rows (v30/s30 sums, 0.1 rounding)", () => {
    // 44+16=60 verified, 31+14=45 sent → 75.0% (dokładnie próg → text-success)
    const data = tableData([
      row({
        user_id: 1,
        name: "Osoba A",
        precision_verified_30d: 44,
        precision_sent_30d: 31,
      }),
      row({
        user_id: 2,
        name: "Osoba B",
        precision_verified_30d: 16,
        precision_sent_30d: 14,
      }),
    ])
    render(<RecruitmentTeamTable table={data} />)

    const footer = screen.getByText(/Razem \(2\)/).closest("tr")!
    expect(within(footer).getByText("75%")).toBeInTheDocument()
  })

  it("footer recomputes when the role filter narrows visible rows", () => {
    const data = tableData([
      row({
        user_id: 1,
        name: "Rekruterka",
        role: "recruiter",
        verifications: 10,
        precision_verified_30d: 10,
        precision_sent_30d: 9,
      }),
      row({
        user_id: 2,
        name: "Sourcerka",
        role: "sourcer",
        verifications: 5,
        precision_verified_30d: 2,
        precision_sent_30d: 1,
      }),
    ])
    render(<RecruitmentTeamTable table={data} />)

    fireEvent.change(screen.getByLabelText("Filtruj po roli"), {
      target: { value: "recruiter" },
    })

    expect(screen.queryByText("Sourcerka")).not.toBeInTheDocument()
    const footer = screen.getByText(/Razem \(1\)/).closest("tr")!
    expect(within(footer).getByText("10")).toBeInTheDocument()
    expect(within(footer).getByText("90%")).toBeInTheDocument()
  })

  it("keeps unknown roles filterable (appended after the known hierarchy)", () => {
    const data = tableData([
      row({ user_id: 1, name: "Znana", role: "recruiter" }),
      row({ user_id: 2, name: "Przyszła Rola", role: "quality_lead" }),
    ])
    render(<RecruitmentTeamTable table={data} />)

    const select = screen.getByLabelText("Filtruj po roli") as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)
    expect(values).toContain("quality_lead")

    fireEvent.change(select, { target: { value: "quality_lead" } })
    expect(screen.getByText("Przyszła Rola")).toBeInTheDocument()
    expect(screen.queryByText("Znana")).not.toBeInTheDocument()
  })

  it("sorts by column on header click and hides rows below the precision floor", () => {
    const data = tableData([
      row({ user_id: 1, name: "Mało", verifications: 3, precision_verified_30d: 3 }),
      row({ user_id: 2, name: "Dużo", verifications: 30, precision_verified_30d: 2 }),
    ])
    render(<RecruitmentTeamTable table={data} />)

    // precision poniżej progu 5 weryfikacji/30d → „—", nigdy liczba
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2)

    fireEvent.click(screen.getByRole("button", { name: /Weryfikacje/ }))
    const cells = screen
      .getAllByRole("row")
      .slice(1, 3)
      .map((r) => within(r).getAllByRole("cell")[0].textContent)
    expect(cells[0]).toContain("Dużo")
  })
})
