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
});
