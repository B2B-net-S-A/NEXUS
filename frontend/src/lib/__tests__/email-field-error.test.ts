import { describe, expect, it } from "vitest";

import { emailFieldError } from "@/lib/email-field-error";

describe("emailFieldError", () => {
  it("zajęty adres (409 z serwera) trafia do pola e-mail", () => {
    expect(
      emailFieldError({
        response: { status: 409, data: { detail: "Kandydat z tym adresem e-mail już istnieje." } },
      }),
    ).toBe("Kandydat z tym adresem e-mail już istnieje.");
  });

  it("inne 409 (np. duplikat z listą trafień) nie dotyczą pola e-mail", () => {
    expect(
      emailFieldError({
        response: { status: 409, data: { detail: { detail: "duplikat", matches: [] } } },
      }),
    ).toBeNull();
    expect(
      emailFieldError({ response: { status: 409, data: { detail: "Coś innego." } } }),
    ).toBeNull();
  });

  it("422 przy polu email nadal daje polskie zdanie", () => {
    expect(
      emailFieldError({
        response: {
          status: 422,
          data: { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address" }] },
        },
      }),
    ).toMatch(/Nieprawidłowy adres e-mail/);
  });
});
