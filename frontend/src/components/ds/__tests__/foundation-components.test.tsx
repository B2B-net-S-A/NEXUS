import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { Badge } from "@/components/ui/badge"

import { EntityHeader } from "../EntityHeader"
import { FilterBar, resultCountLabel } from "../FilterBar"
import { KeyFacts } from "../KeyFacts"
import {
  getMatchScoreTone,
  MatchScoreBadge,
  normalizeMatchScore,
} from "../MatchScoreBadge"
import { PageHeader } from "../PageHeader"
import { TabbedNav } from "../TabbedNav"

describe("MatchScoreBadge", () => {
  it.each([
    [100, "success"],
    [75, "success"],
    [74, "warning"],
    [50, "warning"],
    [49, "neutral"],
    [0, "neutral"],
  ] as const)("maps %s to the %s tone", (score, tone) => {
    expect(getMatchScoreTone(score)).toBe(tone)
  })

  it("clamps the visible score and exposes an explicit accessible label", () => {
    render(<MatchScoreBadge score={108.6} />)

    expect(screen.getByText("100/100")).toBeInTheDocument()
    expect(screen.getByLabelText("Dopasowanie: 100 na 100")).toBeInTheDocument()
    expect(normalizeMatchScore(-10)).toBe(0)
  })

  it("renders a useful empty state instead of a numeric score", () => {
    render(<MatchScoreBadge score={null} showLabel />)

    expect(screen.getByText("Dopasowanie: Brak wyniku")).toBeInTheDocument()
  })
})

describe("KeyFacts", () => {
  it("uses semantic description-list elements and preserves empty values", () => {
    render(
      <KeyFacts
        facts={[
          { id: "availability", label: "Dostępność", value: "Od zaraz" },
          { id: "owner", label: "Opiekun", value: null },
        ]}
      />,
    )

    expect(screen.getByText("Dostępność").closest("dt")).not.toBeNull()
    expect(screen.getByText("Od zaraz").tagName).toBe("DD")
    expect(screen.getByText("—").tagName).toBe("DD")
  })
})

describe("EntityHeader", () => {
  it("supports drawer heading semantics without changing the visual hierarchy", () => {
    render(
      <EntityHeader
        headingLevel={2}
        density="compact"
        title="Jan Kowalski"
        subtitle="Cloud Architect"
        badges={<Badge variant="success">Aktywny</Badge>}
        actions={<button type="button">Przypisz</button>}
      />,
    )

    expect(screen.getByRole("heading", { level: 2, name: "Jan Kowalski" })).toBeInTheDocument()
    expect(screen.getByText("Cloud Architect")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Przypisz" })).toBeInTheDocument()
  })
})

describe("PageHeader", () => {
  it("keeps compact density additive and renders the existing API", () => {
    render(
      <PageHeader
        density="compact"
        eyebrow="Kandydaci"
        title="Baza kandydatów"
        description="Opis"
      />,
    )

    const title = screen.getByRole("heading", { level: 1, name: "Baza kandydatów" })
    expect(title).toHaveClass("text-xl")
    expect(screen.getByText("Opis")).toBeInTheDocument()
  })
})

describe("FilterBar", () => {
  it("supports immediate input, Enter submit and a dedicated clear action", () => {
    const onChange = vi.fn()
    const onSubmit = vi.fn()
    const onClear = vi.fn()

    render(
      <FilterBar
        search={{
          value: "cloud",
          onChange,
          onSubmit,
          onClear,
          ariaLabel: "Szukaj kandydatów",
        }}
        resultCount={22}
      />,
    )

    const search = screen.getByRole("searchbox", { name: "Szukaj kandydatów" })
    fireEvent.change(search, { target: { value: "devops" } })
    fireEvent.keyDown(search, { key: "Enter" })
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść wyszukiwanie" }))

    expect(onChange).toHaveBeenCalledWith("devops")
    expect(onSubmit).toHaveBeenCalledOnce()
    expect(onClear).toHaveBeenCalledOnce()
    expect(screen.getByText("22 wyniki")).toBeInTheDocument()
  })

  it.each([
    [1, "wynik"],
    [2, "wyniki"],
    [12, "wyników"],
    [24, "wyniki"],
  ] as const)("pluralizes %s as %s", (count, label) => {
    expect(resultCountLabel(count)).toBe(label)
  })
})

describe("TabbedNav", () => {
  it("labels the tablist, supports horizontal overflow and reports selection", async () => {
    const onValueChange = vi.fn()
    const user = userEvent.setup()

    render(
      <TabbedNav
        tabs={[
          { value: "summary", label: "Podsumowanie" },
          { value: "activity", label: "Aktywność", count: 3 },
        ]}
        value="summary"
        onValueChange={onValueChange}
        ariaLabel="Sekcje profilu"
        overflow="scroll"
      />,
    )

    const tablist = screen.getByRole("tablist", { name: "Sekcje profilu" })
    expect(tablist.parentElement).toHaveClass("overflow-x-auto")
    await user.click(screen.getByRole("tab", { name: /Aktywność/ }))
    expect(onValueChange).toHaveBeenCalledWith("activity")
  })
})
