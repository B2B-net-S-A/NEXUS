/**
 * Układ sekcji `/jobs`: szyna „Otwarte karty” stoi na stronach rekrutacji
 * i — od 02.10.2026 — na liście. Lista ma własny stan domyślny szyny
 * (rozwinięta od 1920 px okna), strona rekrutacji zostaje przy zwiniętej.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import JobsLayout from "@/app/jobs/layout";
import { useTabsStore } from "@/store/tabs";

const nav = { pathname: "/jobs" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => nav.pathname,
}));

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

function renderAt(pathname: string) {
  nav.pathname = pathname;
  return render(
    <JobsLayout>
      <p>treść strony</p>
    </JobsLayout>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  useTabsStore.setState({
    tabs: [{ id: "job-501", type: "job", entityId: 501, title: "Programista Python", url: "/jobs/501" }],
    activeTabId: null,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("app/jobs/layout — szyna otwartych kart", () => {
  it("lista `/jobs` ma szynę; przy 1920 px bez zapisanej preferencji jest rozwinięta", async () => {
    stubViewportWidth(1920);
    renderAt("/jobs");
    expect(screen.getByText("treść strony")).toBeInTheDocument();
    const rail = await screen.findByRole("complementary", { name: "Otwarte rekrutacje" });
    expect(rail).toHaveTextContent("Programista Python");
    // Od 1024 px, przyklejona do góry; na telefonie szyny nie ma.
    expect(rail).toHaveClass("hidden", "lg:flex", "sticky");
  });

  it("lista na laptopie (1280 px): zakładka z licznikiem w marginesie — bez kosztu szerokości", async () => {
    stubViewportWidth(1280);
    renderAt("/jobs");
    const show = await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" });
    expect(show).toHaveTextContent("1");
    expect(screen.queryByRole("complementary", { name: "Otwarte rekrutacje" })).not.toBeInTheDocument();
    // Tabela rekrutacji przy 1280 px ledwo mieści się w oknie: zakładka wisi
    // w marginesie strony, opakowanie ma zerową szerokość i nie ma odstępu.
    const tab = show.closest("aside") as HTMLElement;
    const wrapper = tab.parentElement as HTMLElement;
    expect(tab).toHaveClass("absolute", "-left-6");
    expect(wrapper).toHaveClass("w-0");
    expect(wrapper.parentElement).not.toHaveClass("gap-4");
  });

  it("strona rekrutacji na laptopie zostaje przy pasku 40 px w układzie strony", async () => {
    stubViewportWidth(1280);
    renderAt("/jobs/501");
    const show = await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" });
    const wrapper = (show.closest("aside") as HTMLElement).parentElement as HTMLElement;
    expect(wrapper).toHaveClass("w-10");
    expect(wrapper.parentElement).toHaveClass("gap-4", "lg:gap-6");
  });

  it("strona rekrutacji przy 1920 px zostaje przy zwiniętej szynie (bez zmian)", async () => {
    stubViewportWidth(1920);
    renderAt("/jobs/501");
    expect(await screen.findByRole("button", { name: "Pokaż pasek rekrutacji" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Otwarte rekrutacje" })).not.toBeInTheDocument();
  });

  it("formularz nowej rekrutacji i „Porządek w requestach” renderują się bez szyny", () => {
    stubViewportWidth(1920);
    for (const pathname of ["/jobs/new", "/jobs/review-states"]) {
      const view = renderAt(pathname);
      expect(screen.getByText("treść strony")).toBeInTheDocument();
      expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("bez otwartych kart lista zajmuje całą szerokość — szyna nie renderuje nic", () => {
    stubViewportWidth(1920);
    useTabsStore.setState({ tabs: [], activeTabId: null });
    renderAt("/jobs");
    expect(screen.getByText("treść strony")).toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });
});
