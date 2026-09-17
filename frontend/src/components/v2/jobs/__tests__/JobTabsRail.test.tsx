/**
 * `JobTabsRail` — szyna „Otwarte karty" na trasach szczegółów rekrutacji.
 *
 * Fala 3 przeniosła stan zwinięcia z ręcznego `useState`/`localStorage`
 * (klucz `nexus.jobTabsRail.collapsed`) na `useLocalStorageFlag` z nowym
 * kluczem `nexus.jobTabsRail.collapsed.v2` i domyślnie ZWINIĘTĄ szyną —
 * te testy pilnują właśnie tej zmiany (a nie samej listy kart, która nie
 * jest tu ruszana).
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
