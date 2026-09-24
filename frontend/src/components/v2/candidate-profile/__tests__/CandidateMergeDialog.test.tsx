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
  it("renders conflict radios, counters and duplicate-row note", () => {
    const onChoose = vi.fn();
    render(<MergePlanView plan={plan} choices={{}} onChoose={onChoose} />);
    fireEvent.click(screen.getByLabelText("E-mail: jan@b.pl"));
    expect(onChoose).toHaveBeenCalledWith("email", "duplicate");
    expect(screen.getByText(/Przejdzie na ten profil: 9/)).toBeInTheDocument();
    expect(screen.getByText(/w tym 1 zdublowanych — zostaje nowszy wpis/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
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
