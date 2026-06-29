import { describe, it, expect } from "vitest";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

describe("cn (tailwind class merger)", () => {
  it("joins multiple class strings", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("handles conditional classes (falsy values dropped)", () => {
    expect(cn("a", false && "b", "c")).toBe("a c");
  });

  it("merges conflicting tailwind utilities keeping last", () => {
    // tailwind-merge dedupes conflicting classes by keeping the last one
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("handles arrays and objects via clsx", () => {
    expect(cn(["a", "b"])).toBe("a b");
    expect(cn({ a: true, b: false, c: true })).toBe("a c");
  });

  it("preserves non-conflicting tailwind classes", () => {
    expect(cn("text-sm", "font-bold")).toBe("text-sm font-bold");
  });
});

describe("sanitizeDecimalInput (rate field onChange)", () => {
  it("keeps a Polish comma decimal (the reported case 215,60)", () => {
    expect(sanitizeDecimalInput("215,60")).toBe("215,60");
  });

  it("keeps a period decimal", () => {
    expect(sanitizeDecimalInput("215.60")).toBe("215.60");
  });

  it("strips letters and stray symbols", () => {
    expect(sanitizeDecimalInput("2a1b5,6zł0")).toBe("215,60");
  });

  it("collapses extra separators to the first one", () => {
    expect(sanitizeDecimalInput("215,6,0")).toBe("215,60");
    expect(sanitizeDecimalInput("1.2.3")).toBe("1.23");
  });

  it("allows a trailing separator while typing", () => {
    expect(sanitizeDecimalInput("215,")).toBe("215,");
  });

  it("returns empty string for non-numeric input", () => {
    expect(sanitizeDecimalInput("abc")).toBe("");
  });
});

describe("parseDecimalInput (rate field submit)", () => {
  it("parses a Polish comma decimal to a number (215,60 → 215.6)", () => {
    expect(parseDecimalInput("215,60")).toBe(215.6);
  });

  it("parses a period decimal", () => {
    expect(parseDecimalInput("215.60")).toBe(215.6);
  });

  it("parses an integer", () => {
    expect(parseDecimalInput("25000")).toBe(25000);
  });

  it("trims surrounding whitespace", () => {
    expect(parseDecimalInput("  215,60  ")).toBe(215.6);
  });

  it("returns null for empty input", () => {
    expect(parseDecimalInput("")).toBeNull();
    expect(parseDecimalInput("   ")).toBeNull();
  });

  it("returns null for a lone separator", () => {
    expect(parseDecimalInput(",")).toBeNull();
    expect(parseDecimalInput(".")).toBeNull();
  });
});
