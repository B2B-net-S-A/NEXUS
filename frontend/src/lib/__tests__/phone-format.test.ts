import { describe, expect, it } from "vitest";

import { formatPhone } from "@/lib/phone-format";

describe("formatPhone", () => {
  it("groups a bare nine-digit number in threes", () => {
    expect(formatPhone("531898451")).toBe("531 898 451");
  });

  it("keeps the +48 prefix and groups the rest", () => {
    expect(formatPhone("+48531898451")).toBe("+48 531 898 451");
    expect(formatPhone("0048531898451")).toBe("+48 531 898 451");
  });

  it("normalises numbers already written with other separators", () => {
    expect(formatPhone(" 531-898-451 ")).toBe("531 898 451");
    expect(formatPhone("+48 53 189 84 51")).toBe("+48 531 898 451");
    expect(formatPhone("(+48) 531.898.451")).toBe("+48 531 898 451");
  });

  it("leaves numbers it cannot read for sure untouched", () => {
    expect(formatPhone("+380671234567")).toBe("+380671234567");
    expect(formatPhone("+49 30 1234567")).toBe("+49 30 1234567");
    expect(formatPhone("22 123 45 67 wew. 12")).toBe("22 123 45 67 wew. 12");
    expect(formatPhone("531898451, 600100200")).toBe("531898451, 600100200");
    expect(formatPhone("48531898451")).toBe("48531898451");
    expect(formatPhone("12345")).toBe("12345");
  });

  it("returns an empty string for blank input", () => {
    expect(formatPhone("   ")).toBe("");
  });
});
