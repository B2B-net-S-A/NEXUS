/**
 * Strefa podglądu w panelu osoby (09.10.2026): treść warsztatu trafia portalem
 * do lewej strefy powłoki, a w wąskim oknie i bez powłoki zostaje w miejscu.
 */
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PersonPanelSide,
  PersonPanelSideProvider,
  PersonPanelSideSection,
  PersonPanelSideZone,
} from "@/components/v2/person/PersonPanelSide";

const originalMatchMedia = window.matchMedia;

function mockViewport(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: wide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

const inline = (content: React.ReactNode) => <div data-testid="inline-slot">{content}</div>;

describe("PersonPanelSide", () => {
  it("bez powłoki panelu treść zostaje w miejscu", () => {
    mockViewport(true);
    render(
      <PersonPanelSide inline={inline}>
        <p>podgląd CV</p>
      </PersonPanelSide>,
    );
    expect(within(screen.getByTestId("inline-slot")).getByText("podgląd CV")).toBeInTheDocument();
  });

  it("w szerokim oknie treść trafia do lewej strefy, nie do miejsca wywołania", () => {
    mockViewport(true);
    render(
      <PersonPanelSideProvider>
        <PersonPanelSideZone />
        <div data-testid="dock">
          <PersonPanelSide inline={inline}>
            <p>podgląd CV</p>
          </PersonPanelSide>
        </div>
      </PersonPanelSideProvider>,
    );
    const zone = screen.getByTestId("person-panel-side");
    expect(within(zone).getByText("podgląd CV")).toBeInTheDocument();
    expect(within(screen.getByTestId("dock")).queryByText("podgląd CV")).toBeNull();
    expect(screen.queryByTestId("inline-slot")).toBeNull();
  });

  it("w wąskim oknie strefa jest pusta, a treść zostaje w miejscu", () => {
    mockViewport(false);
    render(
      <PersonPanelSideProvider>
        <PersonPanelSideZone />
        <div data-testid="dock">
          <PersonPanelSide inline={inline}>
            <p>podgląd CV</p>
          </PersonPanelSide>
        </div>
      </PersonPanelSideProvider>,
    );
    expect(within(screen.getByTestId("dock")).getByText("podgląd CV")).toBeInTheDocument();
    expect(within(screen.getByTestId("person-panel-side")).queryByText("podgląd CV")).toBeNull();
  });

  it("niewidoczna sekcja chowa swój podgląd, ale go nie odmontowuje", () => {
    mockViewport(true);
    const { rerender } = render(
      <PersonPanelSideProvider>
        <PersonPanelSideZone />
        <PersonPanelSideSection active={false}>
          <PersonPanelSide>
            <p>podgląd sekcji CV</p>
          </PersonPanelSide>
        </PersonPanelSideSection>
        <PersonPanelSideSection active>
          <PersonPanelSide>
            <p>podgląd sekcji Screening</p>
          </PersonPanelSide>
        </PersonPanelSideSection>
      </PersonPanelSideProvider>,
    );
    const hidden = screen.getByText("podgląd sekcji CV");
    expect(hidden).not.toBeVisible();
    expect(screen.getByText("podgląd sekcji Screening")).toBeVisible();

    rerender(
      <PersonPanelSideProvider>
        <PersonPanelSideZone />
        <PersonPanelSideSection active>
          <PersonPanelSide>
            <p>podgląd sekcji CV</p>
          </PersonPanelSide>
        </PersonPanelSideSection>
        <PersonPanelSideSection active={false}>
          <PersonPanelSide>
            <p>podgląd sekcji Screening</p>
          </PersonPanelSide>
        </PersonPanelSideSection>
      </PersonPanelSideProvider>,
    );
    // Ten sam węzeł — zmiana zakładki nie montuje podglądu od nowa.
    expect(screen.getByText("podgląd sekcji CV")).toBe(hidden);
    expect(hidden).toBeVisible();
    expect(screen.getByText("podgląd sekcji Screening")).not.toBeVisible();
  });

  it("ukryta strefa (panel nie jest w trybie dzielonym) chowa treść", () => {
    mockViewport(true);
    render(
      <PersonPanelSideProvider>
        <PersonPanelSideZone hidden />
        <PersonPanelSide>
          <p>podgląd CV</p>
        </PersonPanelSide>
      </PersonPanelSideProvider>,
    );
    expect(screen.getByText("podgląd CV")).not.toBeVisible();
  });
});
