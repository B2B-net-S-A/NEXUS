import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AcademyCallView } from "@/components/academy/AcademyCallView";
import type { SessionsLoadState } from "@/components/academy/AcademyShared";
import type { AcademyApplication, AcademyProgram } from "@/lib/api/academy";

const program: AcademyProgram = {
  id: 1,
  name: "Akademia Rekrutera",
  is_active: true,
  max_experience_years: 6,
  require_polish: true,
  luna_enabled: true,
  conditions: [],
  session_capacity: 8,
  task_due_days: 5,
};

const caller = {
  id: 7,
  candidate_id: 7,
  full_name: "Anna Przykładowa",
  email: null,
  phone: "600100200",
  city: null,
  has_cv: true,
  source_job_id: 1,
  source_job_title: "Akademia Rekrutera",
  applied_at: "2026-09-20T10:00:00Z",
  status: "to_call",
  screening_verdict: "call",
  screening_reasons: [],
  screening_facts: {},
  screened_at: null,
  experience_years: 1,
  call_attempts: 0,
  last_call_at: null,
  session_id: null,
  session_starts_at: null,
  attended: null,
  task_due: null,
  task_result: null,
  contract_sent_at: null,
  signed_at: null,
  cohort_month: null,
  closed_stage: null,
  closed_reason: null,
  closed_at: null,
  reapplied_at: null,
  note: null,
  updated_at: "2026-09-20T10:00:00Z",
} as AcademyApplication;

function renderCall(sessionsState: SessionsLoadState) {
  return render(
    <AcademyCallView
      program={program}
      apps={[caller]}
      bookable={[]}
      onAct={vi.fn(async () => true)}
      busyIds={new Set()}
      sessionsState={sessionsState}
    />,
  );
}

describe("terminy w biurze: błąd i wczytywanie to nie „brak terminów”", () => {
  it("błąd zapytania pokazuje komunikat z „Ponów”, nie zachętę do dodania rytmu", async () => {
    const onRetry = vi.fn();
    renderCall({ loading: false, error: "Błąd serwera", onRetry });
    expect(screen.queryByText(/Nie ma przyszłych terminów/)).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać terminów");
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("w trakcie wczytywania mówi „Wczytuję terminy…”", () => {
    renderCall({ loading: true, error: null, onRetry: vi.fn() });
    expect(screen.getByText("Wczytuję terminy…")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma przyszłych terminów/)).toBeNull();
  });

  it("po wczytaniu pustej listy — dopiero wtedy „Nie ma przyszłych terminów”", () => {
    renderCall({ loading: false, error: null, onRetry: vi.fn() });
    expect(screen.getByText(/Nie ma przyszłych terminów/)).toBeInTheDocument();
  });
});
