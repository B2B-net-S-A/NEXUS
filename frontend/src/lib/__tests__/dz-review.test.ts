import { describe, expect, it } from "vitest";

import { groupCproByJob, type BoardTaskRow } from "@/lib/api/boardTasks";
import { highlightTerms, requirementAlternatives } from "@/lib/dz-review";

const marked = (text: string, terms: string[]) =>
  highlightTerms(text, terms)
    .filter((p) => p.match)
    .map((p) => p.text);

describe("highlightTerms — must-have w tekście CV", () => {
  it("całe słowa: Java nie świeci w JavaScript", () => {
    expect(marked("Java i JavaScript, java", ["Java"])).toEqual(["Java", "java"]);
  });

  it("C++ świeci także w C++17, .NET w ASP.NET", () => {
    expect(marked("C++17 oraz ASP.NET", ["C++", ".NET"])).toEqual(["C++", ".NET"]);
  });

  it("alternatywy „X lub Y” i frazy przez myślnik", () => {
    expect(requirementAlternatives("Java lub Kotlin")).toEqual(["Java", "Kotlin"]);
    expect(marked("Kotlin, Spring-Boot", ["Java lub Kotlin", "Spring Boot"])).toEqual(["Kotlin", "Spring-Boot"]);
  });

  it("zachowuje cały tekst", () => {
    const parts = highlightTerms("Łódź: Java, Kubernetes", ["Java", "Kubernetes"]);
    expect(parts.map((p) => p.text).join("")).toBe("Łódź: Java, Kubernetes");
  });
});

describe("groupCproByJob — jedna osoba na rekrutację", () => {
  const row = (over: Partial<BoardTaskRow>): BoardTaskRow => ({
    kind: "cpro_to_send",
    stage_id: 1,
    candidate_id: 1,
    candidate_name: "A",
    job_id: 10,
    job_title: "Java",
    client_id: 5,
    client_name: "Nordea",
    since: "2026-09-20T10:00:00Z",
    process_state_version: 0,
    target_stage_def_id: null,
    assignee_id: null,
    assignee_name: null,
    ...over,
  });

  it("zachowuje kolejność pierwszego wystąpienia i zbiera kandydatów", () => {
    const groups = groupCproByJob([
      row({ stage_id: 1, job_id: 10 }),
      row({ stage_id: 2, job_id: 20, job_title: "QA", assignee_id: 7, assignee_name: "Ola", job_sender_id: 7, job_sender_name: "Ola" }),
      row({ stage_id: 3, job_id: 10 }),
    ]);
    expect(groups.map((g) => [g.job_id, g.rows.map((r) => r.stage_id)])).toEqual([
      [10, [1, 3]],
      [20, [2]],
    ]);
    expect(groups[1].assignee_name).toBe("Ola");
  });

  it("typowanie jednego kandydata nie udaje osoby dla całej rekrutacji", () => {
    const [group] = groupCproByJob([
      row({ stage_id: 1, assignee_id: 7, assignee_name: "Ola" }),
      row({ stage_id: 2, assignee_id: 8, assignee_name: "Piotr" }),
      row({ stage_id: 3, assignee_id: 7, assignee_name: "Ola" }),
    ]);
    expect(group.assignee_id).toBeNull();
    expect(group.legacy_assignees).toEqual(["Ola", "Piotr"]);
  });
});
