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
  usePersonPanelConversationMode,
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
      columnWidth: null,
      compact: false,
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

/** Tryb rozmowy widziany z wnętrza kolumny (dok osoby, „Screening dla”). */
function ModeProbe() {
  const mode = usePersonPanelConversationMode();
  if (!mode) return <p>bez trybu rozmowy</p>;
  return (
    <button type="button" aria-pressed={mode.on} onClick={mode.toggle}>
      Tryb rozmowy
    </button>
  );
}

function AdjustablePanel({ split = true }: { split?: boolean }) {
  return (
    <PersonPanelSideProvider>
      <PersonPanelSideZone hidden={!split} />
      <PersonPanelColumn split={split}>
        <LayoutProbe />
        <ModeProbe />
      </PersonPanelColumn>
    </PersonPanelSideProvider>
  );
}

/** jsdom nie liczy układu: panel 1280 px, kolumna w swojej bieżącej szerokości. */
function mockPanelBox(panelWidth = 1280) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const el = this as HTMLElement;
    const columnWidth = Number.parseInt(el.style?.width?.match(/min\((\d+)px/)?.[1] ?? "460", 10);
    const width = el.dataset?.testid === "person-panel-column" ? columnWidth : panelWidth;
    return { x: 0, y: 0, top: 0, left: 0, bottom: 720, right: width, width, height: 720, toJSON: () => ({}) } as DOMRect;
  });
}

function savedLayout(): Record<string, unknown> | null {
  return JSON.parse(window.localStorage.getItem("nexus:person-preview-layout:7") ?? "null");
}

describe("szerokość kolumny i tryb rozmowy (29.10.2026)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uchwyt krawędzi stoi tylko w rozwiniętym panelu przy widocznym CV", () => {
    mockViewport(true);
    const { unmount } = render(<AdjustablePanel />);
    expect(screen.getByRole("separator", { name: "Szerokość panelu osoby" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CV" }));
    // Zwinięte CV: kolumna zostaje regułą D2 (połowa ekranu), bez uchwytu.
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(screen.getByTestId("person-panel-column").className).toContain("lg:w-[calc((100%-2.75rem)/2)]");
    unmount();

    render(<AdjustablePanel split={false} />);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  it("w wąskim oknie nie ma ani uchwytu, ani trybu rozmowy", () => {
    mockViewport(false);
    render(<AdjustablePanel />);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(screen.getByText("bez trybu rozmowy")).toBeInTheDocument();
  });

  it("przeciągnięcie krawędzi poszerza kolumnę, pamięta szerokość i zostawia CV co najmniej 360 px", () => {
    mockViewport(true);
    mockPanelBox();
    render(<AdjustablePanel />);
    const handle = screen.getByRole("separator", { name: "Szerokość panelu osoby" });

    fireEvent.pointerDown(handle, { clientX: 820 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 640 }));
    });
    const column = screen.getByTestId("person-panel-column");
    expect(column.style.width).toMatch(/^min\(640px, (calc\()?100% - 360px\)?\)$/);
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 100 }));
      window.dispatchEvent(new MouseEvent("pointerup"));
    });
    // 1280 − 360 px na CV = najszerzej 920 px.
    expect(column.style.width).toMatch(/^min\(920px, (calc\()?100% - 360px\)?\)$/);
    expect(column.className).not.toContain("lg:w-[460px]");
    expect(savedLayout()).toMatchObject({ columnWidth: 920 });
  });

  it("nie da się zwęzić poniżej 400 px; dwuklik wraca do domyślnej szerokości", () => {
    mockViewport(true);
    mockPanelBox();
    render(<AdjustablePanel />);
    const handle = screen.getByRole("separator", { name: "Szerokość panelu osoby" });

    fireEvent.pointerDown(handle, { clientX: 820 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 1200 }));
      window.dispatchEvent(new MouseEvent("pointerup"));
    });
    expect(savedLayout()).toMatchObject({ columnWidth: 400 });

    fireEvent.doubleClick(handle);
    const column = screen.getByTestId("person-panel-column");
    expect(column.style.width).toBe("");
    expect(column.className).toContain("lg:w-[460px]");
    expect(savedLayout()).toMatchObject({ columnWidth: null });
  });

  it("strzałki zmieniają szerokość o 40 px, Home wraca do domyślnej", () => {
    mockViewport(true);
    mockPanelBox();
    render(<AdjustablePanel />);
    const handle = screen.getByRole("separator", { name: "Szerokość panelu osoby" });

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "500");
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "540");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle).toHaveAttribute("aria-valuenow", "500");
    fireEvent.keyDown(handle, { key: "Home" });
    expect(handle).not.toHaveAttribute("aria-valuenow");
    expect(handle).toHaveAttribute("aria-valuetext", "domyślna");
  });

  it("zapamiętana szerokość wraca po ponownym otwarciu panelu", () => {
    mockViewport(true);
    window.localStorage.setItem("nexus:person-preview-layout:7", JSON.stringify({ columnWidth: 700 }));
    render(<AdjustablePanel />);
    expect(screen.getByTestId("person-panel-column").style.width).toMatch(/^min\(700px, (calc\()?100% - 360px\)?\)$/);
  });

  it("tryb rozmowy jest domyślnie wyłączony, przełącznik ustawia data-compact i pamięta wybór", () => {
    mockViewport(true);
    const { unmount } = render(<AdjustablePanel />);
    const toggle = screen.getByRole("button", { name: "Tryb rozmowy" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("person-panel-column")).not.toHaveAttribute("data-compact");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Tryb rozmowy" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("person-panel-column")).toHaveAttribute("data-compact", "");
    expect(savedLayout()).toMatchObject({ compact: true });
    unmount();

    render(<AdjustablePanel />);
    expect(screen.getByTestId("person-panel-column")).toHaveAttribute("data-compact", "");
  });

  it("dok (panel nie jest dzielony) nie ma trybu rozmowy, nawet zapamiętanego", () => {
    mockViewport(true);
    window.localStorage.setItem("nexus:person-preview-layout:7", JSON.stringify({ compact: true, columnWidth: 700 }));
    render(<AdjustablePanel split={false} />);
    expect(screen.getByText("bez trybu rozmowy")).toBeInTheDocument();
    const column = screen.getByTestId("person-panel-column");
    expect(column).not.toHaveAttribute("data-compact");
    expect(column.style.width).toBe("");
  });
});
