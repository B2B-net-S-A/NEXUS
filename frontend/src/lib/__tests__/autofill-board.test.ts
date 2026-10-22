/**
 * Osoby od systemu na Tablicy (silnik „Nowi na 20”, 23.10.2026): plakietka,
 * termin decyzji, osoba na karcie, filtr „Kto dodał” i zdanie „Pracy w tle”.
 */
import { describe, expect, it } from "vitest";
import {
  addedByChoiceLabel,
  addedByEmptyColumnText,
  addedByOptions,
  addedByParam,
  addedByQueueSuffix,
  matchesAddedBy,
  parseAddedBy,
  type AddedByItem,
} from "@/lib/board-added-by";
import {
  autofillDecisionBadge,
  autofillSourceBadge,
  cardOwner,
  workdaysText,
} from "@/lib/board-card-badges";
import { backgroundEventMessage } from "@/lib/job-background-events";

const meta = {
  score: 81,
  matched_must: ["Java", "Spring"],
  missing_must: ["AWS"],
  rate_known: false,
  availability_known: true,
  decided: false,
  waiting_days: 3,
  decision_due: true,
};

describe("plakietki osoby od systemu", () => {
  it("mówi „Od systemu · 81%” z powodem w dymku", () => {
    const badge = autofillSourceBadge(meta);
    expect(badge?.label).toBe("Od systemu · 81%");
    expect(badge?.title).toContain("Spełnia: Java, Spring.");
    expect(badge?.title).toContain("Brakuje: AWS.");
    expect(badge?.title).toContain("Stawka nieznana.");
    expect(autofillSourceBadge(null)).toBeNull();
  });

  it("termin decyzji tylko po 2 dniach i z dniami roboczymi", () => {
    expect(autofillDecisionBadge(meta)?.label).toBe("3 dni bez decyzji");
    expect(autofillDecisionBadge({ ...meta, decision_due: false, waiting_days: 1 })).toBeNull();
    expect(autofillDecisionBadge({ ...meta, waiting_days: null })).toBeNull();
    expect(workdaysText(1)).toBe("1 dzień");
  });

  it("na karcie w „Nowych” właścicielem jest System, po weryfikacji — weryfikujący", () => {
    const item = { added_to_job_by_name: null, verified_by_name: null, entry_source: "system" as const };
    expect(cardOwner(item, "new")).toEqual({ name: "System", role: "added" });
    expect(cardOwner({ ...item, verified_by_name: "Ewa Lis" }, "cv_qc")).toEqual({
      name: "Ewa Lis",
      role: "verified",
    });
  });
});

describe("filtr „Kto dodał” z pozycją System", () => {
  const people: AddedByItem[] = [
    { candidate_id: 1, added_to_job_by_id: 7, added_to_job_by_name: "Marta Nowak" },
    { candidate_id: 2, added_to_job_by_id: null, entry_source: "system" },
    { candidate_id: 3, added_to_job_by_id: null, entry_source: "system" },
    { candidate_id: 4, added_to_job_by_id: null, entry_source: "import" },
  ];

  it("System ma własną pozycję, a „Brak danych” go nie liczy", () => {
    const options = addedByOptions(people, { id: 7, name: "Marta Nowak" });
    expect(options.map((o) => [o.label, o.count])).toEqual([
      ["Wszyscy", 4],
      ["Ty (Marta Nowak)", 1],
      ["System", 2],
      ["Brak danych", 1],
    ]);
  });

  it("filtruje po systemie i rozdziela go od braku danych", () => {
    const system = parseAddedBy("system");
    expect(addedByParam(system)).toBe("system");
    expect(people.filter((p) => matchesAddedBy(p, system)).map((p) => p.candidate_id)).toEqual([2, 3]);
    const none = parseAddedBy("none");
    expect(people.filter((p) => matchesAddedBy(p, none)).map((p) => p.candidate_id)).toEqual([4]);
    expect(addedByChoiceLabel(system, [])).toBe("System");
    expect(addedByQueueSuffix(system, [])).toBe("od systemu");
    expect(addedByEmptyColumnText(system, [])).toBe("Brak osób od systemu.");
  });
});

describe("Praca w tle", () => {
  it("mówi, ile osób system dodał", () => {
    expect(
      backgroundEventMessage({ id: 1, kind: "autofill", created_at: null, count: 3 }),
    ).toBe("System dodał do „Nowych” 3 osoby — kolumna trzyma się na 20.");
  });
});
