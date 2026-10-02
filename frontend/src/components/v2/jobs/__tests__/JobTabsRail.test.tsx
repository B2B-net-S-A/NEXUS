/**
 * `JobTabsRail` — szyna „Otwarte karty" na stronach rekrutacji i (od
 * 02.10.2026) na liście `/jobs`.
 *
 * Fala 3 przeniosła stan zwinięcia z ręcznego `useState`/`localStorage`
 * (klucz `nexus.jobTabsRail.collapsed`) na klucz `nexus.jobTabsRail.collapsed.v2`
 * i domyślnie ZWINIĘTĄ szynę na stronie rekrutacji — pierwsze testy pilnują
 * właśnie tego. Niżej: lista ma własny stan domyślny (rozwinięta od 1920 px),
 * a zapisany wybór wygrywa na obu stronach.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobTabsRail } from "@/components/v2/jobs/JobTabsRail";
import { JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/job-tabs-rail-preferences";
import { useTabsStore } from "@/store/tabs";

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  usePathname: () => "/jobs/501",
}));

const oneJobTab = {
  id: "job-501",
  type: "job" as const,
  entityId: 501,
  title: "Programista Python",
  url: "/jobs/501",
};

beforeEach(() => {
  window.localStorage.clear();
  routerPush.mockReset();
  useTabsStore.setState({ tabs: [oneJobTab], activeTabId: "job-501" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Okno o podanej szerokości: `matchMedia("(min-width: N px)")` odpowiada jak przeglądarka. */
function stubViewportWidth(width: number) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => {
      const min = /min-width:\s*(\d+)px/.exec(query);
      return {
        matches: min ? width >= Number(min[1]) : false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      };
    }),
  );
}

