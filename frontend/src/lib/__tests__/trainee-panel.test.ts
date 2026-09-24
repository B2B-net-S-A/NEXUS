import { describe, expect, it } from "vitest";

import type { TraineeOverviewRow } from "@/lib/api/trainee";
import {
  decisionSummary,
  draftFromRules,
  rulesFromDraft,
  lowAnswerNote,
  plural,
  poolWorkdays,
  qualityLabel,
  traineeState,
} from "@/lib/trainee-panel";

function row(over: Partial<TraineeOverviewRow> = {}): TraineeOverviewRow {
  return {
    user_id: 1,
    name: "Osoba Testowa",
    is_active: true,
    program: {
      start_date: "2026-09-01",
      workdays: 40,
      extended_days: 0,
      daily_list_size: 70,
      status: "active",
      day: 12,
      total_days: 40,
      end_date: "2026-10-27",
      decision_due: false,
    },
    days_with_list: 12,
    days_completed: 11,
    calls_per_day: 29,
    answered_pct: 41,
    complete_profiles_pct: 94,
    handed_over: 3,
    handed_in_process: 1,
    quality: { checked: 5, issues: 0 },
    flag_low_answer: false,
    ...over,
  };
}

describe("stan praktykanta", () => {
  it("decyzja wygrywa z resztą", () => {
    const r = row({ flag_low_answer: true });
    r.program = { ...r.program!, decision_due: true };
    expect(traineeState(r)).toBe("decision");
  });

  it("niski odsetek odebranych albo 2+ uwagi → do sprawdzenia", () => {
    expect(traineeState(row({ flag_low_answer: true }))).toBe("check");
    expect(traineeState(row({ quality: { checked: 3, issues: 2 } }))).toBe("check");
  });

  it("poniżej 80% zaliczonych dni → poniżej normy", () => {
    expect(traineeState(row({ days_with_list: 12, days_completed: 7 }))).toBe("below_norm");
    expect(traineeState(row())).toBe("ok");
  });

  it("bez programu i po zakończeniu", () => {
    expect(traineeState(row({ program: null }))).toBe("not_started");
    const ended = row();
    ended.program = { ...ended.program!, status: "ended" };
    expect(traineeState(ended)).toBe("ended");
  });
});

describe("teksty panelu", () => {
  it("odmiana: uwaga / uwagi / uwag", () => {
    expect(plural(1, "uwaga", "uwagi", "uwag")).toBe("uwaga");
    expect(plural(3, "uwaga", "uwagi", "uwag")).toBe("uwagi");
    expect(plural(12, "uwaga", "uwagi", "uwag")).toBe("uwag");
    expect(plural(22, "uwaga", "uwagi", "uwag")).toBe("uwagi");
    expect(qualityLabel({ checked: 10, issues: 0 })).toBe("10 sprawdz., 0 uwag");
    expect(qualityLabel({ checked: 0, issues: 0 })).toBe("nie sprawdzano");
  });

  it("podsumowanie decyzji", () => {
    expect(
      decisionSummary(
        row({ days_with_list: 40, days_completed: 37, calls_per_day: 27, complete_profiles_pct: 91, handed_over: 11, handed_in_process: 4, quality: { checked: 10, issues: 0 } }),
      ),
    ).toBe(
      "Zaliczone 37 z 40 dni · 27 rozmów dziennie · 91% pełnych profili · 11 przekazanych, 4 weszły do procesu · próbka jakości bez uwag",
    );
  });

  it("notatka o niskim odsetku odebranych mówi, co zrobić", () => {
    expect(lowAnswerNote(row({ name: "Natalia Król", answered_pct: 6 }), 35)).toBe(
      "Natalia Król: odebrane 6% przy średniej 35% — większość pozycji to „Nie odbiera”. Sprawdź próbkę jakości, zanim uznasz dni za zaliczone.",
    );
  });

  it("starczalność puli: aktywni × dzienna lista; bez aktywnych — null", () => {
    const pool = { size: 8420, open_fit: 1310, by_category: [] };
    expect(poolWorkdays(pool, [row(), row({ user_id: 2 }), row({ user_id: 3 }), row({ user_id: 4 })])).toBe(30);
    expect(poolWorkdays(pool, [row({ is_active: false })])).toBeNull();
  });
});

describe("reguły listy", () => {
  const rules = {
    min_fits: 2, window_months: 18, rate_stale_months: 6, verified_recently_days: 90,
    process_active_days: 30, my_people_contact_days: 30, trainee_recall_days: 60,
    missing_rate: true, missing_availability: true, missing_work_mode: true,
    missing_consents: true, missing_b2b: true, missing_work_time: false,
  };

  it("szkic ↔ reguły bez strat", () => {
    expect(rulesFromDraft(draftFromRules(rules))).toEqual({ rules, errors: {} });
  });

  it("puste, ułamkowe i poniżej minimum nie przechodzą — „pasuje do 0” wpuściłoby całą bazę", () => {
    const draft = { ...draftFromRules(rules), min_fits: "0", window_months: "", trainee_recall_days: "1.5" };
    const result = rulesFromDraft(draft);
    expect(result.rules).toBeNull();
    expect(Object.keys(result.errors).sort()).toEqual(["min_fits", "trainee_recall_days", "window_months"]);
  });

  it("zero dni jest dozwolone tam, gdzie znaczy „bez karencji”", () => {
    expect(rulesFromDraft({ ...draftFromRules(rules), process_active_days: "0" }).rules?.process_active_days).toBe(0);
  });
});
