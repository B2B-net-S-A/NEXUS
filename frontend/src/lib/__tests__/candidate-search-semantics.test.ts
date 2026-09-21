import { describe, expect, it } from "vitest";

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import {
  looksLikePastedRequest,
  parseSkillBucketInput,
  summarizeTextInterpretation,
  toSearchSemanticsV2,
} from "@/lib/candidate-search-semantics";
import { listQsFromSavedSearch } from "@/lib/candidate-saved-search";

describe("toSearchSemanticsV2 — pola legacy przez adapter zapisów", () => {
  it("skills_must/skills_any → Mile widziane, skills_none → Wyklucz, open_to_* → open_to", () => {
    const out = toSearchSemanticsV2({
      q: "java",
      skills_must: ["Java"],
      skills_any: ["Spring"],
      skills_none: ["PHP|Perl"],
      open_to_sales_support: true,
      open_to_expert_consult: false,
      page: 3,
    } as CandidateSearchRequest);
    expect(out).toMatchObject({
      q: "java",
      page: 3,
      semantics_version: 2,
      skills_must: [],
      skills_any: [],
      skills_none: [],
      skills_required: [],
      skills_preferred: ["Java", "Spring"],
      skills_excluded: ["PHP", "Perl"],
      open_to: ["sales_support"],
      open_to_sales_support: null,
      // jawne „nie" zostaje nietknięte
      open_to_expert_consult: false,
    });
  });

  it("grupy „którakolwiek” z zapisu listy trafiają do „Musi mieć” jako a|b", () => {
    const out = toSearchSemanticsV2({
      skills_required: ["Go"],
      skills_required_any_groups: [["AWS", "GCP"]],
    } as CandidateSearchRequest);
    expect(out.skills_required).toEqual(["Go", "AWS|GCP"]);
    expect(out.skills_required_any_groups).toEqual([]);
  });

  it("jest idempotentne", () => {
    const once = toSearchSemanticsV2({
      skills_must: ["Java"],
      skills_required: ["Kotlin"],
    } as CandidateSearchRequest);
    expect(toSearchSemanticsV2(once)).toEqual(once);
  });
});

describe("parseSkillBucketInput", () => {
  it("domyślnie „Musi mieć”, `|`/OR = grupa, `-` = Wyklucz (grupa spłaszczona)", () => {
    expect(parseSkillBucketInput("Java, Spring | Quarkus, -PHP|Perl")).toEqual([
      { bucket: "required", value: "Java" },
      { bucket: "required", value: "Spring|Quarkus" },
      { bucket: "excluded", value: "PHP" },
      { bucket: "excluded", value: "Perl" },
    ]);
    expect(parseSkillBucketInput("Docker", "preferred")).toEqual([
      { bucket: "preferred", value: "Docker" },
    ]);
    expect(parseSkillBucketInput("  , ")).toEqual([]);
  });
});

describe("looksLikePastedRequest", () => {
  it("≥ 300 znaków albo ≥ 3 nowe linie", () => {
    expect(looksLikePastedRequest("java")).toBe(false);
    expect(looksLikePastedRequest("a".repeat(300))).toBe(true);
    expect(looksLikePastedRequest("a\nb\nc\nd")).toBe(true);
    expect(looksLikePastedRequest("a\nb\nc")).toBe(false);
    expect(looksLikePastedRequest(null)).toBe(false);
  });
});

describe("summarizeTextInterpretation", () => {
  it("osoba / słowa kluczowe / po znaczeniu", () => {
    expect(
      summarizeTextInterpretation("literal", {
        kind: "email",
        mode: "literal",
        rule: "email",
        name: [],
        email: "jan@x.pl",
        phone: null,
        skills: [],
        locations: [],
        other: [],
      }),
    ).toEqual({ label: "osoba", detail: "e-mail jan@x.pl" });
    expect(summarizeTextInterpretation("keywords", null)?.label).toBe("słowa kluczowe");
    expect(summarizeTextInterpretation("semantic", null)?.label).toBe("po znaczeniu");
    expect(summarizeTextInterpretation("none", null)).toBeNull();
  });
});

describe("listQsFromSavedSearch", () => {
  it("zapis przypięty do dawnych zasad otwiera się z sv=1", () => {
    const qs = listQsFromSavedSearch({
      version: 2,
      qs: "skills_q=Java",
      keep_legacy_semantics: true,
    });
    expect(new URLSearchParams(qs).get("sv")).toBe("1");
  });

  it("v3 z hide_unknown dokłada hu=1, zwykły zapis bez zmian", () => {
    expect(
      new URLSearchParams(
        listQsFromSavedSearch({
          version: 3,
          qs: "loc=Gdańsk&sv=2",
          request: { hide_unknown: true },
        }),
      ).get("hu"),
    ).toBe("1");
    expect(listQsFromSavedSearch({ version: 2, qs: "q=java" })).toBe("q=java");
    expect(listQsFromSavedSearch(null)).toBe("");
  });
});
