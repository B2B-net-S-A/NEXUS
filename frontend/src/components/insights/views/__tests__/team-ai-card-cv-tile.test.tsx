/**
 * Kafelek „CV do klienta z karty AI” w Insights → Zespół (decyzja Artura 22.11.2026).
 *
 * Reguły pod ochroną:
 *
 * 1. Bieżący tydzień na górze z udziałem i celem 100%, 4 poprzednie w tabeli
 *    od najnowszego.
 * 2. Tydzień bez wysyłek to „—”, nie 0%.
 * 3. Awaria zapytania nie wygląda jak 0% ani pusty stan — mówi o błędzie
 *    tekstem z `apiErrorMessage` i daje „Spróbuj ponownie”.
 * 4. Pusty stan tylko po udanym zapytaniu.
 */
import * as React from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}))

import { TeamAiCardCvTile } from "../team/TeamAiCardCvTile"
import type { AiCardCvShare, AiCardCvWeek } from "@/lib/insights-ai-card"

function week(
  start: string,
  end: string,
  cv: number,
  fromCard: number,
  pct: number | null,
  inProgress = false,
): AiCardCvWeek {
  return {
    week_start: start,
    week_end: end,
    cv_sent: cv,
    from_ai_card: fromCard,
    share_pct: pct,
    in_progress: inProgress,
  }
}

const DATA: AiCardCvShare = {
  window_from: "2026-10-19",
  window_to: "2026-11-20",
  target_pct: 100,
  weeks: [
    week("2026-10-19", "2026-10-25", 0, 0, null),
    week("2026-10-26", "2026-11-01", 12, 3, 25),
    week("2026-11-02", "2026-11-08", 20, 5, 25),
    week("2026-11-09", "2026-11-15", 10, 4, 40),
    week("2026-11-16", "2026-11-22", 8, 2, 25, true),
  ],
}

function renderTile() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <TeamAiCardCvTile />
    </QueryClientProvider>,
  )
}

describe("TeamAiCardCvTile", () => {
  beforeEach(() => {
    mocks.get.mockReset()
  })

  it("pokazuje szkielet w trakcie ładowania", () => {
    mocks.get.mockReturnValue(new Promise(() => {}))
    const { container } = renderTile()
    expect(container.querySelector(".animate-pulse")).not.toBeNull()
    expect(screen.queryByText("CV do klienta z karty AI")).toBeNull()
  })

  it("pokazuje bieżący tydzień z celem i cztery poprzednie od najnowszego", async () => {
    mocks.get.mockResolvedValue({ data: DATA })
    renderTile()

    expect(await screen.findByText("CV do klienta z karty AI")).toBeTruthy()
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/insights/recruitment/cv-from-ai-card",
    )
    expect(screen.getByText(/Ten tydzień · 16\.11–22\.11 · trwa/)).toBeTruthy()
    expect(screen.getByText("2 z 8 CV z karty AI · cel 100%")).toBeTruthy()

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1)
    expect(rows).toHaveLength(4)
    expect(rows[0].textContent).toContain("09.11–15.11")
    expect(rows[0].textContent).toContain("40%")
    // Tydzień bez wysyłek: „—”, nie 0%.
    expect(rows[3].textContent).toContain("19.10–25.10")
    expect(rows[3].textContent).toContain("—")
    expect(rows[3].textContent).not.toContain("0%")
  })

  it("awaria nie wygląda jak 0% — komunikat i ponowienie", async () => {
    mocks.get.mockRejectedValueOnce({
      response: { status: 500, data: { detail: "Baza nie odpowiada" } },
    })
    renderTile()

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain("Baza nie odpowiada")
    expect(screen.queryByText(/%/)).toBeNull()

    mocks.get.mockResolvedValue({ data: DATA })
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }))
    await waitFor(() =>
      expect(screen.getByText("2 z 8 CV z karty AI · cel 100%")).toBeTruthy(),
    )
  })

  it("awaria bez treści z serwera daje własny komunikat kafelka", async () => {
    mocks.get.mockRejectedValueOnce(new Error("Network Error"))
    renderTile()

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain(
      "Nie udało się policzyć udziału CV z karty AI",
    )
  })

  it("pusty stan po udanym zapytaniu bez żadnej wysyłki", async () => {
    mocks.get.mockResolvedValue({
      data: {
        ...DATA,
        weeks: DATA.weeks.map((w) => ({
          ...w,
          cv_sent: 0,
          from_ai_card: 0,
          share_pct: null,
        })),
      },
    })
    renderTile()

    expect(
      await screen.findByText(/Od 19\.10 do 20\.11 nikt nie wysłał CV do klienta/),
    ).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
  })
})
