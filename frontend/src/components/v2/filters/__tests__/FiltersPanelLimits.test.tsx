import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";

vi.mock("@/components/v2/filters/AdvancedSearchPopover", () => ({
  AdvancedSearchPopover: () => null,
}));
vi.mock("@/components/v2/filters/CompetenceCategoryFilter", () => ({
  CompetenceCategoryFilter: () => null,
}));

import {
  FiltersPanel,
  SEARCH_QUERY_MAX_LENGTH,
  clampExperienceYears,
} from "@/components/v2/filters/FiltersPanel";

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

/** Kontrolowany panel z podglądem ostatniego `onChange`. */
function Harness({
  initial,
  onChange,
}: {
  initial: CandidateSearchRequest;
  onChange: (next: CandidateSearchRequest) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <FiltersPanel
      value={value}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

describe("FiltersPanel — limity lustrzane do backendu", () => {
  it("pole frazy ma limit 500 znaków i licznik", () => {
    render(<FiltersPanel value={{ ...BASE, q: "java" }} onChange={() => {}} />);
    const input = screen.getByPlaceholderText(/Szukaj semantycznie/);
    expect(input.getAttribute("maxLength")).toBe(String(SEARCH_QUERY_MAX_LENGTH));
    expect(screen.getByText(`4/${SEARCH_QUERY_MAX_LENGTH}`)).toBeInTheDocument();
  });

  it("jednoznakowa umiejętność („C”) jest przyjmowana", () => {
    const onChange = vi.fn();
    render(<Harness initial={BASE} onChange={onChange} />);
    const input = screen.getByLabelText("Skills (preferowane)");
    fireEvent.change(input, { target: { value: "C" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ skills_must: ["C"] }),
    );
  });

  it("tekst wpisany bez Enter zamienia się w chip przy opuszczeniu pola", () => {
    const onChange = vi.fn();
    render(<Harness initial={BASE} onChange={onChange} />);
    const city = screen.getByLabelText("Miasto");
    fireEvent.change(city, { target: { value: "Kraków" } });
    fireEvent.blur(city);
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ location_cities: ["Kraków"] }),
    );
    expect((city as HTMLInputElement).value).toBe("");
  });

  it("ponad limit: komunikat przy polu, tekst zostaje, request bez zmian", () => {
    const onChange = vi.fn();
    const cities = Array.from({ length: 10 }, (_, i) => `Miasto${i}`);
    render(
      <Harness initial={{ ...BASE, location_cities: cities }} onChange={onChange} />,
    );
    const city = screen.getByLabelText("Miasto");
    fireEvent.change(city, { target: { value: "Gdańsk" } });
    fireEvent.keyDown(city, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toMatch(/Limit 10 miast/);
    expect((city as HTMLInputElement).value).toBe("Gdańsk");
  });

  it("„Wyczyść” zachowuje tryb wyszukiwania i czyści szkice chipów", () => {
    const onChange = vi.fn();
    render(
      <Harness
        initial={{ ...BASE, search_mode: "boolean", q: "java", tags: ["x"] }}
        onChange={onChange}
      />,
    );
    const skill = screen.getByLabelText("Skills (wyklucz)");
    fireEvent.change(skill, { target: { value: "PHP" } });
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść" }));
    const cleared = onChange.mock.calls.at(-1)?.[0] as CandidateSearchRequest;
    expect(cleared.search_mode).toBe("boolean");
    expect(cleared.q).toBeUndefined();
    expect(cleared.tags).toBeUndefined();
    expect((skill as HTMLInputElement).value).toBe("");
  });

  it("lata doświadczenia są przycinane do 0–60", () => {
    expect(clampExperienceYears("")).toBeNull();
    expect(clampExperienceYears("75")).toBe(60);
    expect(clampExperienceYears("-3")).toBe(0);
    expect(clampExperienceYears("12")).toBe(12);
  });
});
