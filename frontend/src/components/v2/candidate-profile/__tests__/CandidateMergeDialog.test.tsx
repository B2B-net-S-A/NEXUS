import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { MergePlanView } from "../CandidateMergeDialog";
import {
  canMergeCandidates,
  conflictChoices,
  planFromMergeConflict,
  resultingValue,
  type MergePlan,
} from "@/lib/api/candidateMerge";

const plan: MergePlan = {
  survivor_id: 10,
  duplicate_id: 20,
  survivor: { id: 10, name: "Jan", lastname: "Kowalski", email: "jan@a.pl", phone: "111", city: null, external_source: "manual", created_at: null, updated_at: null },
  duplicate: { id: 20, name: "Jan", lastname: "Kowalski", email: "jan@b.pl", phone: null, city: "Kraków", external_source: "traffit", created_at: null, updated_at: null },
  fields: [
    { field: "email", label: "E-mail", survivor: "jan@a.pl", duplicate: "jan@b.pl", conflict: true, default: "survivor" },
    { field: "city", label: "Miasto", survivor: null, duplicate: "Kraków", conflict: false, default: "duplicate" },
  ],
  references: [
    { table: "notes", column: "candidate_id", rows: 3, conflicts: 0, unresolvable: false },
    { table: "my_people_overrides", column: "candidate_id", rows: 2, conflicts: 1, unresolvable: false },
  ],
  polymorphic: [{ table: "activities", rows: 4 }],
  moved_rows: 9,
  conflicts: 1,
  blockers: [],
  primary_cv: { before: null, after: null, changes: false },
  cards: [],
  can_apply: true,
  fingerprint: "f".repeat(64),
};

describe("candidate merge helpers", () => {
  it("only admin and Head of Recruitment may merge", () => {
    expect(canMergeCandidates({ role: "admin", roles: ["admin"] } as never)).toBe(true);
    expect(canMergeCandidates({ role: "head_of_recruitment", roles: ["head_of_recruitment"] } as never)).toBe(true);
    expect(canMergeCandidates({ role: "recruiter", roles: ["recruiter"] } as never)).toBe(false);
    expect(canMergeCandidates(null)).toBe(false);
  });

  it("sends choices only for conflicting fields, defaulting to the survivor", () => {
    expect(conflictChoices(plan, {})).toEqual({ email: "survivor" });
    expect(conflictChoices(plan, { email: "duplicate", city: "survivor" })).toEqual({ email: "duplicate" });
  });

  it("resulting value follows the choice for conflicts and the default otherwise", () => {
    expect(resultingValue(plan.fields[0], { email: "duplicate" })).toBe("jan@b.pl");
    expect(resultingValue(plan.fields[0], {})).toBe("jan@a.pl");
    expect(resultingValue(plan.fields[1], {})).toBe("Kraków");
  });

  it("reads a fresh plan only from a 409 carrying one", () => {
    expect(planFromMergeConflict({ response: { status: 409, data: { detail: { plan } } } })?.duplicate_id).toBe(20);
    expect(planFromMergeConflict({ response: { status: 409, data: { detail: { code: "merge_blocked" } } } })).toBeNull();
  });
});

describe("MergePlanView", () => {
  it("shows which stage stays on a card shared by both profiles", () => {
    render(
      <MergePlanView
        plan={{
          ...plan,
          references: [{ table: "recruitment_processes", column: "candidate_id", rows: 1, conflicts: 1, unresolvable: false }],
          cards: [
            {
              job_id: 7,
              job_title: "Analityk danych",
              survivor_stage: "cv_sent",
              survivor_stage_name: "CV Wysłane",
              duplicate_stage: "screening",
              duplicate_stage_name: "Screening",
              result_stage: "cv_sent",
              result_stage_name: "CV Wysłane",
              kept: "survivor",
              restores: true,
            },
          ],
        }}
        choices={{}}
        onChoose={vi.fn()}
      />,
    );
    const row = screen.getByText("Analityk danych").closest("li");
    expect(row).toHaveTextContent("Analityk danych: zostaje CV Wysłane (ten profil: CV Wysłane, duplikat: Screening)");
    expect(screen.getByText(/zostaje proces karty/)).toBeInTheDocument();
  });

  it("hides the cards section when no recruitment is shared", () => {
    render(<MergePlanView plan={plan} choices={{}} onChoose={vi.fn()} />);
    expect(screen.queryByText("Karty w rekrutacjach obu profili")).not.toBeInTheDocument();
  });

  it("renders conflict radios, counters and duplicate-row note", () => {
    const onChoose = vi.fn();
    render(<MergePlanView plan={plan} choices={{}} onChoose={onChoose} />);
    fireEvent.click(screen.getByLabelText("E-mail: jan@b.pl"));
    expect(onChoose).toHaveBeenCalledWith("email", "duplicate");
    expect(screen.getByText(/Przejdzie na ten profil: 9/)).toBeInTheDocument();
    expect(screen.getByText(/w tym 1 zdublowanych — zostaje nowszy wpis/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the primary CV after the merge only when it changes", () => {
    const file = { document_id: 5, filename: "z-duplikatu.pdf", from_duplicate: true };
    const { rerender } = render(<MergePlanView plan={plan} choices={{}} onChoose={vi.fn()} />);
    expect(screen.queryByText(/Główne CV po scaleniu/)).toBeNull();

    rerender(
      <MergePlanView
        plan={{ ...plan, primary_cv: { before: null, after: file, changes: true } }}
        choices={{}}
        onChoose={vi.fn()}
      />,
    );
    const note = screen.getByRole("status");
    expect(note).toHaveTextContent("Główne CV po scaleniu: z-duplikatu.pdf (z duplikatu #20). Teraz: brak.");

    rerender(
      <MergePlanView
        plan={{ ...plan, primary_cv: { before: file, after: file, changes: false } }}
        choices={{}}
        onChoose={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Główne CV po scaleniu/)).toBeNull();
  });

  it("says both files stay when documents collide", () => {
    render(
      <MergePlanView
        plan={{ ...plan, references: [{ table: "candidate_documents", column: "candidate_id", rows: 2, conflicts: 1, unresolvable: false }] }}
        choices={{}}
        onChoose={vi.fn()}
      />,
    );
    expect(screen.getByText(/w tym 1 zdublowanych — oba pliki zostają/)).toBeInTheDocument();
  });

  it("shows blockers as an alert", () => {
    render(
      <MergePlanView
        plan={{ ...plan, can_apply: false, blockers: [{ code: "both_external", message: "Oba profile pochodzą z Traffita." }] }}
        choices={{}}
        onChoose={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Oba profile pochodzą z Traffita.");
  });
});
