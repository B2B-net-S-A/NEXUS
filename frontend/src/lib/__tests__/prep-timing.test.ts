/**
 * Runda 10 (F08): termin prepu podpowiada się PRZED rozmową u klienta,
 * a kolizja albo prep po rozmowie dają ostrzeżenie.
 */
import { describe, expect, it } from "vitest";

import {
  defaultPrepStart,
  nextWorkdayAt,
  prepInterviewForPair,
  prepTimingWarning,
  scheduledInterviewFromSteps,
  toLocalInput,
} from "@/lib/prep-timing";
import type { CycleOverview } from "@/lib/interview-cycle";

// Czwartek 24.09.2026, 9:00 czasu przeglądarki.
const NOW = new Date(2026, 8, 24, 9, 0);
const local = (y: number, m: number, d: number, h: number, min = 0) =>
  new Date(y, m - 1, d, h, min).toISOString();

describe("defaultPrepStart", () => {
  it("rozmowa w poniedziałek 10:00 → Prep 1 w piątek 10:00, nie na rozmowie", () => {
    const interview = { start: local(2026, 9, 28, 10), end: local(2026, 9, 28, 11) };
    const start = defaultPrepStart(interview, 1, 45, NOW);
    expect(start).toBe("2026-09-25T10:00");
    expect(prepTimingWarning(start, 45, interview)).toBeNull();
  });

  it("Prep 2 — dwie godziny przed rozmową", () => {
    const interview = { start: local(2026, 9, 28, 14) };
    expect(defaultPrepStart(interview, 2, 45, NOW)).toBe("2026-09-28T12:00");
  });

  it("rozmowa jutro rano: dzień przed już był, prep wypada przed rozmową", () => {
    const interview = { start: local(2026, 9, 25, 10), end: local(2026, 9, 25, 11) };
    // Poprzedni dzień roboczy = dziś 10:00 — jeszcze przed nami.
    expect(defaultPrepStart(interview, 1, 45, NOW)).toBe("2026-09-24T10:00");
    const late = new Date(2026, 8, 24, 18, 0);
    const start = defaultPrepStart(interview, 1, 45, late);
    expect(start).toBe("2026-09-25T08:00");
    expect(prepTimingWarning(start, 45, interview)).toBeNull();
  });

  it("rozmowa za pół godziny: nie ma miejsca na prep — ostrzeżenie zostaje", () => {
    const interview = { start: local(2026, 9, 24, 9, 30), end: local(2026, 9, 24, 10, 30) };
    const start = defaultPrepStart(interview, 1, 45, NOW);
    expect(prepTimingWarning(start, 45, interview)).toMatch(/nakłada się/);
  });

  it("bez rozmowy albo po rozmowie — dotychczasowa podpowiedź (jutro 10:00)", () => {
    expect(defaultPrepStart(null, 1, 45, NOW)).toBe(nextWorkdayAt(10, NOW));
    expect(defaultPrepStart({ start: local(2026, 9, 23, 10) }, 1, 45, NOW)).toBe(
      nextWorkdayAt(10, NOW),
    );
  });
});

describe("prepTimingWarning", () => {
  const interview = { start: local(2026, 9, 28, 10), end: local(2026, 9, 28, 11) };

  it("prep o tej samej godzinie co rozmowa to kolizja (zgłoszenie F08)", () => {
    expect(prepTimingWarning("2026-09-28T10:00", 45, interview)).toMatch(
      /nakłada się na rozmowę u klienta/,
    );
  });

  it("prep kończący się po starcie rozmowy to kolizja", () => {
    expect(prepTimingWarning("2026-09-28T09:30", 45, interview)).toMatch(/nakłada się/);
  });

  it("prep po rozmowie to zła kolejność", () => {
    expect(prepTimingWarning("2026-09-28T11:00", 45, interview)).toMatch(/po rozmowie/);
  });

  it("prep kończący się dokładnie o starcie rozmowy jest w porządku", () => {
    expect(prepTimingWarning("2026-09-28T09:15", 45, interview)).toBeNull();
  });

  it("bez rozmowy nie ma ostrzeżenia", () => {
    expect(prepTimingWarning("2026-09-28T10:00", 45, null)).toBeNull();
  });

  it("termin jeszcze niepotwierdzony: prep po propozycji klienta ostrzega, przed nią nie", () => {
    // 02.10.2026: Prep 1 zaplanowano dwa dni po obu terminach od klienta,
    // bo okno nie wiedziało o żadnym.
    const tentative = { start: local(2026, 9, 28, 10), tentative: true };
    expect(prepTimingWarning("2026-09-30T14:00", 30, tentative)).toMatch(
      /nie jest jeszcze potwierdzony/,
    );
    expect(prepTimingWarning("2026-09-25T10:00", 45, tentative)).toBeNull();
    expect(defaultPrepStart(tentative, 1, 45, NOW)).toBe("2026-09-25T10:00");
  });
});

describe("rozmowa z kroków i z agendy", () => {
  it("bierze tylko zaplanowaną rozmowę", () => {
    expect(
      scheduledInterviewFromSteps([{ key: "interview", state: "scheduled", at: "2026-09-28T08:00:00Z" }]),
    ).toEqual({ start: "2026-09-28T08:00:00Z" });
    expect(
      scheduledInterviewFromSteps([{ key: "interview", state: "done", at: "2026-09-20T08:00:00Z" }]),
    ).toBeNull();
  });

  it("koniec rozmowy z agendy ekranu", () => {
    const data = {
      items: [
        {
          candidate_id: 1,
          job_id: 2,
          steps: [{ key: "interview", state: "scheduled", at: "2026-09-28T08:00:00Z", event_id: 9 }],
        },
      ],
      agenda: [{ kind: "interview", event_id: 9, start: "2026-09-28T08:00:00Z", end: "2026-09-28T09:00:00Z" }],
    } as unknown as CycleOverview;
    expect(prepInterviewForPair(data, { candidate_id: 1, job_id: 2 })).toEqual({
      start: "2026-09-28T08:00:00Z",
      end: "2026-09-28T09:00:00Z",
    });
    expect(toLocalInput(new Date(2026, 0, 5, 7, 5))).toBe("2026-01-05T07:05");
  });

  it("bez potwierdzonej rozmowy bierze termin, który czeka na potwierdzenie", () => {
    const data = {
      items: [
        {
          candidate_id: 1,
          job_id: 2,
          steps: [{ key: "interview", state: "todo", at: null, event_id: null }],
          tentative_interview_at: "2026-10-05T08:00:00+00:00",
        },
      ],
      agenda: [],
    } as unknown as CycleOverview;
    expect(prepInterviewForPair(data, { candidate_id: 1, job_id: 2 })).toEqual({
      start: "2026-10-05T08:00:00+00:00",
      tentative: true,
    });
  });
});
