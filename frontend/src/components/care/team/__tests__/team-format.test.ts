/**
 * „Zespół opiekunów”: zaległe i zdrowie per opiekun z listy „Konsultanci”,
 * obciążenie z „Przydziału”, kolejność od zaległych.
 */
import { describe, expect, it } from "vitest";

import type { ConsultantRow, OwnerLoad } from "@/lib/api/care";

import { teamRows, withoutOwner } from "../team-format";

function row(id: number, owner: { id: number; name: string } | null, extra: Partial<ConsultantRow> = {}): ConsultantRow {
  return {
    contract_id: id,
    candidate_id: id,
    candidate_name: `Osoba ${id}`,
    client_id: 1,
    client_name: "Bank",
    job_title: null,
    contract_type: "b2b",
    start_date: null,
    end_date: null,
    owner,
    is_mine: false,
    manager: null,
    cadence: {
      level: "monthly",
      source: "default",
      starts_on: null,
      until_on: null,
      returns_to: null,
      reason: null,
      note: null,
      author: null,
    },
    next_contact: null,
    last_conversation: null,
    signals: [],
    suggested_level: null,
    conversations: { this_month: 1, next_month: 1 },
    can_change_cadence: false,
    ...extra,
  };
}

const overdue = {
  due_on: "2026-10-01",
  label: "Rozmowa",
  overdue: true,
  plan_item_id: 1,
  kind: "cadence" as const,
  overdue_days: 21,
};

const load = (id: number, name: string, extra: Partial<OwnerLoad> = {}): OwnerLoad => ({
  id,
  name,
  is_delivery_lead: false,
  consultants: 0,
  conversations: 0,
  by_level: {},
  clients: [],
  over_threshold: false,
  ...extra,
});

describe("teamRows", () => {
  it("zlicza podopiecznych, zaległe i zdrowie; obciążenie z przydziału; najpierw zaległe", () => {
    const anna = { id: 1, name: "Anna Opiekun" };
    const borys = { id: 2, name: "Borys Opiekun" };
    const rows = teamRows(
      [
        row(1, anna, { health: { level: "risk", label: "Ryzyko", reasons: [] } }),
        row(2, anna),
        row(3, borys, { next_contact: overdue, health: { level: "ok", label: "Dobrze", reasons: [] } }),
        row(4, null),
      ],
      [load(1, "Anna Opiekun", { conversations: 5, consultants: 2 }), load(9, "Cezary Pusty"), load(2, "Borys Opiekun", { conversations: 25, over_threshold: true, is_delivery_lead: true })],
    );
    expect(rows.map((r) => r.name)).toEqual(["Borys Opiekun", "Anna Opiekun"]);
    expect(rows[0]).toMatchObject({ consultants: 1, overdue: 1, conversations: 25, overThreshold: true, isDeliveryLead: true });
    expect(rows[1]).toMatchObject({ consultants: 2, overdue: 0, health: { ok: 0, watch: 0, risk: 1 }, conversations: 5 });
  });

  it("opiekun tylko w przydziale (spoza zakresu listy) też ma wiersz; bez opiekuna liczony osobno", () => {
    const rows = teamRows([], [load(3, "Daria", { consultants: 4, conversations: 6 })]);
    expect(rows).toEqual([
      expect.objectContaining({ id: 3, consultants: 4, overdue: 0, conversations: 6 }),
    ]);
    expect(withoutOwner([row(1, null), row(2, { id: 1, name: "A" })])).toBe(1);
  });
});
