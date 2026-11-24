/**
 * `JobDatesFact` — „Dodana → Termin” w nagłówku rekrutacji (19.11.2026,
 * makieta wariant B). Po terminie zawsze czerwone, ≤ 7 dni ostrzeżenie.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JobDatesFact, jobAddedAt } from "@/components/v2/jobs/JobDatesFact";

const NOW = new Date(2026, 10, 19, 10, 0);

function chip() {
  return screen.getByTestId("job-header-dates");
}

describe("JobDatesFact", () => {
  it("pokazuje dzień dodania, termin i ile zostało; pełne daty w dymku", () => {
    render(
      <JobDatesFact
        job={{
          opened_effective_at: "2026-11-18T09:12:00+01:00",
          deadline: "2026-11-23",
          deadline_time: "12:00:00",
        }}
        now={NOW}
      />,
    );
    expect(chip()).toHaveTextContent("18.11→23.11· za 4 dni");
    // Godzina w pigułce tylko dziś i jutro.
    expect(chip()).not.toHaveTextContent("12:00·");
    expect(chip()).toHaveAttribute("title", "Dodana: 18.11.2026\nTermin: 23.11.2026, 12:00 (za 4 dni)");
    expect(chip()).toHaveAttribute("data-urgency", "soon");
    expect(screen.getByTestId("job-header-dates-relative")).toHaveClass("text-warning-muted-foreground");
  });

  it("termin dziś pokazuje godzinę w pigułce", () => {
    render(
      <JobDatesFact
        job={{ created_at: "2026-11-10T08:00:00Z", deadline: "2026-11-19", deadline_time: "16:30:00" }}
        now={NOW}
      />,
    );
    expect(chip()).toHaveTextContent("10.11→19.11, 16:30· dziś");
  });

  it("po terminie jest czerwone z liczbą dni", () => {
    render(
      <JobDatesFact
        job={{ created_at: "2026-11-10T08:00:00Z", deadline: "2026-11-18", deadline_time: "12:00:00" }}
        now={NOW}
      />,
    );
    // W wąskim nagłówku krótko, w szerokim pełne zdanie; pełne też w dymku.
    expect(screen.getByText("po terminie 1 dz.")).toHaveClass("@min-[86rem]/job-header:hidden");
    expect(screen.getByText("po terminie 1 dzień")).toHaveClass("hidden", "@min-[86rem]/job-header:inline");
    expect(chip().getAttribute("title")).toContain("18.11.2026, 12:00 (po terminie 1 dzień)");
    expect(chip()).toHaveAttribute("data-urgency", "overdue");
    expect(screen.getByTestId("job-header-dates-relative")).toHaveClass("text-destructive");
  });

  it("odległy termin bez koloru ostrzeżenia", () => {
    render(<JobDatesFact job={{ created_at: "2026-11-01T08:00:00Z", deadline: "2026-12-15" }} now={NOW} />);
    expect(chip()).toHaveTextContent("01.11→15.12· za 26 dni");
    expect(screen.getByTestId("job-header-dates-relative")).toHaveClass("text-muted-foreground");
  });

  it("„Klient nie podał” mówi to wprost zamiast daty", () => {
    render(
      <JobDatesFact
        job={{ created_at: "2026-10-20T08:00:00Z", deadline: null, deadline_not_provided: true }}
        now={NOW}
      />,
    );
    expect(chip()).toHaveTextContent("20.10→klient nie podał");
    expect(chip()).toHaveAttribute("title", "Dodana: 20.10.2026\nTermin: klient nie podał");
    expect(screen.queryByTestId("job-header-dates-relative")).toBeNull();
  });

  it("brak terminu i brak decyzji to „nie podano”, nie pustka", () => {
    render(<JobDatesFact job={{ created_at: "2026-10-20T08:00:00Z" }} now={NOW} />);
    expect(chip()).toHaveTextContent("20.10→nie podano");
    expect(chip()).toHaveAttribute("aria-label", "Dodana: 20.10.2026. Termin: nie podano");
  });

  it("data dodania: `opened_at` z Traffita wygrywa z datą importu", () => {
    expect(
      jobAddedAt({ opened_at: "2026-09-01T08:00:00Z", created_at: "2026-10-01T08:00:00Z" }),
    ).toBe("2026-09-01T08:00:00Z");
    expect(jobAddedAt({ created_at: "2026-10-01T08:00:00Z" })).toBe("2026-10-01T08:00:00Z");
    expect(jobAddedAt({})).toBeNull();
  });
});
