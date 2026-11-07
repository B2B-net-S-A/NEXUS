import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  IntakeRequirementProposals,
  type IntakeRequirementProposalsProps,
} from "@/components/v2/jobs/new/IntakeRequirementProposals";
import type { RequirementRowForm } from "@/lib/requirement-rows";

const ROWS: RequirementRowForm[] = [
  { key: "d", words: ["Dynamics 365", "D365"], level: "must" },
  { key: "c", words: ["C#"], level: "must" },
];

function renderPanel(props: Partial<IntakeRequirementProposalsProps> = {}) {
  const handlers = {
    onApproveCritical: vi.fn(),
    onNoCritical: vi.fn(),
    onDismissCritical: vi.fn(),
    onAddTechnologies: vi.fn(),
    onDismissTechnologies: vi.fn(),
  };
  render(
    <IntakeRequirementProposals
      rows={ROWS}
      noCritical={false}
      criticalProposal={[{ label: "Dynamics 365", reason: "minimum 5 lat pracy z Dynamics 365 CE/CRM" }]}
      mailTechnologies={["Dataverse", "D365", "Jenkins"]}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("IntakeRequirementProposals (M1, M2, 07.11.2026)", () => {
  it("propozycja krytycznych z cytatem z maila i trzema decyzjami", () => {
    const h = renderPanel();
    const box = screen.getByTestId("intake-critical-proposal");
    expect(box).toHaveTextContent("Propozycja AI: krytyczne „Dynamics 365”.");
    expect(box).toHaveTextContent("klient pisze „minimum 5 lat pracy z Dynamics 365 CE/CRM”");
    fireEvent.click(within(box).getByRole("button", { name: "Zatwierdź krytyczne" }));
    fireEvent.click(within(box).getByRole("button", { name: "Brak krytycznych" }));
    fireEvent.click(within(box).getByRole("button", { name: "Wybiorę sam" }));
    expect(h.onApproveCritical).toHaveBeenCalledOnce();
    expect(h.onNoCritical).toHaveBeenCalledOnce();
    expect(h.onDismissCritical).toHaveBeenCalledOnce();
  });

  it("po decyzji DL-a propozycja krytycznych znika", () => {
    renderPanel({ rows: [{ ...ROWS[0], level: "critical" }, ROWS[1]] });
    expect(screen.queryByTestId("intake-critical-proposal")).toBeNull();
  });

  it("„Brak krytycznych” też chowa propozycję", () => {
    renderPanel({ noCritical: true });
    expect(screen.queryByTestId("intake-critical-proposal")).toBeNull();
  });

  it("technologie z maila bez tych, które są w wierszach; jedna albo wszystkie", () => {
    const h = renderPanel();
    const box = screen.getByTestId("intake-mail-technologies");
    expect(within(box).queryByRole("button", { name: "+ D365" })).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "+ Jenkins" }));
    expect(h.onAddTechnologies).toHaveBeenLastCalledWith(["Jenkins"]);
    fireEvent.click(within(box).getByRole("button", { name: "Dodaj wszystkie (2)" }));
    expect(h.onAddTechnologies).toHaveBeenLastCalledWith(["Dataverse", "Jenkins"]);
  });

  it("bez propozycji nic nie rysuje", () => {
    renderPanel({ criticalProposal: [], mailTechnologies: ["C#"] });
    expect(screen.queryByTestId("intake-requirement-proposals")).toBeNull();
  });
});
