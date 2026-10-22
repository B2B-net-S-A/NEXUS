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

  it("shows the client reference before each title, like the recruitment header", () => {
    render(
      <JointScreeningPicker
        anchorTitle="Cyber Security Project Coordinator"
        anchorReference="42946"
        pairs={[
          pair({ job_id: 2, title: "Cyber Security Specialist", client_reference: "42927, 42928" }),
          pair({ job_id: 3, title: "Cyber Security Consultant", client_reference: null }),
        ]}
        suggestions={[{ job_id: 4, title: "Cyber Security Expert", client_name: null, client_reference: "42970", score: 71, matching_must: [], gap_must: [] }]}
        selected={new Set()}
        onToggle={vi.fn()}
        onAddAndJoin={vi.fn()}
        addingJobId={null}
      />,
    );
    const tags = screen.getAllByTestId("client-reference-tag").map((tag) => tag.textContent);
    expect(tags).toEqual(["42946", "42927+1", "42970"]);
    expect(screen.getByRole("checkbox", { name: /42927\+1\s*Cyber Security Specialist/ })).toBeInTheDocument();
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

describe("JointScreeningPicker — pamięć rozmowy (16.10.2026, D1 A)", () => {
  const base = {
    anchorTitle: "Programista Frontend",
    suggestions: [],
    onToggle: vi.fn(),
    onAddAndJoin: vi.fn(),
    addingJobId: null,
  };

  it("an unchecked recruitment with entries says how many answers wait in memory", () => {
    render(
      <JointScreeningPicker
        {...base}
        pairs={[
          pair({ job_id: 2, title: "Angular Developer" }),
          pair({ job_id: 3, title: "Java Developer" }),
          pair({ job_id: 5, title: "Kafka Engineer" }),
        ]}
        selected={new Set([2])}
        memory={
          new Map([
            [2, { answers: 3, any: true }],
            [3, { answers: 2, any: true }],
            [5, { answers: 0, any: true }],
          ])
        }
      />,
    );
    // Zaznaczona rekrutacja ma wpisy w formularzu, nie „w pamięci”.
    expect(screen.getByRole("checkbox", { name: /Angular Developer/ })).not.toHaveAccessibleName(/w pamięci/);
    expect(screen.getByRole("checkbox", { name: /Java Developer/ })).toHaveAccessibleName(
      /2 odpowiedzi w pamięci · zaznacz, żeby wróciły/,
    );
    expect(screen.getByRole("checkbox", { name: /Kafka Engineer/ })).toHaveAccessibleName(/wpisy w pamięci/);
  });

  it("after unchecking: how many answers stay and „Cofnij”; after checking again: they came back", () => {
    const onUndo = vi.fn();
    const { rerender } = render(
      <JointScreeningPicker
        {...base}
        pairs={[pair({ job_id: 3, title: "Java Developer" })]}
        selected={new Set()}
        notice={{ kind: "unchecked", jobId: 3, title: "Java Developer", answers: 2 }}
        onUndo={onUndo}
      />,
    );
    expect(screen.getByTestId("joint-picker-notice")).toHaveTextContent(
      "Odznaczono „Java Developer” — 2 odpowiedzi zostają w pamięci do zapisu.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
    expect(onUndo).toHaveBeenCalled();
    rerender(
      <JointScreeningPicker
        {...base}
        pairs={[pair({ job_id: 3, title: "Java Developer" })]}
        selected={new Set([3])}
        notice={{ kind: "restored", jobId: 3, title: "Java Developer", answers: 1 }}
        onUndo={onUndo}
      />,
    );
    expect(screen.getByTestId("joint-picker-notice")).toHaveTextContent("Wróciła 1 odpowiedź z pamięci — Java Developer.");
    expect(screen.queryByRole("button", { name: "Cofnij" })).toBeNull();
  });
});
