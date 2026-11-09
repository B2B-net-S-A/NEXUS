import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { ForJobResponse } from "@/lib/api/myPeople";
import { contextFromPath, shouldCloseOnEscape } from "../MyPeoplePanel";
import { ForJobView, FromLinksView, PeopleListView } from "../MyPeopleViews";

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

  it("flags a rate above the job budget and stays quiet within it", () => {
    render(
      <ForJobView
        data={{
          ...base,
          rate_budget_hourly: 70,
          rows: [
            {
              candidate_id: 5, full_name: "Drogi Test", category_id: null, score: 70,
              measurement: "measured", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: 120, active_processes: 0,
            },
            {
              candidate_id: 6, full_name: "Tani Test", category_id: null, score: 68,
              measurement: "measured", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: 60, active_processes: 0,
            },
          ],
        }}
        actions={{}}
      />,
    );
    expect(screen.getAllByText("oczekuje +71% ponad budżet")).toHaveLength(1);
    expect(screen.getByText(/budżet 70 zł\/h/)).toBeTruthy();
  });

  it("without a job budget no row is flagged", () => {
    render(
      <ForJobView
        data={{
          ...base,
          rows: [
            {
              candidate_id: 7, full_name: "Bez Budżetu", category_id: null, score: 70,
              measurement: "measured", eligibility: null, sent_to_client_at: null,
              last_sent_client_name: null, days_since_last_send: null,
              expected_rate_hourly: 200, active_processes: 0,
            },
          ],
        }}
        actions={{}}
      />,
    );
    expect(screen.queryByText(/ponad budżet/)).toBeNull();
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
  it("pozwala dodać osobę z grupy „Pracują” i mówi, u kogo pracuje", () => {
    const onAdd = vi.fn();
    const marker = {
      phase: "working" as const,
      source: "contract" as const,
      clients: [
        {
          client_id: 3,
          client_name: "Bank Przykładowy",
          contract_id: 30,
          phase: "working" as const,
          order_end_date: "2026-12-31",
        },
      ],
    };
    render(
      <PeopleListView
        active={[]}
        working={[
          {
            candidate_id: 9, full_name: "Pracuje Test", category_id: null, furthest_stage: "hired",
            last_sent_at: null, last_sent_job_title: null, last_sent_client_name: null,
            sent_count: 1, days_since_last_send: null, expected_rate_hourly: null,
            availability_status: null, city: null, source: "auto", active_processes: 0,
            working: true, employment_marker: marker,
            snoozed: false, snooze_reason: null, snoozed_at: null, new_matches: 0,
          },
        ]}
        snoozed={[]}
        categories={[]}
        actions={{ onAdd, onSnooze: vi.fn() }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Pracują/ }));
    expect(screen.getByText("Aktywne zamówienie · nie dzwoń")).toBeTruthy();
    // Do 12.10.2026 przycisku nie było — pracującej osoby nie dało się dodać.
    fireEvent.click(screen.getByLabelText("Dodaj do rekrutacji: Pracuje Test"));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ candidate_id: 9, employment_marker: marker }),
    );
  });
});

describe("FromLinksView", () => {
  const base = {
    applied_at: "2026-10-28T09:12:00Z",
    was_duplicate: false,
    current_job_id: null,
    current_job_title: null,
    screening_status: null,
    screening_outcome: null,
  };

  it("pokazuje oba rodzaje linków i to, czy osoba jest na głównej liście", () => {
    const onAdd = vi.fn();
    render(
      <FromLinksView
        onAdd={onAdd}
        people={[
          {
            ...base,
            candidate_id: 1,
            full_name: "Celina Fikcyjna",
            kind: "job",
            slug: "java-7kq2",
            job_id: 101,
            job_title: "Senior Java Developer",
            current_stage: "new",
            in_my_people: false,
          },
          {
            ...base,
            candidate_id: 2,
            full_name: "Damian Testowy",
            kind: "recruiter",
            slug: "marta-n",
            job_id: null,
            job_title: null,
            current_stage: null,
            in_my_people: true,
          },
        ]}
      />,
    );
    expect(screen.getByText("link do rekrutacji")).toBeInTheDocument();
    expect(screen.getByText("link ogólny")).toBeInTheDocument();
    expect(screen.getByText(/Nowy · poza listą/)).toBeInTheDocument();
    expect(screen.getByText(/W bazie, bez nowej rekrutacji · także na liście/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do rekrutacji: Celina Fikcyjna" }));
    expect(onAdd).toHaveBeenCalledWith({ candidate_id: 1, full_name: "Celina Fikcyjna" });
  });

  it("pusty stan mówi, co się tu pojawi", () => {
    render(<FromLinksView people={[]} />);
    expect(screen.getByText("Nikt jeszcze nie zgłosił się z Twoich linków")).toBeInTheDocument();
  });
});
