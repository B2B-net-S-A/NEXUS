/**
 * „Zespół opiekunów”: zaległe i zdrowie per opiekun z listy „Konsultanci”,
 * obciążenie z „Przydziału”, kolejność od zaległych.
 */
import { describe, expect, it } from "vitest";

import type { ConsultantRow, OwnerLoad } from "@/lib/api/care";

import {
  consultantsOfHref,
  doneText,
  inMonthPl,
  loadText,
  orphansText,
  ownerRoleText,
  portfolioText,
  settingsSummary,
  teamRows,
  withoutOwner,
} from "../team-format";

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

describe("Zespół opiekunów — teksty (makieta P6)", () => {
  it("osoba z puli bez podopiecznych ma wiersz; podpis roli", () => {
    const rows = teamRows([], [
      load(5, "Igor Testowy", { in_pool: true }),
      load(6, "Natalia Opiekuńcza", { is_tcm: true, in_pool: true, consultants: 7 }),
      load(7, "Kamil Testowy", { is_delivery_lead: true, consultants: 1 }),
      load(9, "Cezary Pusty"),
    ]);
    expect(rows.map((r) => r.name)).toEqual(["Natalia Opiekuńcza", "Kamil Testowy", "Igor Testowy"]);
    expect(rows.map(ownerRoleText)).toEqual([
      "TCM · w puli",
      "Delivery Lead · tylko swoi klienci",
      "w puli · bez podopiecznych",
    ]);
  });

  it("rozmowy z progiem, zrobione z przewidzianych, stan portfela", () => {
    expect(loadText({ conversations: 21, overThreshold: true })).toBe("21 rozmów — powyżej progu");
    expect(loadText({ conversations: 3, overThreshold: false })).toBe("3 rozmowy");
    expect(loadText({ conversations: null, overThreshold: false })).toBeNull();
    expect(doneText({ done: 9, planned: 11 })).toBe("9 z 11");
    expect(doneText({ done: 0, planned: 0 })).toBeNull();
    expect(doneText({ done: null, planned: null })).toBeNull();
    expect(portfolioText({ ok: 5, watch: 1, risk: 1 })).toBe("5 dobrze · 1 uwaga · 1 ryzyko");
    expect(portfolioText({ ok: 0, watch: 0, risk: 0 })).toBeNull();
    expect(inMonthPl("2026-11-01")).toBe("w listopadzie");
    expect(inMonthPl("2026-10-22")).toBe("w październiku");
    expect(consultantsOfHref(7)).toBe("/care?tab=consultants&owner=7");
  });

  it("pasek bez opiekuna i zwinięte ustawienia w jednej linii", () => {
    const igor = { id: 4, name: "Igor Testowy" };
    expect(
      orphansText([
        { contract_id: 1, candidate_name: "A", client_name: "Klinika Testowa IT", start_date: "2026-11-07", owner: igor },
        { contract_id: 2, candidate_name: "B", client_name: "Klinika Testowa IT", start_date: "2026-11-10", owner: igor },
      ]),
    ).toBe("2 konsultantów bez opiekuna (Klinika Testowa IT, start 07.11)");
    expect(orphansText([])).toBeNull();
    const summary = settingsSummary(
      {
        threshold: { monthly_conversations: 20 },
        clients: [
          { id: 1, name: "Bank", default_owner: igor, default_owner_active: true, consultants: 3 },
          { id: 2, name: "Klinika", default_owner: null, default_owner_active: false, consultants: 2 },
        ],
      },
      {
        pool: [
          { id: 4, name: "Igor Testowy", excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 0, consultants_after: 0 },
          { id: 5, name: "Beata Księgowa", excluded: true, sees_care: true, eligible: false, note: null, consultants_now: null, consultants_after: null },
        ],
        config: {
          manager: { id: 8, name: "Kamil Testowy" },
          manager_from_division: false,
          excluded_user_ids: [5],
          auto_new_contracts: true,
          saved: true,
        },
      },
    );
    expect(summary).toBe(
      "pula (przełożony Kamil T.): 2 osoby · „Nie przypisuj”: 1 · próg: 20 rozmów / mies. · nowy kontrakt → automat: włączony · domyślni opiekunowie klientów: 1 z 2",
    );
  });
});
