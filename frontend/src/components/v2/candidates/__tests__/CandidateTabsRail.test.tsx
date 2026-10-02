/**
 * `CandidateTabsRail` — szyna ostatnio otwieranych kandydatów na liście
 * i w profilu. Do 02.10.2026 była widoczna dopiero od 1536 px; na laptopie
 * jest teraz zakładką w marginesie strony, z której lista kandydatów wysuwa
 * się NAD treść (nie spycha jej i niczego nie zapisuje). Od 1536 px — bez zmian.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateTabsRail } from "@/components/v2/candidates/CandidateTabsRail";
import { useTabsStore } from "@/store/tabs";

const COLLAPSE_KEY = "nexus.candidateTabsRail.collapsed";

const routerPush = vi.fn();
const nav = { pathname: "/candidates" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
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

beforeEach(() => {
  window.localStorage.clear();
  routerPush.mockReset();
  nav.pathname = "/candidates";
  useTabsStore.setState({
    tabs: [
      { id: "candidate-11", type: "candidate", entityId: 11, title: "Anna Przykładowa", url: "/candidates/11" },
      { id: "candidate-12", type: "candidate", entityId: 12, title: "Jan Testowy", url: "/candidates/12" },
      { id: "job-501", type: "job", entityId: 501, title: "Rekrutacja", url: "/jobs/501" },
    ],
    activeTabId: "candidate-11",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CandidateTabsRail — laptop (poniżej 1536 px)", () => {
  it("zakładka z licznikiem; lista kandydatów otwiera się jako nakładka i nic nie zapisuje", async () => {
    stubViewportWidth(1280);
    const user = userEvent.setup();
    render(<CandidateTabsRail />);

    const show = await screen.findByRole("button", { name: "Pokaż pasek kandydatów" });
    expect(show).toHaveTextContent("2");
    expect(show).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Kandydaci")).not.toBeInTheDocument();

    await user.click(show);
    expect(show).toHaveAttribute("aria-expanded", "true");
    const panel = await screen.findByRole("complementary", {
      name: "Ostatnio wyświetlani kandydaci",
    });
    expect(panel).toHaveClass("absolute");
    expect(screen.getByText("Ostatnio wyświetlani: 2")).toBeInTheDocument();
    // Pasek zostaje na miejscu — nakładka go nie zastępuje.
    expect(screen.getByRole("button", { name: "Pokaż pasek kandydatów" })).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSE_KEY)).toBeNull();

    await user.keyboard("{Escape}");
    expect(screen.queryByText("Ostatnio wyświetlani: 2")).not.toBeInTheDocument();
  });

  it("zapisane „rozwiń” nie zabiera szerokości na laptopie; klik w kandydata otwiera profil", async () => {
    stubViewportWidth(1366);
    window.localStorage.setItem(COLLAPSE_KEY, "0");
    const user = userEvent.setup();
    render(<CandidateTabsRail />);

    const show = await screen.findByRole("button", { name: "Pokaż pasek kandydatów" });
    expect(screen.queryByText("Kandydaci")).not.toBeInTheDocument();

    await user.click(show);
    await user.click(await screen.findByRole("button", { name: /Jan Testowy/ }));
    expect(routerPush).toHaveBeenCalledWith("/candidates/12");
    expect(window.localStorage.getItem(COLLAPSE_KEY)).toBe("0");
  });

  it("klik obok nakładki ją zamyka", async () => {
    stubViewportWidth(1280);
    const user = userEvent.setup();
    render(
      <div>
        <CandidateTabsRail />
        <p>treść listy</p>
      </div>,
    );
    await user.click(await screen.findByRole("button", { name: "Pokaż pasek kandydatów" }));
    expect(await screen.findByText("Ostatnio wyświetlani: 2")).toBeInTheDocument();
    await user.click(screen.getByText("treść listy"));
    expect(screen.queryByText("Ostatnio wyświetlani: 2")).not.toBeInTheDocument();
  });
});

describe("CandidateTabsRail — od 1536 px bez zmian", () => {
  it("bez zapisanego wyboru: zwinięta poniżej 1600 px, rozwinięta od 1600 px", async () => {
    stubViewportWidth(1536);
    const narrow = render(<CandidateTabsRail />);
    expect(await screen.findByRole("button", { name: "Pokaż pasek kandydatów" })).toBeInTheDocument();
    expect(screen.queryByText("Kandydaci")).not.toBeInTheDocument();
    narrow.unmount();

    stubViewportWidth(1920);
    render(<CandidateTabsRail />);
    const panel = await screen.findByRole("complementary", {
      name: "Ostatnio wyświetlani kandydaci",
    });
    // W układzie strony, nie jako nakładka.
    expect(panel).not.toHaveClass("absolute");
    expect(screen.getByText("Kandydaci")).toBeInTheDocument();
  });

  it("„Pokaż” i „Ukryj” zapisują wybór pod dotychczasowym kluczem", async () => {
    stubViewportWidth(1536);
    const user = userEvent.setup();
    render(<CandidateTabsRail />);

    await user.click(await screen.findByRole("button", { name: "Pokaż pasek kandydatów" }));
    expect(await screen.findByText("Kandydaci")).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSE_KEY)).toBe("0");

    await user.click(screen.getByRole("button", { name: "Ukryj pasek kandydatów" }));
    expect(await screen.findByRole("button", { name: "Pokaż pasek kandydatów" })).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSE_KEY)).toBe("1");
  });

  it("podświetla kandydata z adresu i pokazuje tylko karty kandydatów", async () => {
    stubViewportWidth(1920);
    nav.pathname = "/candidates/12";
    render(<CandidateTabsRail />);
    const active = await screen.findByRole("button", { name: /Jan Testowy/ });
    expect(active).toHaveClass("bg-primary/10");
    expect(screen.getByRole("button", { name: /Anna Przykładowa/ })).not.toHaveClass("bg-primary/10");
    expect(screen.queryByText("Rekrutacja")).not.toBeInTheDocument();
  });

  it("bez otwartych kart kandydatów nie renderuje nic", () => {
    useTabsStore.setState({ tabs: [], activeTabId: null });
    const { container } = render(<CandidateTabsRail />);
    expect(container).toBeEmptyDOMElement();
  });
});
