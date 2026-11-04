/**
 * Układ sekcji `/candidates`: szyna ostatnio otwieranych kandydatów na liście
 * i w profilu. Do 02.10.2026 była widoczna dopiero od 1536 px; teraz na
 * laptopie jest zakładką w marginesie strony (lista kandydatów wysuwa się
 * nad treść), która nie zabiera liście szerokości.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CandidatesLayout from "@/app/candidates/layout";
import { useTabsStore } from "@/store/tabs";

const nav = { pathname: "/candidates" };

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
    <CandidatesLayout>
      <p>treść strony</p>
    </CandidatesLayout>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  useTabsStore.setState({
    tabs: [
      { id: "candidate-11", type: "candidate", entityId: 11, title: "Anna Przykładowa", url: "/candidates/11" },
    ],
    activeTabId: null,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("app/candidates/layout — szyna ostatnio otwieranych kandydatów", () => {
  it("laptop (1280 px): zakładka dostępna od 1024 px i bez kosztu szerokości", async () => {
    stubViewportWidth(1280);
    renderAt("/candidates");
    const show = await screen.findByRole("button", { name: "Pokaż pasek kandydatów" });
    // Opakowanie zakładki (z nakładką w środku) niesie klasy widoczności.
    const tab = show.closest("aside") as HTMLElement;
    const wrapper = tab.parentElement as HTMLElement;
    expect(wrapper).toHaveClass("hidden", "lg:flex");
    expect(wrapper).not.toHaveClass("2xl:flex");
    // Zero szerokości w układzie: zakładka wisi w lewym marginesie strony,
    // a odstęp szyna–lista pojawia się dopiero od 1536 px. Lista kandydatów
    // przy 1280 px przewija się w poziomie — pasek 40 px zabierałby jej 56 px.
    expect(wrapper).toHaveClass("w-0");
    expect(wrapper).not.toHaveClass("w-10");
    expect(tab).toHaveClass("absolute", "-left-6");
    expect(wrapper.parentElement).toHaveClass("2xl:gap-6");
    expect(wrapper.parentElement).not.toHaveClass("gap-4");
    expect(screen.queryByText("Kandydaci")).not.toBeInTheDocument();
  });

  it("lista i profil mają szynę; od 1920 px bez zapisanej preferencji jest rozwinięta", async () => {
    stubViewportWidth(1920);
    for (const pathname of ["/candidates", "/candidates/11"]) {
      const view = renderAt(pathname);
      const rail = await screen.findByRole("complementary", {
        name: "Ostatnio wyświetlani kandydaci",
      });
      expect(rail).toHaveTextContent("Anna Przykładowa");
      expect(rail).toHaveClass("hidden", "lg:flex", "sticky");
      view.unmount();
    }
  });

  it("wyszukiwarka, porównanie i import renderują się bez szyny", () => {
    stubViewportWidth(1920);
    for (const pathname of ["/candidates/search", "/candidates/compare", "/candidates/bulk-import"]) {
      const view = renderAt(pathname);
      expect(screen.getByText("treść strony")).toBeInTheDocument();
      expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
      view.unmount();
    }
  });
});
