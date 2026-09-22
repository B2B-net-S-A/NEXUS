import { fireEvent, render, screen } from "@testing-library/react";
import React, { useState } from "react";
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
  semantics_version: 2,
};

/** Kontrolowany panel z podglądem ostatniego `onChange`. */
function Harness({
  initial,
  onChange,
  textInterpretation,
}: {
  initial: CandidateSearchRequest;
  onChange: (next: CandidateSearchRequest) => void;
  textInterpretation?: React.ComponentProps<typeof FiltersPanel>["textInterpretation"];
}) {
  const [value, setValue] = useState(initial);
  return (
    <FiltersPanel
      value={value}
      textInterpretation={textInterpretation}
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
    const input = screen.getByPlaceholderText(/Imię i nazwisko, e-mail/);
    expect(input.getAttribute("maxLength")).toBe(String(SEARCH_QUERY_MAX_LENGTH));
    expect(screen.getByText(`4/${SEARCH_QUERY_MAX_LENGTH}`)).toBeInTheDocument();
  });

  it("jednoznakowa umiejętność („C”) bez wyboru kubełka trafia do „Musi mieć”", () => {
    const onChange = vi.fn();
    render(<Harness initial={BASE} onChange={onChange} />);
    const input = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(input, { target: { value: "C" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ skills_required: ["C"] }),
    );
  });

  it("trzy kubełki: „Musi mieć” z grupą a|b, „Mile widziane”, „Wyklucz”", () => {
    const onChange = vi.fn();
    render(<Harness initial={BASE} onChange={onChange} />);
    const input = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(input, { target: { value: "Java, Spring|Quarkus" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("radio", { name: "Mile widziane" }));
    fireEvent.change(input, { target: { value: "Docker" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "-PHP" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        skills_required: ["Java", "Spring|Quarkus"],
        skills_preferred: ["Docker"],
        skills_excluded: ["PHP"],
      }),
    );
    expect(screen.getByText("Spring lub Quarkus")).toBeInTheDocument();
    expect(screen.getByText("bez PHP")).toBeInTheDocument();
  });

  it("„Ukryj osoby bez danych” ustawia hide_unknown", () => {
    const onChange = vi.fn();
    render(<Harness initial={BASE} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Ukryj osoby bez danych"));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ hide_unknown: true }),
    );
  });

  it("przełącznik „Dosłownie / Po znaczeniu” ustawia text_mode i wraca do auto", () => {
    const onChange = vi.fn();
    render(
      <Harness
        initial={{ ...BASE, q: "Jan Kowalski" }}
        onChange={onChange}
        textInterpretation={{
          applied: "literal",
          interpretation: {
            kind: "name",
            mode: "literal",
            rule: "multi_token_name",
            name: ["Jan", "Kowalski"],
            email: null,
            phone: null,
            skills: [],
            locations: [],
            other: [],
          },
        }}
      />,
    );
    expect(screen.getByTestId("text-interpretation").textContent).toMatch(
      /Rozumiem to jako: osoba \(Jan Kowalski\)/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Po znaczeniu" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ text_mode: "semantic" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Po znaczeniu" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ text_mode: null }),
    );
  });

  it("wklejony request pokazuje „Szukaj jak z requestu”", () => {
    const onUseAsRequest = vi.fn();
    const text = "Szukamy Java developera\nWymagania:\n- Java 17\n- Spring";
    render(
      <FiltersPanel
        value={{ ...BASE, q: text }}
        onChange={() => {}}
        onUseAsRequest={onUseAsRequest}
      />,
    );
    expect(screen.getByText("Wygląda na treść requestu.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Szukaj jak z requestu" }));
    expect(onUseAsRequest).toHaveBeenCalledWith(text);
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
    const skill = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(skill, { target: { value: "PHP" } });
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść" }));
    const cleared = onChange.mock.calls.at(-1)?.[0] as CandidateSearchRequest;
    expect(cleared.search_mode).toBe("boolean");
    expect(cleared.semantics_version).toBe(2);
    expect(cleared.q).toBeUndefined();
    expect(cleared.tags).toBeUndefined();
    // Pole jest przemontowane — szkic nie zamieni się w chip przy blurze.
    expect(
      (screen.getByLabelText("Dodaj umiejętność") as HTMLInputElement).value,
    ).toBe("");
  });

  it("lata doświadczenia są przycinane do 0–60", () => {
    expect(clampExperienceYears("")).toBeNull();
    expect(clampExperienceYears("75")).toBe(60);
    expect(clampExperienceYears("-3")).toBe(0);
    expect(clampExperienceYears("12")).toBe(12);
  });
});
