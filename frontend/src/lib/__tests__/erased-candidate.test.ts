import { describe, expect, it } from "vitest";

import { erasedCandidateMessage } from "../erased-candidate";

const conflict = (detail: unknown, status = 409) => ({ response: { status, data: { detail } } });

describe("erasedCandidateMessage", () => {
  it("oddaje zdanie serwera przy odmowie candidate_erased", () => {
    expect(
      erasedCandidateMessage(conflict({ code: "candidate_erased", message: "Zdanie serwera" })),
    ).toBe("Zdanie serwera");
  });

  it("ma własne zdanie, gdy serwer go nie podał", () => {
    expect(erasedCandidateMessage(conflict({ code: "candidate_erased" }))).toContain(
      "trwale usunięto",
    );
  });

  it.each([
    ["duplikat ze zdaniem", conflict("Kandydat z tym adresem e-mail już istnieje.")],
    ["duplikat z listą", conflict({ existing_candidate_id: 1, matches: [] })],
    ["inny status", conflict({ code: "candidate_erased" }, 403)],
    ["brak odpowiedzi", new Error("network")],
    ["null", null],
  ])("nie rusza innych błędów: %s", (_name, error) => {
    expect(erasedCandidateMessage(error)).toBeNull();
  });
});
