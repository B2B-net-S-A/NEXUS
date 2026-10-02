/**
 * Pole „Rekruter” (`RecruiterAssignmentChoice`): nazwa opcji automatu zależy
 * od trybu przydziału, a nazwę opcji ręcznej może podać ekran.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecruiterAssignmentChoice } from "@/components/v2/jobs/RecruiterAssignmentChoice";
import type { AllocationMode, RecruiterAssignment } from "@/lib/recruiter-assignment";

function renderChoice(
  props: {
    mode?: AllocationMode;
    value?: RecruiterAssignment;
    manualLabel?: string;
    passive?: boolean;
  } = {},
) {
  render(
    <>
      <span id="recruiter-label">Rekruter</span>
      <RecruiterAssignmentChoice
        labelledBy="recruiter-label"
        value={props.value ?? "automatic"}
        onChange={vi.fn()}
        automaticAvailable
        unavailableReason={null}
        mode={props.mode}
        passive={props.passive}
        manualLabel={props.manualLabel}
      />
    </>,
  );
  const group = screen.getByRole("radiogroup", { name: "Rekruter" });
  return within(group)
    .getAllByRole("radio")
    .map((radio) => radio.textContent);
}

describe("RecruiterAssignmentChoice", () => {
  it("tryb „auto”: „Przydzieli automat” i zdanie o przydziale od razu", () => {
    expect(renderChoice({ mode: "auto" })).toEqual(["Przydzieli automat", "Wybieram sam"]);
    expect(
      screen.getByText(
        "Automat przydzieli jedną osobę z kategorii — tę z najmniejszą liczbą requestów. Head rekrutacji zobaczy to na pulpicie i może zmienić.",
      ),
    ).toBeInTheDocument();
  });

  it.each([["shadow" as const], [undefined]])(
    "tryb %s: „Zaproponuje automat” i zdanie o akceptacji",
    (mode) => {
      expect(renderChoice({ mode })).toEqual(["Zaproponuje automat", "Wybieram sam"]);
      expect(
        screen.getByText(
          "Automat zaproponuje osobę według kategorii i obłożenia. Propozycję zatwierdza Head of Recruitment — do tego czasu nikt nie jest przypisany.",
        ),
      ).toBeInTheDocument();
    },
  );

  it("ekran może nazwać opcję ręczną po swojemu", () => {
    expect(renderChoice({ mode: "auto", manualLabel: "Wskażę sam" })).toEqual([
      "Przydzieli automat",
      "Wskażę sam",
    ]);
  });

  it("priorytet „Przyjmujemy kandydatów” nie obiecuje przydziału — także w trybie „auto”", () => {
    renderChoice({ mode: "auto", passive: true });
    expect(screen.getByText(/automat nikogo nie proponuje/)).toBeInTheDocument();
    expect(screen.queryByText(/Automat przydzieli jedną osobę/)).not.toBeInTheDocument();
  });
});
