import { describe, expect, it } from "vitest";

import { formatNip, nipFromQuery, nipProblem, normalizedNip } from "@/lib/nip";

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

describe("nipFromQuery", () => {
  it("rozpoznaje sam NIP w zapisie z kreskami i prefiksem", () => {
    expect(nipFromQuery("111-111-11-11")).toEqual({ nip: "1111111111", valid: true });
    expect(nipFromQuery("PL 1111111111")).toEqual({ nip: "1111111111", valid: true });
  });

  it("oznacza złą sumę kontrolną", () => {
    expect(nipFromQuery("1111111112")).toEqual({ nip: "1111111112", valid: false });
  });

  it("pomija tekst, krótkie numery i VAT UE", () => {
    expect(nipFromQuery("firma 1111111111")).toBeNull();
    expect(nipFromQuery("11111")).toBeNull();
    expect(nipFromQuery("FR1A123456789")).toBeNull();
  });
});

describe("formatNip", () => {
  it("grupuje cyfry jak na fakturze", () => {
    expect(formatNip("1111111111")).toBe("111-111-11-11");
  });
});
