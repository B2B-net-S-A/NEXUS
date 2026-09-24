import { describe, expect, it } from "vitest";

import {
  callFactItems,
  callFactsDraft,
  callFactsPatch,
  callFactsVerifiedLabel,
  rateFactLabel,
} from "@/lib/candidate-call-facts";

describe("fakty z rozmowy praktykanta", () => {
  it("datuje weryfikację w kalendarzu firmy, z zerem wiodącym", () => {
    // 22:30 UTC to już następny dzień w Warszawie.
    expect(
      callFactsVerifiedLabel({
        call_facts_verified_at: "2026-09-03T22:30:00Z",
        call_facts_verified_by_name: "Kasia Wróbel",
      }),
    ).toBe("Zweryfikowane telefonicznie 04.09.2026 · Kasia Wróbel");
  });

  it("bez osoby weryfikującej zostaje sama data, bez weryfikacji — nic", () => {
    expect(
      callFactsVerifiedLabel({ call_facts_verified_at: "2026-09-23T10:00:00Z" }),
    ).toBe("Zweryfikowane telefonicznie 23.09.2026");
    expect(callFactsVerifiedLabel({})).toBeNull();
    expect(callFactsVerifiedLabel({ call_facts_verified_at: "nie-data" })).toBeNull();
  });

  it("stawka po rozmowie to minimum", () => {
    expect(rateFactLabel({})).toBe("Stawka B2B");
    expect(rateFactLabel({ call_facts_verified_at: "2026-09-23T10:00:00Z" })).toBe(
      "Minimalna stawka B2B netto",
    );
  });

  it("stawka zmieniona PO rozmowie nie jest już minimum (audyt 24.09.2026)", () => {
    const facts = { call_facts_verified_at: "2026-09-23T10:00:00Z" };
    // Zapis w tej samej rozmowie (ta sama transakcja) — nadal minimum.
    expect(rateFactLabel(facts, "2026-09-23T10:00:00.400Z")).toBe(
      "Minimalna stawka B2B netto",
    );
    // Stawka sprzed rozmowy — zachowanie bez zmian.
    expect(rateFactLabel(facts, "2026-07-29T10:00:00Z")).toBe(
      "Minimalna stawka B2B netto",
    );
    // Rekruter wpisał stawkę dzień później.
    expect(rateFactLabel(facts, "2026-09-24T09:00:00Z")).toBe("Stawka B2B");
  });

  it("korekta wysyła tylko zmienione pola, „Nie wiadomo” = null", () => {
    const facts = {
      b2b_willingness: "employment_only" as const,
      work_time_preference: "part_time_only" as const,
      accepts_below_min_rate: true,
      accepts_more_office_days: null,
    };
    const draft = callFactsDraft(facts);
    expect(draft).toEqual({
      b2b_willingness: "employment_only",
      work_time_preference: "part_time_only",
      accepts_below_min_rate: "yes",
      accepts_more_office_days: "",
    });
    expect(callFactsPatch(facts, draft)).toEqual({});
    expect(
      callFactsPatch(facts, {
        ...draft,
        b2b_willingness: "b2b",
        accepts_below_min_rate: "",
        accepts_more_office_days: "no",
      }),
    ).toEqual({
      b2b_willingness: "b2b",
      accepts_below_min_rate: null,
      accepts_more_office_days: false,
    });
  });

  it("tylko etat jest ostrzeżeniem, brak odpowiedzi nie jest faktem", () => {
    expect(callFactItems({})).toEqual([]);
    expect(
      callFactItems({
        b2b_willingness: "employment_only",
        work_time_preference: "part_time_only",
        accepts_below_min_rate: true,
        accepts_more_office_days: false,
      }),
    ).toEqual([
      { key: "b2b", label: "Tylko etat — nie bierzemy pod uwagę", tone: "danger" },
      { key: "work_time", label: "tylko part-time", tone: "neutral" },
      { key: "below_min", label: "poniżej minimum: dzwonić", tone: "neutral" },
      { key: "office", label: "więcej dni w biurze: nie dzwonić", tone: "neutral" },
    ]);
    expect(callFactItems({ b2b_willingness: "would_switch" })).toEqual([
      { key: "b2b", label: "przejdzie na B2B", tone: "neutral" },
    ]);
  });
});
