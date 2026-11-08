import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  SkillYearsBadges,
  SkillYearsFilterFields,
} from "@/components/v2/candidates/SkillYearsFilter";

describe("okienko „Lata z technologią”", () => {
  it("pusty filtr: jeden wiersz, wpis technologii idzie do filtrów z domyślnymi 3 latami", () => {
    const onPatch = vi.fn();
    render(
      <SkillYearsFilterFields
        filters={{ skillYears: [], hideUnknownSkillYears: false }}
        onPatch={onPatch}
      />,
    );
    fireEvent.change(screen.getByLabelText("Technologia 1"), { target: { value: "Java" } });
    expect(onPatch).toHaveBeenLastCalledWith({ skillYears: ["Java:3"] });
    fireEvent.change(screen.getByLabelText("Lata z technologią 1"), { target: { value: "5" } });
    expect(onPatch).toHaveBeenLastCalledWith({ skillYears: ["Java:5"] });
  });

  it("niedokończony wiersz zostaje w okienku, ale nie w filtrach", () => {
    const onPatch = vi.fn();
    render(
      <SkillYearsFilterFields
        filters={{ skillYears: ["Java:3"], hideUnknownSkillYears: false }}
        onPatch={onPatch}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /technologia/ }));
    expect(screen.getByLabelText("Technologia 2")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Technologia 1"), { target: { value: "" } });
    expect(screen.getByLabelText("Technologia 1")).toBeInTheDocument();
    expect(onPatch).toHaveBeenLastCalledWith({ skillYears: [] });
  });

  it("usunięcie ostatniego wiersza czyści filtr i zostawia pusty wiersz", () => {
    const onPatch = vi.fn();
    render(
      <SkillYearsFilterFields
        filters={{ skillYears: ["Kafka:2"], hideUnknownSkillYears: false }}
        onPatch={onPatch}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Usuń wiersz 1" }));
    expect(onPatch).toHaveBeenLastCalledWith({ skillYears: [] });
    expect(screen.getByLabelText("Technologia 1")).toHaveValue("");
  });

  it("„ukryj” osoby bez dat w CV", () => {
    const onPatch = vi.fn();
    render(
      <SkillYearsFilterFields
        filters={{ skillYears: ["Java:3"], hideUnknownSkillYears: false }}
        onPatch={onPatch}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "ukryj" }));
    expect(onPatch).toHaveBeenLastCalledWith({ hideUnknownSkillYears: true });
  });
});

describe("lata w wierszu listy", () => {
  it("pokazuje tylko technologie z datami", () => {
    render(
      <SkillYearsBadges
        entries={[
          { skill: "Java", years_min: 3, months: 59, source: "cv_roles" },
          { skill: "Kafka", years_min: 2, months: null, source: null },
        ]}
      />,
    );
    expect(screen.getAllByTestId("skill-years-badge").map((n) => n.textContent)).toEqual([
      "Java 4 lata 11 mies.",
    ]);
  });

  it("bez lat nic nie rysuje", () => {
    const { container } = render(<SkillYearsBadges entries={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
