import { describe, expect, it } from "vitest";

import type { GlossaryTerm } from "@/lib/api/plainKnowledge";
import {
  buildGlossaryLookup,
  glossaryKey,
  readyGlossaryCount,
} from "@/lib/plain-glossary-lookup";

function term(display_name: string, patch: Partial<GlossaryTerm> = {}): GlossaryTerm {
  return {
    term_key: display_name.toLowerCase(),
    display_name,
    level: "must",
    level_label: "wymagane",
    status: "ready",
    summary: `${display_name} po ludzku`,
    does: null,
    cv_hints: [],
    confused_with: null,
    in_this_project: null,
    sources: [],
    origin: null,
    ...patch,
  };
}

describe("buildGlossaryLookup", () => {
  it("łączy po nazwie bez wielkości liter i spacji na brzegach", () => {
    const map = buildGlossaryLookup([term("Spring Boot")]);
    expect(map.get(glossaryKey("  spring boot "))?.display_name).toBe("Spring Boot");
  });

  it("pomija hasła bez opisu, w researchu i nieudane", () => {
    const map = buildGlossaryLookup([
      term("Kafka", { status: "researching", summary: null }),
      term("Jira", { status: "failed" }),
      term("Git", { summary: "  " }),
      term("React"),
    ]);
    expect([...map.keys()]).toEqual(["react"]);
  });

  it("pierwsze hasło wygrywa przy powtórzonej nazwie", () => {
    const map = buildGlossaryLookup([
      term("Java", { summary: "pierwsze" }),
      term("JAVA", { summary: "drugie" }),
    ]);
    expect(map.get("java")?.summary).toBe("pierwsze");
  });

  it("brak listy = pusta mapa i licznik zero", () => {
    expect(buildGlossaryLookup(null).size).toBe(0);
    expect(readyGlossaryCount(undefined)).toBe(0);
  });

  it("licznik liczy tylko hasła z opisem", () => {
    expect(
      readyGlossaryCount([term("A"), term("B", { status: "researching", summary: null })]),
    ).toBe(1);
  });
});
