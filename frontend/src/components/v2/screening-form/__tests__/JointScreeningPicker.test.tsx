import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { JointContextPair } from "@/lib/api/screeningForm";

import { JointScreeningPicker } from "../JointScreeningPicker";

function pair(overrides: Partial<JointContextPair>): JointContextPair {
  return {
    job_id: 1,
    title: "Rekrutacja",
    client_id: 1,
    client_name: "Klient Demo",
    board_column: "new",
    process_state_version: 1,
    claim: null,
    selectable: true,
    reason: null,
    reason_message: null,
    budget_hourly: null,
    verified_stage_def_id: 9,
    ...overrides,
  };
}

describe("JointScreeningPicker — „Screening dla” (B1)", () => {
  it("lets you pick open pairs, greys out the rest with the reason, and adds a suggestion", () => {
    const onToggle = vi.fn();
    const onAddAndJoin = vi.fn();
    render(
      <JointScreeningPicker
        anchorTitle="Programista Frontend"
        pairs={[
          pair({ job_id: 2, title: "Angular Developer" }),
          pair({ job_id: 3, title: "Java Developer", selectable: false, reason: "later_stage", reason_message: "Screening tej rekrutacji jest już za nami." }),
        ]}
        suggestions={[{ job_id: 4, title: "Frontend Lead", client_name: null, score: 72, matching_must: [], gap_must: [] }]}
        selected={new Set([2])}
        onToggle={onToggle}
        onAddAndJoin={onAddAndJoin}
        addingJobId={null}
        error="Ta osoba ma zamkniętą kartę w tej rekrutacji."
      />,
    );
    expect(screen.getByText("2 rekrutacje · jedna rozmowa")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Angular Developer/ })).toBeChecked();
    const later = screen.getByRole("checkbox", { name: /Java Developer/ });
    expect(later).toBeDisabled();
    expect(screen.getByText("Screening tej rekrutacji jest już za nami.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Angular Developer/ }));
    expect(onToggle).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "+ Dodaj i dołącz" }));
    expect(onAddAndJoin).toHaveBeenCalledWith(4);
    expect(screen.getByRole("alert")).toHaveTextContent("zamkniętą kartę");
  });

  it("stops at four recruitments in one conversation", () => {
    render(
      <JointScreeningPicker
        anchorTitle="A"
        pairs={[2, 3, 4, 5].map((job_id) => pair({ job_id, title: `Rekrutacja ${job_id}` }))}
        suggestions={[{ job_id: 9, title: "Frontend Lead", client_name: null, score: 72, matching_must: [], gap_must: [] }]}
        selected={new Set([2, 3, 4])}
        onToggle={vi.fn()}
        onAddAndJoin={vi.fn()}
        addingJobId={null}
      />,
    );
    expect(screen.getByRole("checkbox", { name: /Rekrutacja 5/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Rekrutacja 4/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "+ Dodaj i dołącz" })).toBeDisabled();
    expect(screen.getByText(/Najwyżej 4 rekrutacje w jednej rozmowie/)).toBeInTheDocument();
  });

  it("renders nothing when the person is in no other recruitment and nothing else fits", () => {
    const { container } = render(
      <JointScreeningPicker
        anchorTitle="A"
        pairs={[]}
        suggestions={[]}
        selected={new Set()}
        onToggle={vi.fn()}
        onAddAndJoin={vi.fn()}
        addingJobId={null}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
