import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";

import { ASSIGN_BLOCKED_LABELS, assignErrorMessage } from "@/lib/assign-error";

function axios409(detail: string): AxiosError {
  const headers = new AxiosHeaders();
  const config = { headers };
  return new AxiosError("Request failed with status code 409", "ERR_BAD_REQUEST", config as never, null, {
    status: 409,
    statusText: "Conflict",
    headers,
    config: config as never,
    data: { detail },
  });
}

describe("assignErrorMessage", () => {
  it("maps every eligibility reason code to a Polish sentence", () => {
    for (const [code, label] of Object.entries(ASSIGN_BLOCKED_LABELS)) {
      expect(assignErrorMessage(axios409(code))).toBe(label);
    }
  });

  it("passes through an unknown human-readable detail unchanged", () => {
    expect(assignErrorMessage(axios409("Kandydat nie istnieje"))).toBe(
      "Kandydat nie istnieje",
    );
  });

  it("falls back to the error message for non-axios errors", () => {
    expect(assignErrorMessage(new Error("boom"))).toBe("boom");
  });
});
