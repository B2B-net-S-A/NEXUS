/**
 * Dok osoby na Tablicy rekrutacji planuje prep bez ekranu „Rozmowy u klienta”.
 * 02.10.2026 tędy powstał Prep 1 dwa dni po obu terminach od klienta: dok nie
 * znał terminu, który dopiero czekał na wybór, a po potwierdzeniu rozmowy
 * proponował zaplanowanie Prepu 1 jeszcze raz.
 */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const planPrepProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

vi.mock("@/components/calendar/cycle/PlanPrepDialog", () => ({
  PlanPrepDialog: (props: Record<string, unknown>) => {
    planPrepProps.current = props;
    return <div data-testid="plan-prep-dialog" />;
  },
}));

const rescheduleProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

vi.mock("@/components/calendar/cycle/ReschedulePrepDialog", () => ({
  ReschedulePrepDialog: (props: Record<string, unknown>) => {
    rescheduleProps.current = props;
    return <div data-testid="reschedule-prep-dialog" />;
  },
}));

const slotProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

vi.mock("@/components/calendar/cycle/SlotDialogs", () => ({
  SlotDecisionDialog: (props: Record<string, unknown>) => {
    slotProps.current = props;
    return <div data-testid="slot-decision-dialog" />;
  },
}));

const prepReviewProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

vi.mock("@/components/calendar/cycle/PrepReviewDialog", () => ({
  PrepReviewDialog: (props: Record<string, unknown>) => {
    prepReviewProps.current = props;
    return <div data-testid="prep-review-dialog" />;
  },
}));

const debriefProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));

vi.mock("@/components/calendar/cycle/DebriefDialog", () => ({
  DebriefDialog: (props: Record<string, unknown>) => {
    debriefProps.current = props;
    return <div data-testid="debrief-dialog" />;
  },
}));

import { DockInterviewCycle } from "@/components/v2/jobs/DockInterviewCycle";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { StepKey, StepState } from "@/lib/interview-cycle";

const PAIR = {
  candidate_id: 11,
  candidate_name: "Jan Przykładowy",
  candidate_email: "jan@example.com",
  job_id: 22,
  job_title: "Java Developer",
  client_id: 33,
  client_name: "Bank Przykładowy",
};

function steps(overrides: Partial<Record<StepKey, StepState>>, interviewAt?: string) {
  const keys: StepKey[] = ["slots", "choice", "prep", "prep2", "interview", "call", "debrief"];
  return keys.map((key) => ({
    key,
    state: overrides[key] ?? ("todo" as StepState),
    at: key === "interview" ? (interviewAt ?? null) : null,
  }));
}

function badge(
  extra: Partial<NonNullable<KanbanItem["interview_badge"]>>,
): NonNullable<KanbanItem["interview_badge"]> {
  return { kind: "slot", label: "pon 05.10 · 14:00", tone: "info", ...extra };
}

