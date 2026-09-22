import { act, fireEvent, render, screen } from "@testing-library/react";
import type { AnchorHTMLAttributes } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidatesWorkspace } from "@/components/v2/candidates/CandidatesWorkspace";
import { candidatesModeHref, parseCandidatesMode } from "@/lib/candidates-mode";
import {
  searchRequestToListFilters,
  searchStateToListHref,
} from "@/lib/candidates-search-redirect";
import type { CandidateSearchRequest } from "@/lib/candidate-search-api";

// Lista, wyszukiwarka rekrutacji i radar to DUŻE, osobno przetestowane
// ekrany — tu sprawdzamy wyłącznie, który z nich się pokazuje, i przekazanie
// danych z okna „Z requestu" STANEM (nie adresem).
let searchParams = new URLSearchParams();
const push = vi.fn((href: string) => {
  searchParams = new URLSearchParams(href.split("?")[1] ?? "");
});
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/v2/pages/CandidatesListV2", () => ({
  CandidatesListV2: (props: { onRequestSearch?: (r: unknown) => void }) => (
    <button
      type="button"
      data-testid="mode-list"
      onClick={() =>
        props.onRequestSearch?.({
          source: "text",
          text: "Szukamy Java developera, Kraków, B2B, min. 5 lat",
          client: { id: 3, name: "Bank SA" },
        })
      }
    >
      lista
    </button>
  ),
}));

const searchProps = vi.fn();
vi.mock("@/components/v2/pages/CandidateSearchView", () => ({
  JOB_URL_PARAM: "job",
  CandidateSearchView: (props: Record<string, unknown>) => {
    searchProps(props);
    return <div data-testid="mode-search" />;
  },
}));

vi.mock("@/components/talent-radar/TalentRadarWorkspace", () => ({
  TalentRadarWorkspace: (props: {
    embedded?: boolean;
    initial?: { text?: string; client?: { name: string } };
  }) => (
    <div data-testid="mode-request" data-embedded={String(!!props.embedded)}>
      {props.initial?.text ?? ""}
      {props.initial?.client ? ` · ${props.initial.client.name}` : ""}
    </div>
  ),
}));

beforeEach(() => {
  searchParams = new URLSearchParams();
  push.mockClear();
  replace.mockClear();
  searchProps.mockClear();
});

describe("lib/candidates-mode", () => {
  it("nieznany albo pusty tryb to lista", () => {
    expect(parseCandidatesMode(null)).toBe("list");
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

describe("lib/candidates-search-redirect", () => {
  it("stan wyszukiwarki (?s=) przechodzi na parametry listy", () => {
    const s = JSON.stringify({
      q: "kafka",
      text_mode: "semantic",
      skills_required: ["Java", "Go|Rust"],
      skills_must: ["Spring"],
      skills_none: ["PHP"],
      status: ["active"],
      availability_status: ["open_to_offers"],
      rate_hourly_max: 180,
      location_cities: ["Kraków", "Warszawa"],
      languages: [{ code: "EN", min_level: "B2" }],
      hide_unknown: true,
    });
    const href = searchStateToListHref(new URLSearchParams({ mode: "search", s }));
    const params = new URLSearchParams(href.split("?")[1]);
    expect(href.startsWith("/candidates?")).toBe(true);
    expect(params.get("q")).toBe("kafka");
    expect(params.get("tm")).toBe("semantic");
    // OR wiąże mocniej niż AND — „Go OR Rust" to jedna grupa „którakolwiek".
    expect(params.get("skills_q")).toBe("Java AND Go OR Rust NOT PHP");
    // Stare `skills_must` zawsze było tylko rankingiem → „Mile widziane".
    expect(params.getAll("skills_pref")).toEqual(["Spring"]);
    expect(params.get("status")).toBe("active");
    expect(params.get("availability")).toBe("open_to_offers");
    expect(params.get("rate_max")).toBe("180");
    expect(params.get("loc")).toBe("Kraków");
    expect(params.get("lang")).toBe("en:B2");
    expect(params.get("hu")).toBe("1");
    expect(params.has("mode")).toBe(false);
  });

  it("brak albo zepsuty stan = czysta lista", () => {
    expect(searchStateToListHref(new URLSearchParams("mode=search"))).toBe("/candidates");
    expect(searchStateToListHref(new URLSearchParams("mode=search&s=%7Bzepsute"))).toBe(
      "/candidates",
    );
    expect(
      searchRequestToListFilters({ q: "  ", sort: "relevance" } as CandidateSearchRequest).q,
    ).toBe("");
  });
});

describe("CandidatesWorkspace", () => {
  it("bez parametru pokazuje listę — bez zakładek trybów", () => {
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-list")).toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
  });

  it("stary ?mode=search bez rekrutacji przechodzi na listę (replace, nie nowy wpis)", () => {
    searchParams = new URLSearchParams(`mode=search&s=${encodeURIComponent('{"q":"java"}')}`);
    render(<CandidatesWorkspace />);
    expect(replace).toHaveBeenCalledWith("/candidates?q=java");
    expect(screen.queryByTestId("mode-search")).toBeNull();
    expect(push).not.toHaveBeenCalled();
  });

  it("?mode=search&job= zostaje wyszukiwarką rekrutacji z linkiem powrotu", () => {
    searchParams = new URLSearchParams("mode=search&job=12");
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-search")).toBeInTheDocument();
    expect(searchProps.mock.calls[0][0]).toMatchObject({
      syncUrl: true,
      hideHeader: true,
      persistUrlParams: { mode: "search" },
    });
    expect(screen.getByRole("link", { name: /Kandydaci/ })).toHaveAttribute("href", "/candidates");
    expect(replace).not.toHaveBeenCalled();
  });

  it("?mode=request pokazuje wyniki radaru z linkiem powrotu", () => {
    searchParams = new URLSearchParams("mode=request");
    render(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-request")).toHaveAttribute("data-embedded", "true");
    expect(screen.getByRole("link", { name: /Kandydaci/ })).toBeInTheDocument();
  });

  it("okno „Z requestu” przekazuje dane radarowi przez stan, nie adres", () => {
    const { rerender } = render(<CandidatesWorkspace />);
    act(() => {
      fireEvent.click(screen.getByTestId("mode-list"));
    });
    expect(push).toHaveBeenCalledWith("/candidates?mode=request");
    rerender(<CandidatesWorkspace />);
    expect(screen.getByTestId("mode-request")).toHaveTextContent(
      "Szukamy Java developera, Kraków, B2B, min. 5 lat · Bank SA",
    );
    expect(push.mock.calls[0][0]).not.toContain("Java");
  });
});
