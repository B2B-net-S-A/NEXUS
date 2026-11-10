import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { TeamFilterControls } from "@/components/v2/kpi/TeamFilterControls"
import { DEFAULT_TEAM_FILTERS } from "@/lib/team-filters"

describe("TeamFilterControls", () => {
  it("switches the role and keeps the client", async () => {
    const onChange = vi.fn()
    render(
      <TeamFilterControls
        value={{ role: "recruiter", clientId: 7, clientName: "Nordea" }}
        onChange={onChange}
        clients={[{ id: 7, name: "Nordea", count: 21 }]}
      />,
    )
    expect(screen.getByRole("button", { name: "Rekruterzy" })).toHaveAttribute("aria-pressed", "true")
    await userEvent.click(screen.getByRole("button", { name: "Delivery Leadzi" }))
    expect(onChange).toHaveBeenCalledWith({ role: "delivery_lead", clientId: 7, clientName: "Nordea" })
  })

  it("hides the role buttons when the screen fixes the role", () => {
    render(
      <TeamFilterControls
        value={DEFAULT_TEAM_FILTERS}
        onChange={() => {}}
        roles={["recruiter"]}
        clients={[]}
      />,
    )
    expect(screen.queryByRole("group", { name: "Rola" })).not.toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "Klient" })).toBeInTheDocument()
  })

  it("keeps a client chosen in another period on the list", () => {
    render(
      <TeamFilterControls
        value={{ role: "all", clientId: 3, clientName: "Orlen S.A." }}
        onChange={() => {}}
        clients={[{ id: 7, name: "Nordea", count: 2 }]}
      />,
    )
    expect(screen.getByRole("combobox", { name: "Klient" })).toHaveTextContent("Orlen S.A.")
  })

  it("has no client picker without a client list", () => {
    render(<TeamFilterControls value={DEFAULT_TEAM_FILTERS} onChange={() => {}} />)
    expect(screen.queryByRole("combobox", { name: "Klient" })).not.toBeInTheDocument()
  })
})
