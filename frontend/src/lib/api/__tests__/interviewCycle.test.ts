import { describe, expect, it } from "vitest";

import { cycleRefetchDelayMs } from "@/lib/api/interviewCycle";
import type { CycleOverview } from "@/lib/interview-cycle";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";

const NOW = Date.parse("2026-11-18T10:00:00Z");
const MIN = 60_000;

function overview(partial: Partial<CycleOverview>): CycleOverview {
  return {
    generated_at: new Date(NOW).toISOString(),
    scope: "mine",
    call_window_minutes: 30,
    items: [],
    agenda: [],
    todos: [],
    truncated: false,
    ...partial,
  };
}

function entry(startOffsetMin: number, endOffsetMin: number | null) {
  return {
    candidate_id: 1,
    candidate_name: "A",
    candidate_email: null,
    job_id: 2,
    job_title: "T",
    client_id: 3,
    client_name: "K",
    kind: "interview",
    start: new Date(NOW + startOffsetMin * MIN).toISOString(),
    end: endOffsetMin == null ? null : new Date(NOW + endOffsetMin * MIN).toISOString(),
    event_id: 9,
    slot_request_id: null,
    online_meeting_url: null,
    done: false,
  } as unknown as CycleOverview["agenda"][number];
}

describe("cycleRefetchDelayMs", () => {
  it("bez danych i bez granic: siatka bezpieczeństwa", () => {
    expect(cycleRefetchDelayMs(undefined, NOW)).toBe(WS_BACKED_SAFETY_POLL_MS);
    expect(cycleRefetchDelayMs(overview({}), NOW)).toBe(WS_BACKED_SAFETY_POLL_MS);
  });

  it("koniec rozmowy za 3 min: budzi się sekundę po nim", () => {
    expect(cycleRefetchDelayMs(overview({ agenda: [entry(-57, 3)] }), NOW)).toBe(3 * MIN + 1_000);
  });

  it("po końcu rozmowy liczy koniec okna telefonu", () => {
    // Koniec 10 min temu, okno 30 min → granica za 20 min, czyli sufit 5 min.
    expect(cycleRefetchDelayMs(overview({ agenda: [entry(-70, -10)] }), NOW)).toBe(
      WS_BACKED_SAFETY_POLL_MS,
    );
    expect(cycleRefetchDelayMs(overview({ agenda: [entry(-88, -28)] }), NOW)).toBe(2 * MIN + 1_000);
  });

  it("rozmowa bez końca trwa godzinę, a kwadrans przed startem to też granica", () => {
    expect(cycleRefetchDelayMs(overview({ agenda: [entry(-58, null)] }), NOW)).toBe(2 * MIN + 1_000);
    expect(cycleRefetchDelayMs(overview({ agenda: [entry(17, 77)] }), NOW)).toBe(2 * MIN + 1_000);
  });

  it("termin zadania w przyszłości jest granicą, przeszły nie", () => {
    const todo = (dueMin: number) =>
      ({
        kind: "debrief_overdue",
        due: new Date(NOW + dueMin * MIN).toISOString(),
      }) as unknown as CycleOverview["todos"][number];
    expect(cycleRefetchDelayMs(overview({ todos: [todo(1)] }), NOW)).toBe(MIN + 1_000);
    expect(cycleRefetchDelayMs(overview({ todos: [todo(-1)] }), NOW)).toBe(WS_BACKED_SAFETY_POLL_MS);
  });

  it("granica za chwilę nie zapętla odpytywania (dolny próg 5 s)", () => {
    const soon = overview({ agenda: [entry(-60, 0.01)] });
    expect(cycleRefetchDelayMs(soon, NOW)).toBe(5_000);
  });
});
