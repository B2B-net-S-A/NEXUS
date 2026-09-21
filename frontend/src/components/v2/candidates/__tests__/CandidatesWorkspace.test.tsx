import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidatesWorkspace } from "@/components/v2/candidates/CandidatesWorkspace";
import { candidatesModeHref, parseCandidatesMode } from "@/lib/candidates-mode";

// Trzy tryby to trzy DUŻE, osobno przetestowane ekrany — tu sprawdzamy
// wyłącznie przełączanie i przekazanie tekstu między trybami.
let searchParams = new URLSearchParams();
const push = vi.fn((href: string) => {
  searchParams = new URLSearchParams(href.split("?")[1] ?? "");
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

vi.mock("@/components/v2/pages/CandidatesListV2", () => ({
  CandidatesListV2: () => <div data-testid="mode-list" />,
}));

const searchProps = vi.fn();
vi.mock("@/components/v2/pages/CandidateSearchView", () => ({
  CandidateSearchView: (props: {
    onUseAsRequest?: (text: string) => void;
    persistUrlParams?: Record<string, string>;
    hideHeader?: boolean;
  }) => {
    searchProps(props);
    return (
      <button
        type="button"
        data-testid="mode-search"
        onClick={() => props.onUseAsRequest?.("Szukamy Java developera\n\n\nKraków, B2B")}
      >
        przenieś
      </button>
    );
  },
}));

vi.mock("@/components/talent-radar/TalentRadarWorkspace", () => ({
  TalentRadarWorkspace: (props: { embedded?: boolean; initialText?: string }) => (
    <div data-testid="mode-request" data-embedded={String(!!props.embedded)}>
      {props.initialText ?? ""}
    </div>
  ),
}));

beforeEach(() => {
  searchParams = new URLSearchParams();
  push.mockClear();
  searchProps.mockClear();
});

describe("lib/candidates-mode", () => {
  it("nieznany albo pusty tryb to lista", () => {
    expect(parseCandidatesMode(null)).toBe("list");
    expect(parseCandidatesMode("")).toBe("list");
    expect(parseCandidatesMode("radar")).toBe("list");
    expect(parseCandidatesMode("search")).toBe("search");
    expect(parseCandidatesMode("request")).toBe("request");
  });

  it("adres trybu przenosi stan starego adresu bez dublowania mode", () => {
    expect(candidatesModeHref("list")).toBe("/candidates");
    expect(candidatesModeHref("request")).toBe("/candidates?mode=request");
    expect(
      candidatesModeHref("search", new URLSearchParams("s=abc&job=12&mode=list")),
    ).toBe("/candidates?mode=search&s=abc&job=12");
  });
});

describe("CandidatesWorkspace", () => {
  it("bez parametru pokazuje listę i trzy zakładki trybów", () => {
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-list")).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Baza", "Wyszukiwanie", "Z treści requestu"]);
  });

  it("tryb wyszukiwania zachowuje mode w adresie i nie rysuje własnego nagłówka", () => {
    searchParams = new URLSearchParams("mode=search");
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-search")).toBeInTheDocument();
    const props = searchProps.mock.calls[0][0];
    expect(props.persistUrlParams).toEqual({ mode: "search" });
    expect(props.hideHeader).toBe(true);
  });

  it("tryb requestu osadza radar bez jego nagłówka strony", () => {
    searchParams = new URLSearchParams("mode=request");
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-request")).toHaveAttribute("data-embedded", "true");
  });

  it("„Szukaj jak z requestu” przenosi tekst do radaru przez stan, nie adres", () => {
    searchParams = new URLSearchParams("mode=search");
    const { rerender } = render(<CandidatesWorkspace />);
    act(() => {
      fireEvent.click(screen.getByTestId("mode-search"));
    });
    expect(push).toHaveBeenCalledWith("/candidates?mode=request");
    rerender(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-request")).toHaveTextContent("Szukamy Java developera");
    expect(push.mock.calls[0][0]).not.toContain("Java");
  });
});