describe("JobTabsRail — preferencja zwinięcia", () => {
  it("bez zapisanej preferencji startuje ZWINIĘTA (pasek z licznikiem, nie lista)", async () => {
    render(<JobTabsRail />);

    expect(
      await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.queryByText("Rekrutacje")).not.toBeInTheDocument();
  });

  it('"0" pod kluczem v2 rozwija szynę', async () => {
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    render(<JobTabsRail />);

    expect(await screen.findByText("Rekrutacje")).toBeInTheDocument();
    expect(screen.getByText("Otwarte karty: 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pokaż pasek rekrutacji" }),
    ).not.toBeInTheDocument();
  });

  it('stary klucz (bez ".v2") jest ignorowany — szyna zostaje zwinięta mimo zapisanego "0"', async () => {
    window.localStorage.setItem("nexus.jobTabsRail.collapsed", "0");
    render(<JobTabsRail />);

    expect(
      await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Rekrutacje")).not.toBeInTheDocument();
  });

  it('kliknięcie "Pokaż" rozwija szynę i zapisuje preferencję pod nowym kluczem', async () => {
    const user = userEvent.setup();
    render(<JobTabsRail />);

    await user.click(
      await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" }),
    );

    expect(await screen.findByText("Rekrutacje")).toBeInTheDocument();
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBe("0");
  });

  it('kliknięcie "Ukryj" w rozwiniętej szynie zwija ją z powrotem', async () => {
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    const user = userEvent.setup();
    render(<JobTabsRail />);

    await user.click(
      await screen.findByRole("button", { name: "Ukryj pasek rekrutacji" }),
    );

    expect(
      await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBe("1");
  });
});

describe("JobTabsRail — samo-ukrywanie", () => {
  it("bez otwartych kart rekrutacji nie renderuje nic", () => {
    act(() => {
      useTabsStore.setState({ tabs: [], activeTabId: null });
    });
    const { container } = render(<JobTabsRail />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("JobTabsRail — okno węższe niż 1536 px (laptop z Windows)", () => {
  function mockNarrowScreen() {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
  }

  it("zapisane „rozwiń” nie zabiera szerokości: pasek, a lista jako nakładka bez zapisu", async () => {
    mockNarrowScreen();
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    const user = userEvent.setup();
    render(<JobTabsRail />);

    const open = await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" });
    expect(screen.queryByText("Rekrutacje")).not.toBeInTheDocument();

    await user.click(open);
    expect(await screen.findByText("Otwarte karty: 1")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByText("Otwarte karty: 1")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBe("0");
    vi.unstubAllGlobals();
  });
});

describe("JobTabsRail — lista rekrutacji (`variant=\"list\"`)", () => {
  it("bez zapisanej preferencji: od 1920 px rozwinięta, a przycisk „Ukryj” zapisuje wybór", async () => {
    stubViewportWidth(1920);
    const user = userEvent.setup();
    render(<JobTabsRail variant="list" />);

    expect(await screen.findByText("Otwarte karty: 1")).toBeInTheDocument();
    // Sam stan domyślny niczego nie zapisuje.
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Ukryj pasek rekrutacji" }));
    expect(await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" })).toBeInTheDocument();
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBe("1");
  });

  it("bez zapisanej preferencji: poniżej 1920 px (1536–1919) zwinięty pasek w układzie strony", async () => {
    stubViewportWidth(1600);
    const user = userEvent.setup();
    render(<JobTabsRail variant="list" />);

    const show = await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" });
    expect(screen.queryByText("Otwarte karty: 1")).not.toBeInTheDocument();

    // Od 1536 px „Pokaż” rozwija szynę na stałe (zapis), nie jako nakładkę.
    await user.click(show);
    expect(await screen.findByText("Otwarte karty: 1")).toBeInTheDocument();
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBe("0");
  });

  it("zapisana preferencja wygrywa z szerokością okna — w obie strony", async () => {
    stubViewportWidth(1920);
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "1");
    const view = render(<JobTabsRail variant="list" />);
    expect(await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" })).toBeInTheDocument();
    expect(screen.queryByText("Otwarte karty: 1")).not.toBeInTheDocument();
    view.unmount();

    stubViewportWidth(1600);
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    render(<JobTabsRail variant="list" />);
    expect(await screen.findByText("Otwarte karty: 1")).toBeInTheDocument();
  });

  it("laptop (poniżej 1536 px): pasek, a lista kart jako nakładka — bez zapisu", async () => {
    stubViewportWidth(1280);
    const user = userEvent.setup();
    render(<JobTabsRail variant="list" />);

    await user.click(await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" }));
    const panel = await screen.findByRole("complementary", { name: "Otwarte rekrutacje" });
    // Nakładka nie zabiera miejsca w układzie: jest pozycjonowana nad treścią.
    expect(panel).toHaveClass("absolute");
    expect(window.localStorage.getItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY)).toBeNull();

    // Klik w kartę otwiera rekrutację.
    await user.click(screen.getByRole("button", { name: /Programista Python/ }));
    expect(routerPush).toHaveBeenCalledWith("/jobs/501");
  });

  it("strona rekrutacji przy 1920 px zostaje zwinięta — stan domyślny listy jej nie dotyczy", async () => {
    stubViewportWidth(1920);
    render(<JobTabsRail />);
    expect(await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" })).toBeInTheDocument();
    expect(screen.queryByText("Otwarte karty: 1")).not.toBeInTheDocument();
  });
});

describe("JobTabsRail — karty", () => {
  it("„×” przy karcie zamyka ją bez nawigacji, „×” w nagłówku zamyka wszystkie", async () => {
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    useTabsStore.setState({
      tabs: [
        oneJobTab,
        { id: "job-502", type: "job", entityId: 502, title: "Tester", url: "/jobs/502" },
        { id: "candidate-9", type: "candidate", entityId: 9, title: "Kandydat", url: "/candidates/9" },
      ],
      activeTabId: "job-501",
    });
    const user = userEvent.setup();
    render(<JobTabsRail />);

    // Szyna rekrutacji pokazuje tylko rekrutacje.
    expect(await screen.findByText("Otwarte karty: 2")).toBeInTheDocument();
    expect(screen.queryByText("Kandydat")).not.toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Zamknij kartę" })[1]);
    expect(routerPush).not.toHaveBeenCalled();
    expect(useTabsStore.getState().tabs.map((t) => t.id)).toEqual(["job-501", "candidate-9"]);

    await user.click(screen.getByRole("button", { name: "Zamknij wszystkie karty" }));
    expect(useTabsStore.getState().tabs.map((t) => t.id)).toEqual(["candidate-9"]);
  });

  it("z klawiatury: Enter na wierszu otwiera kartę, Enter na „×” ją zamyka (nie otwiera)", async () => {
    window.localStorage.setItem(JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY, "0");
    const user = userEvent.setup();
    render(<JobTabsRail />);

    const row = await screen.findByRole("button", { name: /Programista Python/ });
    row.focus();
    await user.keyboard("{Enter}");
    expect(routerPush).toHaveBeenCalledWith("/jobs/501");
    routerPush.mockReset();

    // Klawisz na przycisku w środku wiersza też dociera do wiersza — do
    // 02.10.2026 otwierał kartę, którą użytkownik właśnie zamykał.
    screen.getByRole("button", { name: "Zamknij kartę" }).focus();
    await user.keyboard("{Enter}");
    expect(routerPush).not.toHaveBeenCalled();
    expect(useTabsStore.getState().tabs).toEqual([]);
  });
});
