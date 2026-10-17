/** Pomocniki listy „Opieka · Ten tydzień” — powód, tydzień, „Ostatnio”, toast przekazania. */
import { describe, expect, it } from "vitest";

import { handoffToast } from "@/components/care/week/FrontOfficeSection";
import { contractParam } from "@/components/care/week/WeekPanel";
import {
  daysBetween,
  frontOfficeText,
  lastContactText,
  reasonText,
  shiftIso,
  shortNames,
  weekRangeLabel,
} from "@/components/care/week/week-format";
import type { WeekContact, WeekReason } from "@/lib/api/care";

function reason(overrides: Partial<WeekReason>): WeekReason {
  return {
    kind: "day_30",
    label: "Dzień 30",
    due_on: "2026-10-14",
    overdue: false,
    plan_item_id: 1,
    from_conversation_on: null,
    ...overrides,
  };
}

function row(overrides: Partial<WeekContact>): WeekContact {
  return {
    contract_id: 1,
    candidate_id: 2,
    candidate_name: "Ewa Przykładowa",
    client_id: 3,
    client_name: "Firma Testowa",
    job_title: null,
    start_date: null,
    end_date: null,
    owner: null,
    reasons: [reason({})],
    due_on: "2026-10-14",
    overdue: false,
    overdue_days: 0,
    plan_item_id: 1,
    manager: null,
    last_conversation: null,
    signals: [],
    front_office: { reasons: [], handed_off_on: null },
    ...overrides,
  };
}

describe("tydzień", () => {
  it("przesuwa daty bez strefy i podpisuje tydzień pracy", () => {
    expect(shiftIso("2026-10-19", 7)).toBe("2026-10-26");
    expect(shiftIso("2026-11-02", -7)).toBe("2026-10-26");
    expect(weekRangeLabel("2026-10-19", "2026-10-23")).toBe("19–23.10");
    expect(weekRangeLabel("2026-10-26", "2026-10-30")).toBe("26–30.10");
    expect(weekRangeLabel("2026-11-30", "2026-12-04")).toBe("30.11–04.12");
    expect(daysBetween("2026-10-11", "2026-10-14")).toBe(3);
  });
});

describe("powód kontaktu", () => {
  const today = "2026-10-14";

  it("zaległy, dziś, w tym tygodniu, umówiony i przed końcem", () => {
    expect(reasonText(reason({ due_on: "2026-10-11", overdue: true }), today)).toBe(
      "zaległy 3 dni · dzień 30",
    );
    expect(reasonText(reason({ due_on: "2026-10-13", overdue: true }), today)).toBe(
      "zaległy 1 dzień · dzień 30",
    );
    expect(reasonText(reason({ due_on: today }), today)).toBe("dziś · dzień 30");
    expect(
      reasonText(
        reason({
          kind: "follow_up",
          label: "Umówiony kontakt",
          due_on: "2026-10-16",
          plan_item_id: null,
          from_conversation_on: "2026-10-01",
        }),
        today,
      ),
    ).toBe("16.10 · umówiony kontakt z 01.10");
    expect(
      reasonText(reason({ kind: "pre_end", label: "Przed końcem zamówienia", due_on: "2026-10-15" }), today),
    ).toBe("15.10 · 30 dni przed końcem zamówienia");
  });

  it("„Ostatnio”: sygnał z kolejki przepięć wygrywa z notatką", () => {
    const talked = {
      id: 1,
      occurred_on: "2026-10-01",
      satisfaction: 4,
      note_excerpt: "Dobrze, chce więcej pracy z Kafką.",
      signals: [],
    };
    expect(lastContactText(row({ last_conversation: talked }))).toBe(
      "Dobrze, chce więcej pracy z Kafką.",
    );
    expect(lastContactText(row({ last_conversation: talked, signals: ["wants_change"] }))).toBe(
      "sygnał: chce zmiany projektu",
    );
    expect(lastContactText(row({}))).toBeNull();
  });

  it("front office i skrócone nazwiska w prośbie o opinię", () => {
    expect(frontOfficeText(["project_end", "wants_change"])).toBe(
      "kończy projekt · chce zmiany projektu",
    );
    expect(shortNames(["Jan Kowalski-Przykładowy", "Ewa Lis", null])).toBe(
      "Jan K., Ewa L., konsultant",
    );
  });
});

describe("panel i przekazanie", () => {
  it("`?contract=` tylko z dodatnią liczbą całkowitą", () => {
    expect(contractParam("4504")).toBe(4504);
    expect(contractParam("0")).toBeNull();
    expect(contractParam("abc")).toBeNull();
    expect(contractParam(null)).toBeNull();
  });

  it("toast mówi, kto naprawdę dostał powiadomienie", () => {
    const base = {
      contract_id: 1,
      handed_off_on: "2026-10-14",
      reasons: ["project_end" as const],
      job_ids: [],
      recipients: [{ id: 7, name: "Anna DL" }],
      redeploy_item_id: 3,
    };
    expect(handoffToast({ ...base, notified: [{ id: 7, name: "Anna DL" }] })).toEqual({
      text: "Przekazano do front office. Powiadomieni: Anna DL.",
      tone: "success",
    });
    expect(handoffToast({ ...base, notified: [] }).tone).toBe("info");
  });
});
