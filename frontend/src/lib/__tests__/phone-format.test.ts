import { describe, expect, it } from "vitest";

import { dialablePhone, formatPhone } from "@/lib/phone-format";

describe("formatPhone", () => {
  it("groups a bare nine-digit number in threes", () => {
    expect(formatPhone("600100200")).toBe("600 100 200");
  });

  it("keeps the +48 prefix and groups the rest", () => {
    expect(formatPhone("+48600100200")).toBe("+48 600 100 200");
    expect(formatPhone("0048600100200")).toBe("+48 600 100 200");
  });

  it("reads eleven digits starting with 48 as a Polish number without the plus", () => {
    // 83% numerów na listach dzwonienia jest zapisanych jako „48XXXXXXXXX” (27.11.2026).
    expect(formatPhone("48514641516")).toBe("+48 514 641 516");
    expect(formatPhone("48 514 641 516")).toBe("+48 514 641 516");
  });

  it("normalises numbers already written with other separators", () => {
    expect(formatPhone(" 600-100-200 ")).toBe("600 100 200");
    expect(formatPhone("+48 60 010 02 00")).toBe("+48 600 100 200");
    expect(formatPhone("(+48) 600.100.200")).toBe("+48 600 100 200");
  });

  it("leaves numbers it cannot read for sure untouched", () => {
    expect(formatPhone("+380671234567")).toBe("+380671234567");
    expect(formatPhone("+49 30 1234567")).toBe("+49 30 1234567");
    expect(formatPhone("22 123 45 67 wew. 12")).toBe("22 123 45 67 wew. 12");
    expect(formatPhone("600100200, 601200300")).toBe("600100200, 601200300");
    expect(formatPhone("12345")).toBe("12345");
  });

  it("returns an empty string for blank input", () => {
    expect(formatPhone("   ")).toBe("");
  });
});

describe("dialablePhone", () => {
  it("gives a Polish number with the +48 prefix so the phone dials it", () => {
    expect(dialablePhone("48514641516")).toBe("+48514641516");
    expect(dialablePhone("514 641 516")).toBe("+48514641516");
    expect(dialablePhone("0048 514 641 516")).toBe("+48514641516");
    expect(dialablePhone("+48 514-641-516")).toBe("+48514641516");
  });

  it("leaves numbers it cannot read for sure as they were saved", () => {
    expect(dialablePhone("+49 30 1234567")).toBe("+49 30 1234567");
    expect(dialablePhone("22 123 45 67 wew. 12")).toBe("22 123 45 67 wew. 12");
    expect(dialablePhone(" 12345 ")).toBe("12345");
  });
});
