/**
 * Obudowa panelu osoby (jeden panel osoby, 04.10.2026): ta sama `aside`
 * w czterech rozmiarach (dok, szeroki, dzielony ze strefą podglądu po lewej,
 * przegląd DL — 09.10.2026), podkład zamyka najwyższą warstwę, ukryty panel
 * nie traci treści.
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

  it("dzielony (09.10.2026): cała szerokość, strefa podglądu po lewej i stała kolumna po prawej", () => {
    render(
      <PersonPanelShell size="split" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-none");
    expect(panel).toHaveAttribute("data-wide");
    expect(panel).toHaveAttribute("data-cover");
    expect(panel).toHaveAttribute("data-size", "split");
    expect(screen.getByTestId("pipeline-dock-backdrop").className).not.toContain("lg:hidden");

    const zone = screen.getByTestId("person-panel-side");
    expect(zone).not.toHaveAttribute("hidden");
    const column = screen.getByTestId("person-panel-column");
    expect(column.className).toContain("lg:w-[460px]");
    expect(column.className).toContain("2xl:w-[520px]");
    expect(column).toContainElement(screen.getByText("treść"));
    // Strefa stoi w DOM przed kolumną — kolejność tabulatora = lewo → prawo.
    expect(zone.compareDocumentPosition(column) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("przegląd DL: cała szerokość bez strefy podglądu", () => {
    render(
      <PersonPanelShell size="review" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel.className).toContain("max-w-none");
    expect(panel).toHaveAttribute("data-cover");
    expect(panel).toHaveAttribute("data-size", "review");
    expect(screen.getByTestId("person-panel-side")).toHaveAttribute("hidden");
    expect(screen.getByTestId("person-panel-column").className).not.toContain("lg:w-[460px]");
  });

  it("dok i tryb szeroki nie zakrywają menu i trzymają strefę ukrytą, ale zamontowaną", () => {
    const { rerender } = render(
      <PersonPanelShell size="dock" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    const zone = screen.getByTestId("person-panel-side");
    expect(panel).not.toHaveAttribute("data-cover");
    expect(zone).toHaveAttribute("hidden");

    rerender(
      <PersonPanelShell size="split" chromeTop={null} onBackdropClick={vi.fn()}>
        <p>treść</p>
      </PersonPanelShell>,
    );
    // Ten sam węzeł strefy i ta sama kolumna — zmiana rozmiaru niczego nie odmontowuje.
    expect(screen.getByTestId("person-panel-side")).toBe(zone);
    expect(zone).not.toHaveAttribute("hidden");
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
