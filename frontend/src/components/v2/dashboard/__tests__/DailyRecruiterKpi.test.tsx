import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { DailyRecruiterKpi } from "@/components/v2/dashboard/DailyRecruiterKpi"
import { useMyKpis } from "@/hooks/useMyKpis"

vi.mock("@/hooks/useMyKpis", () => ({ useMyKpis: vi.fn() }))

const useKpis = vi.mocked(useMyKpis)

describe("DailyRecruiterKpi", () => {
  it("shows current, target, remaining and progress for today's first verifications", () => {
    useKpis.mockReturnValue({
      data: [
        {
          kpi_id: "daily_first_verifications",
          period: "day",
          title_pl: "Pierwsze weryfikacje",
          description_pl: "Pierwsza weryfikacja kandydata",
          target: 4,
          current: 2,
          progress_pct: 50,
          state: "on_track",
          deadline_hours_left: 5.2,
        },
      ],
      isLoading: false,
    } as ReturnType<typeof useMyKpis>)

    render(<DailyRecruiterKpi />)

    const card = screen.getByTestId("daily-recruiter-kpi")
    expect(within(card).getByText("Twój cel na dziś")).toBeInTheDocument()
    expect(within(card).getByText("z 4 weryfikacji")).toBeInTheDocument()
    expect(within(card).getByText("Zostało")).toBeInTheDocument()
    expect(within(card).getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "50",
    )
    expect(
      within(card).getByText(/6 h do końca dnia pracy/),
    ).toBeInTheDocument()
  })

  it("uses the workday deadline wording in the final hour", () => {
    useKpis.mockReturnValue({
      data: [
        {
          kpi_id: "daily_first_verifications",
          period: "day",
          title_pl: "Pierwsze weryfikacje",
          description_pl: "Pierwsza weryfikacja kandydata",
          target: 4,
          current: 3,
          progress_pct: 75,
          state: "behind",
          deadline_hours_left: 0.5,
        },
      ],
      isLoading: false,
    } as ReturnType<typeof useMyKpis>)

    render(<DailyRecruiterKpi />)

    expect(
      screen.getByText("Mniej niż godzina do końca dnia pracy", {
        exact: false,
      }),
    ).toBeInTheDocument()
  })

  it("states that the workday is over after the deadline", () => {
    useKpis.mockReturnValue({
      data: [
        {
          kpi_id: "daily_first_verifications",
          period: "day",
          title_pl: "Pierwsze weryfikacje",
          description_pl: "Pierwsza weryfikacja kandydata",
          target: 4,
          current: 2,
          progress_pct: 50,
          state: "missed",
          deadline_hours_left: 0,
        },
      ],
      isLoading: false,
    } as ReturnType<typeof useMyKpis>)

    render(<DailyRecruiterKpi />)

    expect(
      screen.getByText("Dzień pracy zakończony", { exact: false }),
    ).toBeInTheDocument()
  })

  it("does not invent a target for a role without the daily KPI", () => {
    useKpis.mockReturnValue(
      { data: [], isLoading: false } as unknown as ReturnType<typeof useMyKpis>,
    )

    const { container } = render(<DailyRecruiterKpi />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows a retry action when the daily target cannot be loaded", async () => {
    const refetch = vi.fn()
    useKpis.mockReturnValue(
      {
        data: undefined,
        isLoading: false,
        isError: true,
        refetch,
      } as unknown as ReturnType<typeof useMyKpis>,
    )

    render(<DailyRecruiterKpi />)

    expect(
      screen.getByText("Nie udało się pobrać Twojego celu na dziś."),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }))
    expect(refetch).toHaveBeenCalledOnce()
  })
})
