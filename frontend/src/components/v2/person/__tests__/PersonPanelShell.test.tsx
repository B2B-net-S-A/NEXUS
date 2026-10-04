/**
 * Obudowa panelu osoby (jeden panel osoby, 04.10.2026): ta sama `aside`
 * w wąskim i szerokim trybie, podkład zamyka najwyższą warstwę, ukryty panel
 * nie traci treści.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonPanelShell } from "@/components/v2/person/PersonPanelShell";

describe("PersonPanelShell", () => {
  it("wąski: 380 px, podkład tylko na tablecie", () => {
    render(
      <PersonPanelShell wide={false} chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-[380px]");
    expect(panel).not.toHaveAttribute("data-wide");
    expect(panel).toHaveAttribute("data-help", "jobs.person.dock");
    expect(screen.getByTestId("pipeline-dock-backdrop").className).toContain("lg:hidden");
  });

  it("szeroki: 760 px, podkład na każdej szerokości i klik go zamyka", () => {
    const onBackdropClick = vi.fn();
    render(
      <PersonPanelShell wide chromeTop={64} onBackdropClick={onBackdropClick}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-[760px]");
    expect(panel).toHaveAttribute("data-wide");
    expect(panel.style.top).toBe("64px");
    const backdrop = screen.getByTestId("pipeline-dock-backdrop");
    expect(backdrop.className).not.toContain("lg:hidden");
    fireEvent.click(backdrop);
    expect(onBackdropClick).toHaveBeenCalledTimes(1);
  });

  it("ukryty: bez podkładu, treść zostaje zamontowana", () => {
    render(
      <PersonPanelShell wide={false} hidden chromeTop={null} onBackdropClick={vi.fn()}>
        <textarea defaultValue="niewysłana notatka" aria-label="notatka" />
      </PersonPanelShell>,
    );
    expect(screen.queryByTestId("pipeline-dock-backdrop")).toBeNull();
    expect(screen.getByLabelText("notatka", { selector: "textarea" })).toHaveValue("niewysłana notatka");
    expect(screen.getByLabelText("notatka", { selector: "textarea" })).not.toBeVisible();
  });
});
