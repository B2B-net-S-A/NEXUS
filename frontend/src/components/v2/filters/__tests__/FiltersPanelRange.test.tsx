import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import { EXPERIENCE_RANGE_REVERSED_MSG } from "@/lib/candidate-search-request";

vi.mock("@/components/v2/filters/AdvancedSearchPopover", () => ({
  AdvancedSearchPopover: () => null,
}));
vi.mock("@/components/v2/filters/CompetenceCategoryFilter", () => ({
  CompetenceCategoryFilter: () => null,
}));

import { FiltersPanel } from "@/components/v2/filters/FiltersPanel";

const BASE: CandidateSearchRequest = {
  q: null,
  q_all: [],
  q_any: [],
  q_any_groups: [],
  q_none: [],
  competence_category_ids: [],
  skills_must: [],
  skills_any: [],
  skills_none: [],
  languages: [],
  location_cities: [],
  status: [],
  availability_status: [],
  tags: [],
  sort: "relevance",
  page: 1,
  page_size: 50,
  search_mode: "hybrid",
};

describe("FiltersPanel — lata doświadczenia (UAT B28)", () => {
  it("min > max pokazuje błąd przy polu i oznacza pola jako niepoprawne", () => {
    render(
      <FiltersPanel
        value={{ ...BASE, experience_years_min: 10, experience_years_max: 2 }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("alert").textContent).toBe(EXPERIENCE_RANGE_REVERSED_MSG);
    expect(screen.getByPlaceholderText("min").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByPlaceholderText("max").getAttribute("aria-invalid")).toBe("true");
  });

  it("poprawny przedział nie pokazuje błędu", () => {
    render(
      <FiltersPanel
        value={{ ...BASE, experience_years_min: 2, experience_years_max: 6 }}
        onChange={() => {}}
      />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByPlaceholderText("min").getAttribute("aria-invalid")).toBeNull();
  });
});
