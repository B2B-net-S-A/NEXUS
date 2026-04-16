import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

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
