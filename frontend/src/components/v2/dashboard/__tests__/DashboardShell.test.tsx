import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { DashboardShell } from "@/components/v2/dashboard/DashboardShell"

describe("DashboardShell", () => {
  it("switches only between authorized presets and periods", () => {
    const onPresetChange = vi.fn()
    const onPeriodChange = vi.fn()
    render(
      <DashboardShell
        preset="admin-ops"
        period="month"
        availablePresets={["admin-ops", "finance"]}
        onPresetChange={onPresetChange}
        onPeriodChange={onPeriodChange}
      >
        <div>Treść dashboardu</div>
      </DashboardShell>,
    )

    expect(screen.getByText("Centrum operacyjne")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Delivery Lead" })).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Finanse" }))
    expect(onPresetChange).toHaveBeenCalledWith("finance")

    fireEvent.click(screen.getByRole("button", { name: "Kwartał" }))
    expect(onPeriodChange).toHaveBeenCalledWith("quarter")
  })
})
