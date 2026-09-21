import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { ForJobResponse } from "@/lib/api/myPeople";
import { contextFromPath, shouldCloseOnEscape } from "../MyPeoplePanel";
import { ForJobView, PeopleListView } from "../MyPeopleViews";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("contextFromPath", () => {
  it("reads job and candidate ids from the address", () => {
    expect(contextFromPath("/jobs/42")).toEqual({ jobId: 42, candidateId: null });
    expect(contextFromPath("/jobs/42?tab=pipeline")).toEqual({ jobId: 42, candidateId: null });
    expect(contextFromPath("/candidates/7")).toEqual({ jobId: null, candidateId: 7 });
    expect(contextFromPath("/jobs")).toEqual({ jobId: null, candidateId: null });
    expect(contextFromPath(null)).toEqual({ jobId: null, candidateId: null });
  });
});

describe("shouldCloseOnEscape", () => {
  it("ignores Escape already handled or owned by an open dialog", () => {
    const esc = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
    expect(shouldCloseOnEscape(esc)).toBe(true);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    expect(shouldCloseOnEscape(esc)).toBe(false);
    dialog.remove();
    const handled = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
    handled.preventDefault();
    expect(shouldCloseOnEscape(handled)).toBe(false);
    expect(shouldCloseOnEscape(new KeyboardEvent("keydown", { key: "a" }))).toBe(false);
  });
});

const base: ForJobResponse = {
  job_id: 1,
  job_title: "Java",
  in_job_count: 0,
  degraded: false,
  rows: [],
};

describe("ForJobView", () => {
  it("says degraded instead of pretending nobody fits", () => {
    render(
      <ForJobView
        data={{
          ...base,
          degraded: true,
          rows: [
            {
              candidate_id: 1, full_name: "Anna Test", category_id: null, score: null,
              measurement: "unavailable", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: null, active_processes: 0,
            },
          ],
        }}
        actions={{}}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("nie znaczy, że nikt nie pasuje");
    expect(screen.queryByText("Nikt z Twojej listy nie jest dostępny do tej rekrutacji.")).toBeNull();
  });

  it("an unscored row is labelled, never shown as 0", () => {
    render(
      <ForJobView
        data={{
          ...base,
          rows: [
            {
              candidate_id: 2, full_name: "Ola Test", category_id: null, score: null,
              measurement: "missing_vector", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: null, active_processes: 0,
            },
          ],
        }}
        actions={{}}
      />,
    );
    expect(screen.getByLabelText("Dopasowanie: Ocena niepełna")).toBeTruthy();
    expect(screen.queryByText(/0\/100/)).toBeNull();
  });

  it("blocks adding when the hiring manager vetoed, adds otherwise", () => {
    const onAdd = vi.fn();
    render(
      <ForJobView
        data={{
          ...base,
          rows: [
            {
              candidate_id: 3, full_name: "Veto Test", category_id: null, score: 80,
              measurement: "measured",
              eligibility: { reason_code: "rejected_by_hiring_manager", reason: "Weto HM", assignment_allowed: false, visibility: "warn", severity: "hard", secondary: [] },
              sent_to_client_at: null, last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: null, active_processes: 0,
            },
            {
              candidate_id: 4, full_name: "Ok Test", category_id: null, score: 75,
              measurement: "measured", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: null, active_processes: 0,
            },
          ],
        }}
        actions={{ onAdd }}
      />,
    );
    expect((screen.getByLabelText("Dodaj do tej rekrutacji: Veto Test") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Dodaj do tej rekrutacji: Ok Test"));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ candidate_id: 4 }));
  });
});

describe("PeopleListView", () => {
  it("does not offer adding a working person", () => {
    render(
      <PeopleListView
        active={[]}
        working={[
          {
            candidate_id: 9, full_name: "Pracuje Test", category_id: null, furthest_stage: "hired",
            last_sent_at: null, last_sent_job_title: null, last_sent_client_name: null,
            sent_count: 1, days_since_last_send: null, expected_rate_hourly: null,
            availability_status: null, city: null, source: "auto", active_processes: 0,
            working: true, snoozed: false, snooze_reason: null, snoozed_at: null, new_matches: 0,
          },
        ]}
        snoozed={[]}
        categories={[]}
        actions={{ onAdd: vi.fn(), onSnooze: vi.fn() }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Pracują/ }));
    expect(screen.getByText("Pracuje Test")).toBeTruthy();
    expect(screen.queryByLabelText("Dodaj do rekrutacji: Pracuje Test")).toBeNull();
  });
});
