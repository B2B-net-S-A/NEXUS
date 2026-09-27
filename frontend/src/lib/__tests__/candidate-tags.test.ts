import { describe, expect, it } from "vitest";
import { editableTagText, structuredTagLabels } from "@/lib/candidate-tags";

const source = { type: "traffit_source", value: "LinkedIn" };

describe("candidate tags in the edit form (UAT B60)", () => {
  it("shows only text tags, never object serialisation", () => {
    expect(editableTagText(["Java", source, " Remote "])).toBe("Java, Remote");
    expect(editableTagText([source, source])).toBe("");
    expect(editableTagText(null)).toBe("");
    expect(editableTagText("legacy, string")).toBe("legacy, string");
  });

  it("names imported tags for the read-only hint", () => {
    expect(structuredTagLabels(["Java", source])).toEqual(["LinkedIn"]);
  });
});
