/**
 * Publiczny formularz aplikacyjny nie może zgubić CV kandydata.
 *
 * `detail` z FastAPI szło wprost do JSX. Dla błędu walidacji `Form(...)` jest
 * to TABLICA obiektów → React #31 → granica błędu zjada całą stronę, a kandydat
 * traci wypełniony formularz RAZEM z załączonym plikiem i nie dowiaduje się,
 * że chodziło o adres e-mail (zod 4 przyjmuje `jan@firma-.pl`, `EmailStr` nie).
 */

import { describe, expect, it } from "vitest";

import { applyFieldErrors } from "@/lib/apply-form-errors";

describe("applyFieldErrors", () => {
  it("zamienia odmowę walidacji na komunikat PRZY POLU", () => {
    const errors = applyFieldErrors({
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address",
          input: "jan@firma-.pl",
        },
      ],
    });
    expect(errors).toHaveLength(1);
    expect(errors[0].field).toBe("email");
    // Komunikat po polsku i actionable — „value is not a valid email address"
    // nic kandydatowi nie mówi.
    expect(errors[0].message).toContain("literówki");
  });

  it("tłumaczy „field required” na nazwę pola", () => {
    const errors = applyFieldErrors({
      detail: [{ loc: ["body", "last_name"], msg: "Field required" }],
    });
    expect(errors[0].message).toBe("Nazwisko jest wymagane.");
  });

  it("pomija odmowy spoza ciała żądania — nie ma przy czym ich postawić", () => {
    // `query`/`path`/`header` ustawia kod aplikacji, nie kandydat.
    expect(
      applyFieldErrors({ detail: [{ loc: ["query", "token"], msg: "bad" }] }),
    ).toEqual([]);
  });

  it("pomija pola, których formularz nie ma", () => {
    expect(
      applyFieldErrors({ detail: [{ loc: ["body", "secret"], msg: "bad" }] }),
    ).toEqual([]);
  });

  it("string detail i pusta odpowiedź nie wywracają niczego", () => {
    expect(applyFieldErrors({ detail: "Nie znaleziono linku" })).toEqual([]);
    expect(applyFieldErrors({})).toEqual([]);
    expect(applyFieldErrors(null)).toEqual([]);
    expect(applyFieldErrors("")).toEqual([]);
  });
});
