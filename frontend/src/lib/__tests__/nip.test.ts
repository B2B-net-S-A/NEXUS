import { describe, expect, it } from "vitest";

import { nipProblem, normalizedNip } from "@/lib/nip";

describe("nipProblem", () => {
  it.each(["1111111111", "111-111-11-11", "PL 1111111111", "FI12345678", "FR1A123456789", ""])(
    "accepts %s",
    (value) => {
      expect(nipProblem(value)).toBeNull();
    },
  );

  it("refuses a bad checksum with a Polish reason", () => {
    expect(nipProblem("1111111112")).toBe("Ten NIP ma niepoprawną sumę kontrolną.");
  });

  it("refuses a short number", () => {
    expect(nipProblem("123456")).toBe("NIP ma 10 cyfr.");
  });

  it("refuses a truncated VAT number and free text", () => {
    expect(nipProblem("FR1")).toMatch(/VAT UE/);
    expect(nipProblem("nie wiem")).toMatch(/VAT UE/);
  });
});

describe("normalizedNip", () => {
  it("drops separators and the PL prefix", () => {
    expect(normalizedNip("PL 111-111-11-11")).toBe("1111111111");
  });

  it("keeps a foreign prefix", () => {
    expect(normalizedNip("fi 12345678")).toBe("FI12345678");
  });
});
