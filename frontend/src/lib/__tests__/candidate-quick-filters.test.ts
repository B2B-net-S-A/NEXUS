import { describe, expect, it } from "vitest";
import {
  AVAILABILITY_CHOICES,
  QUICK_FILTERS,
  availabilityChoiceFor,
  toggleQuickFilter,
} from "@/lib/candidate-quick-filters";
import type { CandidateFilters } from "@/lib/url-filters";

const TODAY = new Date(2026, 8, 22); // 22.09.2026
type Fields = Pick<
  CandidateFilters,
  "availability" | "employment" | "pipelineStage" | "sentToClientFrom" | "sentToClientTo"
>;
const base: Fields = {
  availability: [],
  employment: [],
  pipelineStage: [],
  sentToClientFrom: "",
  sentToClientTo: "",
};
const quick = (id: string) => QUICK_FILTERS.find((q) => q.id === id)!;

describe("availabilityChoiceFor", () => {
  it("każda odpowiedź rozpoznaje własne ustawienie", () => {
    for (const choice of AVAILABILITY_CHOICES) {
      expect(availabilityChoiceFor(choice.patch)).toBe(choice.id);
    }
  });

  it("kolejność wartości nie ma znaczenia", () => {
    expect(
      availabilityChoiceFor({
        availability: ["open_to_offers", "actively_looking"],
        employment: ["available"],
      }),
    ).toBe("open");
  });

  it("połączenie spoza pytania to null, nie zgadnięta odpowiedź", () => {
    // „Szuka pracy” bez warunku zatrudnienia zostawia konsultantów u klienta.
    expect(availabilityChoiceFor({ availability: ["actively_looking"], employment: [] })).toBeNull();
  });
});

describe("gotowe skróty", () => {
  it("„Do zaproponowania teraz” ustawia pytanie o dostępność i zdejmuje je drugim klikiem", () => {
    const on = toggleQuickFilter(quick("ready"), base, TODAY);
    expect(on).toEqual({
      availability: ["actively_looking", "open_to_offers"],
      employment: ["available"],
    });
    const off = toggleQuickFilter(quick("ready"), { ...base, ...on } as Fields, TODAY);
    expect(off).toEqual({ availability: [], employment: [] });
  });

  it("„Wysłani do klienta — 3 mies.” liczy okno od dzisiaj", () => {
    const on = toggleQuickFilter(quick("sent_recently"), base, TODAY);
    expect(on).toEqual({ sentToClientFrom: "2026-06-24", sentToClientTo: "" });
    expect(quick("sent_recently").isActive({ ...base, ...on } as Fields, TODAY)).toBe(true);
    // Własny zakres dat nie udaje skrótu.
    expect(
      quick("sent_recently").isActive({ ...base, sentToClientFrom: "2026-01-01" }, TODAY),
    ).toBe(false);
  });

  it("„Zatrudnialiśmy ich” to etap „Zatrudniony”", () => {
    expect(toggleQuickFilter(quick("hired_before"), base, TODAY)).toEqual({
      pipelineStage: ["hired"],
    });
    expect(
      toggleQuickFilter(quick("hired_before"), { ...base, pipelineStage: ["hired"] }, TODAY),
    ).toEqual({ pipelineStage: [] });
  });
});
