/**
 * Przypadki współdzielone z backendem (`backend/tests/test_next_action_parity.py`
 * czyta TEN SAM plik). Reguła „kto ma ruch" żyje w dwóch językach, więc pilnuje
 * jej jedna tabela, a nie dwa zestawy asercji, które rozjadą się przy pierwszej
 * poprawce po jednej stronie.
 */

import { describe, expect, it } from "vitest";

import fixtures from "@/lib/__fixtures__/next-action-cases.json";
import { NUDGE_DAYS, STUCK_DAYS, nextActionFor } from "@/lib/pipeline-next-action";
import type { PipelineGroupKey } from "@/lib/pipeline-flow";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

interface FixtureCase {
  name: string;
  group: string;
  column: { stage: string; category: string; terminal_type: string | null; name: string };
  item: { days_in_stage: number | null; screening_done: boolean | null; hm_veto: boolean };
  sla_days: number | null;
  expected: { label: string; tone: string; kind: string; owner: string };
}

const VETO: NonNullable<KanbanItem["hm_veto"]> = {
  hiring_manager_contact_id: 1,
  source_job_id: 1,
  rejected_at: "2026-09-01T00:00:00Z",
  rejection_reason_name: "Brak dopasowania",
};

describe("nextActionFor — przypadki wspólne z backendem", () => {
  it("stałe progów zgadzają się z plikiem przypadków", () => {
    expect(fixtures.nudge_days).toBe(NUDGE_DAYS);
    expect(fixtures.stuck_days).toBe(STUCK_DAYS);
  });

  it.each((fixtures.cases as FixtureCase[]).map((c) => [c.name, c] as const))(
    "%s",
    (_name, c) => {
      const column = {
        stage: c.column.stage,
        category: c.column.category,
        terminal_type: c.column.terminal_type,
        name: c.column.name,
        count: 1,
        items: [],
      } as unknown as KanbanColumn;
      const item = {
        id: 1,
        candidate_id: 1,
        stage: c.column.stage,
        ...(c.item.days_in_stage == null ? {} : { days_in_stage: c.item.days_in_stage }),
        ...(c.item.screening_done == null ? {} : { screening_done: c.item.screening_done }),
        hm_veto: c.item.hm_veto ? VETO : null,
      } as KanbanItem;
      expect(
        nextActionFor(item, column, {
          group: c.group as PipelineGroupKey,
          slaDays: c.sla_days,
        }),
      ).toEqual(c.expected);
    },
  );
});
