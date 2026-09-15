import { describe, expect, it } from "vitest";
import { splitTemplateVariables } from "@/lib/template-variables";

const labels = new Map([
  ["{{candidate_name}}", "Imię i nazwisko kandydata"],
  ["{{job_title}}", "Tytuł stanowiska"],
]);

describe("splitTemplateVariables (UAT B14)", () => {
  it("labels known variables and keeps surrounding text", () => {
    expect(splitTemplateVariables("Cześć {{candidate_name}}, rola: {{ job_title }}.", labels)).toEqual([
      { kind: "text", value: "Cześć " },
      { kind: "variable", token: "{{candidate_name}}", label: "Imię i nazwisko kandydata" },
      { kind: "text", value: ", rola: " },
      { kind: "variable", token: "{{job_title}}", label: "Tytuł stanowiska" },
      { kind: "text", value: "." },
    ]);
  });

  it("marks unknown variables instead of hiding them", () => {
    expect(splitTemplateVariables("{{foo}}", labels)).toEqual([
      { kind: "variable", token: "{{foo}}", label: null },
    ]);
  });

  it("handles empty text", () => {
    expect(splitTemplateVariables(null, labels)).toEqual([]);
  });
});
