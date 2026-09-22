import { describe, expect, it } from "vitest";
import {
  AVAILABILITY_CHOICES,
  availabilityChoiceFor,
} from "@/lib/candidate-availability-choice";

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
