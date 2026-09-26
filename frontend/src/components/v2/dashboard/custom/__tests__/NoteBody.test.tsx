import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { NoteBody } from "../SmallTiles"

// Runda 8 (R8-N10-5): `/\evil.com` przeglądarka czyta jak `//evil.com` —
// notatka nie może wyrenderować go jako linku wewnętrznego.
describe("NoteBody — linki", () => {
  it("ścieżka wewnętrzna i https są linkami, `/\\host` zwykłym tekstem", () => {
    render(
      <NoteBody
        config={{
          links: [
            { label: "Rekrutacje", url: "/jobs" },
            { label: "Dokumentacja", url: "https://example.com/doc" },
            { label: "Podstęp", url: "/\\evil.example.com" },
          ],
        }}
      />,
    )
    expect(screen.getByRole("link", { name: "Rekrutacje" })).toHaveAttribute("href", "/jobs")
    expect(screen.getByRole("link", { name: "Dokumentacja" })).toHaveAttribute(
      "href",
      "https://example.com/doc",
    )
    expect(screen.queryByRole("link", { name: "Podstęp" })).toBeNull()
    expect(screen.getByText("Podstęp")).toBeInTheDocument()
  })
})
