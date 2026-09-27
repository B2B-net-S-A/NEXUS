import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClientRulesCard } from "../GenerateBar";

const base = {
  clientName: "Test Client Alfa",
  clientSource: "process" as const,
  loading: false,
  error: false,
  languageLabel: "PL",
  filename: null,
  projectRef: null,
  projectRefFromJob: false,
  consentAttached: false,
};

describe("ClientRulesCard — zgoda RODO (runda 10, F20)", () => {
  it("bez wymogu zrzutu mówi, że stała klauzula RODO pochodzi z szablonu, nie od kandydata", () => {
    render(<ClientRulesCard {...base} consentRequired={false} />);
    expect(screen.getByText("Zrzut zgody RODO")).toBeInTheDocument();
    expect(screen.getByText("niewymagany")).toBeInTheDocument();
    expect(screen.getByText(/stała klauzula RODO B2B\.net z szablonu firmowego/)).toBeInTheDocument();
    expect(screen.queryByText("nie wymaga")).not.toBeInTheDocument();
  });

  it("przy wymogu zrzutu nadal pokazuje brak zrzutu", () => {
    render(<ClientRulesCard {...base} consentRequired />);
    expect(screen.getByText("brak zrzutu")).toBeInTheDocument();
  });
});
