import { describe, it, expect } from "vitest";
import { highlightTerms } from "@/components/v2/MatchSnippet";

describe("highlightTerms", () => {
  it("splits plain text into one non-match part when no term matches", () => {
    expect(highlightTerms("Just plain text", ["Python"])).toEqual([
      { text: "Just plain text", match: false },
    ]);
  });

  it("returns single non-match when text is empty", () => {
    expect(highlightTerms("", ["Python"])).toEqual([]);
  });

  it("returns single non-match when no terms are passed", () => {
    expect(highlightTerms("Some text", [])).toEqual([
      { text: "Some text", match: false },
    ]);
  });

  it("highlights one occurrence (case-insensitive, preserves case)", () => {
    expect(highlightTerms("Senior PYTHON Developer", ["python"])).toEqual([
      { text: "Senior ", match: false },
      { text: "PYTHON", match: true },
      { text: " Developer", match: false },
    ]);
  });

  it("highlights multiple occurrences of the same term", () => {
    expect(highlightTerms("python and Python and python", ["python"])).toEqual([
      { text: "python", match: true },
      { text: " and ", match: false },
      { text: "Python", match: true },
      { text: " and ", match: false },
      { text: "python", match: true },
    ]);
  });

  it("prefers longer terms over shorter overlapping ones", () => {
    // "AI Engineer" should match as one chunk, not "AI" + "Engineer"
    expect(
      highlightTerms("Senior AI Engineer", ["AI", "AI Engineer"]),
    ).toEqual([
      { text: "Senior ", match: false },
      { text: "AI Engineer", match: true },
    ]);
  });

  it("highlights different terms in sequence", () => {
    expect(
      highlightTerms("Python and Django stack", ["Python", "Django"]),
    ).toEqual([
      { text: "Python", match: true },
      { text: " and ", match: false },
      { text: "Django", match: true },
      { text: " stack", match: false },
    ]);
  });

  it("drops terms shorter than 2 chars", () => {
    expect(highlightTerms("abc def", ["a", "def"])).toEqual([
      { text: "abc ", match: false },
      { text: "def", match: true },
    ]);
  });

  it("trims whitespace from terms before matching", () => {
    expect(highlightTerms("Senior Python Dev", ["  Python  "])).toEqual([
      { text: "Senior ", match: false },
      { text: "Python", match: true },
      { text: " Dev", match: false },
    ]);
  });

  it("handles adjacent matches without empty plain part", () => {
    // Adjacent term occurrences must NOT emit an empty "" plain part
    // between them (would render as <></> noise).
    expect(highlightTerms("PyJS", ["Py", "JS"])).toEqual([
      { text: "Py", match: true },
      { text: "JS", match: true },
    ]);
  });
});