describe("DockInterviewCycle", () => {
  it("prep po rozmowie u klienta: „Przełóż”, nie „Zaplanuj Prep 1”", () => {
    render(
      <DockInterviewCycle
        badge={badge({
          steps: steps({ slots: "done", choice: "done", prep: "overdue", interview: "scheduled" }),
          late_prep_event_id: 604,
        })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
      />,
    );
    // Przełożenie TEGO spotkania na miejscu, nie przejście do kalendarza.
    expect(screen.queryByRole("link", { name: /Przełóż prep/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Przełóż prep/ }));
    expect(screen.getByTestId("reschedule-prep-dialog")).toBeInTheDocument();
    expect(rescheduleProps.current).toEqual(
      expect.objectContaining({ eventId: 604, prepNo: 1, pair: PAIR }),
    );
    // Prep 1 już istnieje (po rozmowie) — do zaplanowania zostaje tylko Prep 2.
    expect(screen.queryByRole("button", { name: "Zaplanuj Prep 1" })).toBeNull();
    expect(screen.getByRole("button", { name: "Zaplanuj Prep 2" })).toBeInTheDocument();
  });

  it("potwierdzona rozmowa: okno prepu dostaje jej termin z kroków odznaki", () => {
    render(
      <DockInterviewCycle
        badge={badge({
          steps: steps(
            { slots: "done", choice: "done", prep: "current", interview: "scheduled" },
            "2031-10-05T12:00:00+00:00",
          ),
          // Termin potwierdzony wygrywa z propozycją, gdyby serwer podał oba.
          tentative_interview_at: "2031-10-07T08:00:00+00:00",
        })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj Prep 1" }));
    expect(planPrepProps.current?.interview).toEqual({ start: "2031-10-05T12:00:00+00:00" });
  });

  it("termin rozmowy czeka na wybór: okno prepu dostaje go jako niepotwierdzony", () => {
    render(
      <DockInterviewCycle
        badge={badge({
          kind: "choose_slot",
          label: "Wybierz termin · 2 propozycje",
          tone: "wait",
          steps: steps({ slots: "done", choice: "current" }),
          tentative_interview_at: "2031-10-05T08:00:00+00:00",
        })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj Prep 1" }));
    expect(screen.getByTestId("plan-prep-dialog")).toBeInTheDocument();
    expect(planPrepProps.current?.interview).toEqual({
      start: "2031-10-05T08:00:00+00:00",
      tentative: true,
    });
  });

  // PR 6 (04.10.2026): termin od klienta i ocena prepu w panelu osoby.
  const REQUEST = {
    id: 77,
    status: "awaiting_recruiter" as const,
    slots: [{ start: "2026-10-08T12:00:00Z", end: null }],
    chosen_index: null,
    respond_by: null,
    recruiter_id: 5,
    created_by: 6,
    duration_minutes: 60,
    note: null,
    event_id: null,
  };

  it("wniosek czeka na rekrutera: „Wybierz termin z kandydatem” otwiera wybór na miejscu", () => {
    render(
      <DockInterviewCycle
        badge={badge({ steps: steps({ slots: "done", choice: "current" }), slot_request: REQUEST })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
        onAddClientSlots={() => {}}
      />,
    );
    // Wniosek już jest — drugi „Terminy od klienta” byłby duplikatem.
    expect(screen.queryByRole("button", { name: "Terminy od klienta" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Wybierz termin z kandydatem" }));
    expect(slotProps.current).toEqual(expect.objectContaining({ mode: "pick", request: REQUEST, pair: PAIR }));
  });

  it("potwierdzenie terminu widzi tylko osoba z prawem do terminów od klienta", () => {
    const confirmBadge = badge({
      steps: steps({ slots: "done", choice: "done" }),
      slot_request: { ...REQUEST, status: "awaiting_dl", chosen_index: 0 },
    });
    const { rerender } = render(
      <DockInterviewCycle badge={confirmBadge} pair={PAIR} readOnly={false} onDebrief={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: "Potwierdź termin" })).toBeNull();
    rerender(
      <DockInterviewCycle
        badge={confirmBadge}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
        onAddClientSlots={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź termin" }));
    expect(slotProps.current).toEqual(expect.objectContaining({ mode: "confirm" }));
  });

  it("prep z oceną otwiera okno oceny prepu", () => {
    render(
      <DockInterviewCycle
        badge={badge({
          steps: steps({ slots: "done", choice: "done", prep: "done" }),
          preps: [
            { id: 901, prep_no: 1, start: null, review_status: "ok", transcript_status: "ready" },
            { id: 902, prep_no: 2, start: null, review_status: null, transcript_status: null },
          ],
        })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "Ocena prepu 2" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ocena prepu 1" }));
    expect(prepReviewProps.current).toEqual(expect.objectContaining({ eventId: 901 }));
  });
});

describe("DockInterviewCycle — zapisany debrief (04.10.2026)", () => {
  it("pokazuje skrót z warunkiem kandydata i otwiera cały debrief", () => {
    render(
      <DockInterviewCycle
        badge={badge({
          kind: "debrief_done",
          label: "Debrief ✓",
          tone: "ok",
          interview_event_id: 44,
          steps: steps({ interview: "done", call: "done", debrief: "done" }),
          debrief: {
            id: 5,
            overall_impression: 5,
            outcome: "good",
            offer_acceptance: "likely",
            acceptance_condition: "Chce jednak 125 zł/h",
            candidate_comment: null,
            questions_count: 4,
            no_client_questions: false,
          },
        })}
        pair={PAIR}
        readOnly={false}
        onDebrief={() => {}}
      />,
    );
    const summary = screen.getByTestId("dock-debrief-summary");
    expect(summary).toHaveTextContent("dobrze · raczej przyjmie · 4 pytania klienta");
    expect(summary).toHaveTextContent("Warunek: Chce jednak 125 zł/h");
    fireEvent.click(screen.getByRole("button", { name: "Cały debrief" }));
    expect(screen.getByTestId("debrief-dialog")).toBeInTheDocument();
    expect(debriefProps.current?.eventId).toBe(44);
    expect(debriefProps.current?.readOnly).toBe(false);
  });
});
