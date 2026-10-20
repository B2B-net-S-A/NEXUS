import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CareerJobView } from "../../CareerJobView";
import { huntMessage } from "../GlitchScene";
import { mockMatchMedia, MUST, NICE, renderScene } from "./sceneTestUtils";

afterEach(() => vi.unstubAllGlobals());

describe("scena Glitch", () => {
  it("test, który zdasz → PASS i wynik; „uruchom” nie zmienia wyniku", () => {
    const s = renderScene("glitch");
    const row = s.full().getByRole("button", { name: /^PostgreSQL/ });
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(row).toHaveTextContent("PASS");
    expect(s.full().getByText(/1 passed · 4 pending/)).toBeInTheDocument();
    fireEvent.click(s.full().getByRole("button", { name: "uruchom" }));
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });

  it("błąd ma opis dla czytnika zamiast literówki; znaleziony znika i nie liczy się do wyniku", () => {
    const s = renderScene("glitch");
    const bugs = s.full().getAllByRole("button", { name: /^Błąd 2 z 3: literówka w nazwie pliku testów/ });
    expect(bugs).toHaveLength(1);
    expect(bugs[0]).not.toHaveAccessibleName(/spce/);
    fireEvent.click(bugs[0]);
    expect(screen.queryAllByRole("button", { name: /^Błąd 2 z 3/ })).toHaveLength(0);
    expect(s.full().getByText("kandydat.spec.ts")).toHaveClass("kr-bug-fixed");
    expect(s.full().getByText("znalezione 1/3 — szukaj dalej")).toBeInTheDocument();
    expect(s.score().getByText("0/5")).toBeInTheDocument();
    expect(huntMessage(3)).toMatch(/wszystkie 3/);
  });

  it("na stronie trzy błędy: hero, runner, panel wyniku — tytuł h1 nietknięty", () => {
    render(
      <CareerJobView
        data={{
          status: "open",
          theme: "glitch",
          recruiter: { first_name: "Marta", slug: "marta-n" },
          job: {
            slug: "test-automation-engineer-ab12",
            title: "Test Automation Engineer",
            subtitle: null,
            about: null,
            must: MUST,
            nice: NICE,
            params: null,
            show: { must: true, nice: true, params: true, process: true },
          },
        }}
        base="/kariera"
        host="nexus.b2bnetwork.pl"
        formPreview={{ disableSubmit: true }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Test AutomationEngineer.");
    for (const n of [1, 2, 3]) {
      expect(screen.getAllByRole("button", { name: new RegExp(`^Błąd ${n} z 3`) }).length).toBeGreaterThan(0);
    }
    fireEvent.click(screen.getByRole("button", { name: /^Błąd 1 z 3/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /^Błąd 2 z 3/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /^Błąd 3 z 3/ }));
    expect(screen.getAllByText("wszystkie 3 znalezione. Dokładnie tego szukamy.").length).toBeGreaterThan(0);
    expect(screen.getByText("rekrutacji")).toHaveClass("kr-bug-fixed");
  });

  it("ograniczenie ruchu: „uruchom” bez paska postępu, PASS działa", () => {
    mockMatchMedia((q) => q.includes("reduce"));
    const s = renderScene("glitch");
    fireEvent.click(s.full().getByRole("button", { name: "uruchom" }));
    expect(s.container.querySelector(".kr-gl-prog")).toBeNull();
    fireEvent.click(s.full().getByRole("button", { name: /^Kafka/ }));
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });
});
