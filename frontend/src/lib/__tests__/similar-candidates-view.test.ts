import { describe, expect, it } from "vitest";

import {
  checkVerdict,
  verdictText,
  type CandidateCheck,
} from "@/lib/api/similarCandidates";
import {
  addPlan,
  checksByCandidate,
  defaultSelected,
  mergePickableJobs,
  personName,
  prettySkill,
  rateText,
  sharedSkillsText,
  type PickableJob,
} from "@/lib/similar-candidates-view";

/**
 * Zakładka „Podobni” (22.10.2026): podobny ≠ pasujący. Brak krytycznej to
 * ostrzeżenie — osoba domyślnie odznaczona, a zaznaczona czeka na zdanie.
 */

const check = (id: number, over: Partial<CandidateCheck> = {}): CandidateCheck => ({
  candidate_id: id,
  critical: [{ label: "Active Directory", status: "met", sources: ["cv"] }],
  missing: [],
  in_job: null,
  ...over,
});

const missingM365 = (id: number) =>
  check(id, {
    critical: [
      { label: "Active Directory", status: "met", sources: ["cv"] },
      { label: "Microsoft 365", status: "missing", sources: [] },
    ],
    missing: ["Microsoft 365"],
  });

describe("wynik sprawdzenia pod rekrutację", () => {
  it("nazywa brak, spełnienie, kartę w rekrutacji i rekrutację bez krytycznych", () => {
    expect(verdictText(checkVerdict(missingM365(1))!)).toBe("Brak krytycznej: Microsoft 365");
    expect(
      verdictText(
        checkVerdict(
          check(1, {
            missing: ["A", "B"],
            critical: [
              { label: "A", status: "missing", sources: [] },
              { label: "B", status: "missing", sources: [] },
            ],
          }),
        )!,
      ),
    ).toBe("Brak 2 krytycznych: A, B");
    expect(verdictText(checkVerdict(check(1))!)).toBe("Spełnia krytyczne 1/1");
    expect(
      verdictText(checkVerdict(check(1, { in_job: { label: "Screening", column: "screening", closed: false } }))!),
    ).toBe("Już w tej rekrutacji");
    expect(verdictText(checkVerdict(check(1, { critical: [] }))!)).toBe("Rekrutacja bez krytycznych");
    expect(checkVerdict(undefined)).toBeNull();
  });

  it("krytyczna, której nie da się sprawdzić słowem, nie jest brakiem", () => {
    const verdict = checkVerdict(
      check(1, { critical: [{ label: "bankowość", status: "unknown", sources: [] }] }),
    );
    expect(verdict).toEqual({ kind: "met", met: 0, total: 0 });
    expect(verdictText(verdict!)).toBe("Krytyczne do sprawdzenia w rozmowie");
  });
});

describe("zaznaczenie i dodanie", () => {
  const checks = checksByCandidate({
    job_id: 5,
    critical_labels: ["Active Directory", "Microsoft 365"],
    candidates: [
      check(1),
      missingM365(2),
      check(3, { in_job: { label: "Screening", column: "screening", closed: false } }),
    ],
  });

  it("domyślnie zaznacza tylko spełniających krytyczne i spoza rekrutacji", () => {
    expect([...defaultSelected([1, 2, 3, 4], checks)]).toEqual([1]);
  });

  it("brak krytycznej czeka na zdanie; osoba już w rekrutacji nie idzie do serwera", () => {
    const waiting = addPlan(new Set([1, 2, 3]), checks, { 2: "   " });
    expect(waiting.ids).toEqual([1, 2]);
    expect(waiting.waitingForReason).toEqual([2]);
    expect(waiting.reasons).toEqual({});

    const ready = addPlan(new Set([1, 2]), checks, { 2: " dopytam o M365 " });
    expect(ready.waitingForReason).toEqual([]);
    expect(ready.reasons).toEqual({ 2: "dopytam o M365" });
  });
});

describe("rekrutacje do wyboru", () => {
  const job = (id: number, group: PickableJob["group"]): PickableJob => ({
    id,
    names: { id, title: `R${id}`, working_title: null, client_reference: null },
    clientName: null,
    group,
  });

  it("rekrutacje osoby z profilu na górze, moje bez powtórzeń", () => {
    const merged = mergePickableJobs([job(1, "source"), job(2, "source")], [job(2, "mine"), job(3, "mine")]);
    expect(merged.map((j) => [j.id, j.group])).toEqual([
      [1, "source"],
      [2, "source"],
      [3, "mine"],
    ]);
  });
});

describe("teksty wiersza", () => {
  it("odmienia „wspólne umiejętności”", () => {
    expect(sharedSkillsText(1)).toBe("1 wspólna umiejętność");
    expect(sharedSkillsText(3)).toBe("3 wspólne umiejętności");
    expect(sharedSkillsText(5)).toBe("5 wspólnych umiejętności");
    expect(sharedSkillsText(12)).toBe("12 wspólnych umiejętności");
    expect(sharedSkillsText(22)).toBe("22 wspólne umiejętności");
    expect(sharedSkillsText(0)).toBe("0 wspólnych umiejętności");
  });

  it("nazwa umiejętności ze słownika, a bez wpisu z wielką literą", () => {
    const dictionary = new Map([["active directory", "Active Directory"]]);
    expect(prettySkill("active directory", dictionary)).toBe("Active Directory");
    expect(prettySkill("veeam", dictionary)).toBe("Veeam");
  });

  it("stawka i imię bez pustych napisów", () => {
    expect(rateText(70, "PLN")).toBe("70 zł/h");
    expect(rateText(null, null)).toBe("—");
    expect(rateText(20, "EUR")).toBe("20 EUR/h");
    expect(personName({ id: 7, name: null, lastname: null })).toBe("Osoba #7");
  });
});
