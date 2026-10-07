/**
 * Obudowa panelu osoby (jeden panel osoby, 04.10.2026): ta sama `aside`
 * w wąskim, szerokim i dzielonym trybie (0424), podkład zamyka najwyższą
 * warstwę, ukryty panel nie traci treści.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonPanelShell } from "@/components/v2/person/PersonPanelShell";

describe("PersonPanelShell", () => {
  it("wąski: 380 px, podkład tylko na tablecie", () => {
    render(
      <PersonPanelShell size="dock" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-[380px]");
    expect(panel).not.toHaveAttribute("data-wide");
    expect(panel).toHaveAttribute("data-size", "dock");
    expect(panel).toHaveAttribute("data-help", "jobs.person.dock");
    expect(screen.getByTestId("pipeline-dock-backdrop").className).toContain("lg:hidden");
  });

  it("szeroki: 760 px, podkład na każdej szerokości i klik go zamyka", () => {
    const onBackdropClick = vi.fn();
    render(
      <PersonPanelShell size="wide" chromeTop={64} onBackdropClick={onBackdropClick}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-[760px]");
    expect(panel).toHaveAttribute("data-wide");
    expect(panel).toHaveAttribute("data-size", "wide");
    expect(panel.style.top).toBe("64px");
    const backdrop = screen.getByTestId("pipeline-dock-backdrop");
    expect(backdrop.className).not.toContain("lg:hidden");
    fireEvent.click(backdrop);
    expect(onBackdropClick).toHaveBeenCalledTimes(1);
  });

  it("dzielony (0424): do 1200 px, liczy się jako szeroki", () => {
    render(
      <PersonPanelShell size="split" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-[min(1200px,100vw)]");
    expect(panel).toHaveAttribute("data-wide");
    expect(panel).toHaveAttribute("data-size", "split");
    expect(screen.getByTestId("pipeline-dock-backdrop").className).not.toContain("lg:hidden");
  });

  it("ukryty: bez podkładu, treść zostaje zamontowana", () => {
    render(
      <PersonPanelShell size="dock" hidden chromeTop={null} onBackdropClick={vi.fn()}>
        <textarea defaultValue="niewysłana notatka" aria-label="notatka" />
      </PersonPanelShell>,
    );
    expect(screen.queryByTestId("pipeline-dock-backdrop")).toBeNull();
    expect(screen.getByLabelText("notatka", { selector: "textarea" })).toHaveValue("niewysłana notatka");
    expect(screen.getByLabelText("notatka", { selector: "textarea" })).not.toBeVisible();
  });
});
