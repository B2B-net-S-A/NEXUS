/**
 * Strefa podglądu w panelu osoby (09.10.2026): treść warsztatu trafia portalem
 * do lewej strefy powłoki, a w wąskim oknie i bez powłoki zostaje w miejscu.
 * Od 13.10.2026 strefa trzyma też układ podglądu (zwinięte CV / wymagania),
 * pamiętany per osoba.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PersonPanelColumn,
  PersonPanelSide,
  PersonPanelSideProvider,
  PersonPanelSideSection,
  PersonPanelSideZone,
  usePersonPreviewCollapse,
} from "@/components/v2/person/PersonPanelSide";
import { useAuthStore } from "@/store/auth";

const originalMatchMedia = window.matchMedia;

function mockViewport(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: wide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  window.localStorage.clear();
  useAuthStore.setState({ user: { id: 7 } as never, hydrated: true });
});

afterEach(() => {
  window.matchMedia = originalMatchMedia;
  useAuthStore.setState({ user: null });
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

/** Odczyt i przełączniki układu, jak w podglądzie kandydata. */
function LayoutProbe() {
  const collapse = usePersonPreviewCollapse();
  if (!collapse) return <p>bez zwijania</p>;
  return (
    <div>
      <p data-testid="layout">{`cv:${collapse.layout.cvCollapsed} info:${collapse.layout.infoCollapsed}`}</p>
      <button type="button" onClick={() => collapse.setLayout({ cvCollapsed: !collapse.layout.cvCollapsed })}>
        CV
      </button>
      <button type="button" onClick={() => collapse.setLayout({ infoCollapsed: !collapse.layout.infoCollapsed })}>
        info
      </button>
    </div>
  );
}

function Panel({ split = true }: { split?: boolean }) {
  return (
    <PersonPanelSideProvider>
      <PersonPanelSideZone hidden={!split} />
      <PersonPanelColumn split={split}>
        <LayoutProbe />
      </PersonPanelColumn>
    </PersonPanelSideProvider>
  );
}

describe("układ podglądu (zwijanie CV i wymagań, 13.10.2026)", () => {
  it("bez powłoki panelu i w wąskim oknie nie ma zwijania", () => {
    mockViewport(true);
    render(<LayoutProbe />);
    expect(screen.getByText("bez zwijania")).toBeInTheDocument();

    mockViewport(false);
    render(
      <PersonPanelSideProvider>
        <LayoutProbe />
      </PersonPanelSideProvider>,
    );
    expect(screen.getAllByText("bez zwijania")).toHaveLength(2);
  });

  it("domyślnie oba otwarte: kolumna panelu 460/520 px, strefa wypełnia resztę", () => {
    mockViewport(true);
    render(<Panel />);
    expect(screen.getByTestId("layout")).toHaveTextContent("cv:false info:false");
    const column = screen.getByTestId("person-panel-column");
    expect(column.className).toContain("lg:w-[460px]");
    expect(column.className).toContain("2xl:w-[520px]");
    expect(screen.getByTestId("person-panel-side").className).toContain("flex-1");
  });

  it("zwinięte CV: wymagania i panel po połowie (D2)", () => {
    mockViewport(true);
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "CV" }));

    expect(screen.getByTestId("layout")).toHaveTextContent("cv:true info:false");
    const column = screen.getByTestId("person-panel-column");
    expect(column.className).toContain("lg:w-[calc((100%-2.75rem)/2)]");
    expect(column.className).not.toContain("lg:w-[460px]");
    expect(column.className).not.toContain("2xl:w-[520px]");
    expect(screen.getByTestId("person-panel-side").className).not.toContain("lg:w-[5.5rem]");
  });

  it("zwinięte same wymagania nie ruszają kolumny panelu", () => {
    mockViewport(true);
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "info" }));

    expect(screen.getByTestId("layout")).toHaveTextContent("cv:false info:true");
    expect(screen.getByTestId("person-panel-column").className).toContain("lg:w-[460px]");
  });

  it("oba zwinięte: dwie listwy w strefie, panel na resztę ekranu", () => {
    mockViewport(true);
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "CV" }));
    fireEvent.click(screen.getByRole("button", { name: "info" }));

    const zone = screen.getByTestId("person-panel-side");
    expect(zone.className).toContain("lg:w-[5.5rem]");
    expect(zone.className).toContain("lg:flex-none");
    const column = screen.getByTestId("person-panel-column");
    expect(column.className).toContain("lg:flex-1");
    expect(column.className).not.toContain("lg:w-[calc((100%-2.75rem)/2)]");
  });

  it("dok (panel nie jest dzielony) ignoruje układ podglądu", () => {
    mockViewport(true);
    window.localStorage.setItem(
      "nexus:person-preview-layout:7",
      JSON.stringify({ cvCollapsed: true, infoCollapsed: true }),
    );
    render(<Panel split={false} />);
    const column = screen.getByTestId("person-panel-column");
    expect(column.className).not.toContain("lg:w-");
    expect(column.className).not.toContain("lg:flex-1");
  });

  it("układ zapisuje się pod kluczem osoby i wraca po ponownym otwarciu panelu (D4)", () => {
    mockViewport(true);
    const { unmount } = render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "CV" }));
    expect(JSON.parse(window.localStorage.getItem("nexus:person-preview-layout:7") ?? "null")).toEqual({
      cvCollapsed: true,
      infoCollapsed: false,
    });
    unmount();

    render(<Panel />);
    expect(screen.getByTestId("layout")).toHaveTextContent("cv:true info:false");
  });

  it("inna osoba w tej samej przeglądarce ma własny układ", () => {
    mockViewport(true);
    window.localStorage.setItem(
      "nexus:person-preview-layout:7",
      JSON.stringify({ cvCollapsed: true, infoCollapsed: false }),
    );
    render(<Panel />);
    expect(screen.getByTestId("layout")).toHaveTextContent("cv:true info:false");

    act(() => {
      useAuthStore.setState({ user: { id: 8 } as never });
    });
    expect(screen.getByTestId("layout")).toHaveTextContent("cv:false info:false");
  });
});
