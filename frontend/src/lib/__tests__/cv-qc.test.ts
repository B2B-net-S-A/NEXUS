import { describe, expect, it } from "vitest";

import { groupCproByJob, type BoardTaskRow } from "@/lib/api/boardTasks";
import type { QcCheck, QcCvBlock } from "@/lib/api/cvQc";
import {
  apiErrorCode,
  candidateQuestion,
  checkLevelFixes,
  highlightTerms,
  parseBoldMarkup,
  qcFailedStageId,
  requirementAlternatives,
  roleGaps,
  segmentCv,
  unboldedTerms,
} from "@/lib/cv-qc";

const marked = (text: string, terms: string[]) =>
  highlightTerms(text, terms)
    .filter((p) => p.match)
    .map((p) => p.text);

describe("highlightTerms — terminy w tekście CV", () => {
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

describe("parseBoldMarkup — propozycje AI", () => {
  it("`**x**` to pogrubienie, reszta zwykły tekst — bez HTML", () => {
    expect(parseBoldMarkup("W **Java 11** i <b>**Spring Boot**</b>.")).toEqual([
      { t: "W ", b: false },
      { t: "Java 11", b: true },
      { t: " i <b>", b: false },
      { t: "Spring Boot", b: true },
      { t: "</b>.", b: false },
    ]);
  });

  it("niedomknięte gwiazdki zostają tekstem", () => {
    expect(parseBoldMarkup("a **b")).toEqual([{ t: "a **b", b: false }]);
  });
});

const check = (over: Partial<QcCheck>): QcCheck => ({
  key: "must_in_cv",
  label: "x",
  severity: "blocking",
  status: "pass",
  summary: null,
  items: [],
  ...over,
});

describe("braki z wyniku QC", () => {
  const checks = [
    check({ key: "must_bolded", status: "fail", items: [{ term: "Kafka", fix: "bold_all" }, { requirement: "GraphQL", fix: "bold_all" }] }),
    check({ key: "nice_bolded", status: "pass", items: [{ term: "Docker" }] }),
    check({
      key: "must_in_roles",
      status: "fail",
      items: [
        { requirement: "Java", role: "ING Tech — Java Developer · 2019–2022", fix: "ai" },
        { requirement: "Spring Boot", role: "ING Tech — Java Developer · 2019–2022", fix: "ai" },
        { requirement: "Kafka", role: "Allegro — Senior Java Dev", fix: "ai" },
      ],
    }),
  ];

  it("żółte = niepogrubione z nieprzechodzących sprawdzeń pogrubienia", () => {
    expect(unboldedTerms(checks)).toEqual(["Kafka", "GraphQL"]);
  });

  it("naprawa całego sprawdzenia pojawia się raz", () => {
    expect(checkLevelFixes(checks[0])).toEqual(["bold_all"]);
    expect(checkLevelFixes(checks[2])).toEqual(["ai"]);
  });

  it("czerwona krawędź trafia w stanowisko po pracodawcy i roli (lata w innym formacie)", () => {
    const blocks: QcCvBlock[] = [
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Allegro — Senior Java Developer", b: true }] },
      { kind: "li", section: null, runs: [{ t: "Integracje asynchroniczne.", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Java Developer", b: true }, { t: " 06.2019 – 02.2022", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "ING Tech", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Moduł przelewów SEPA.", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Asseco — Junior", b: true }] },
    ];
    const segments = segmentCv(blocks, roleGaps(checks));
    expect(segments.map((s) => [s.blocks.length, s.gap?.requirements ?? null])).toEqual([
      [1, null],
      [2, ["Kafka"]],
      [3, ["Java", "Spring Boot"]],
      [1, null],
    ]);
  });

  it("`role_index` z serwera wygrywa z etykietą roli z oryginału", () => {
    const blocks: QcCvBlock[] = [
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Lead Developer", b: true }] },
      { kind: "p", section: "role", runs: [{ t: "Programista", b: true }] },
    ];
    const gaps = roleGaps([
      check({
        key: "must_in_roles",
        status: "fail",
        items: [{ requirement: "Kafka", role: "Acme — Software Engineer", role_index: 1, fix: "ai" }],
      }),
    ]);
    expect(segmentCv(blocks, gaps).map((s) => s.gap?.requirements ?? null)).toEqual([null, null, ["Kafka"]]);
  });

  it("pytanie do kandydata z terminem i rolą", () => {
    expect(candidateQuestion({ term: "Docker", role: "Allegro" })).toBe("Czy używał(a) Docker w Allegro?");
    expect(candidateQuestion({ requirement: "Docker" })).toBe("Czy używał(a) Docker? W którym projekcie?");
  });
});

describe("kody błędów", () => {
  it("czyta `detail.code` i `code` w ciele", () => {
    expect(apiErrorCode({ response: { data: { detail: { code: "CV_NOT_EDITABLE" } } } })).toBe("CV_NOT_EDITABLE");
    expect(apiErrorCode({ response: { data: { code: "CV_NOT_EDITABLE" } } })).toBe("CV_NOT_EDITABLE");
    expect(apiErrorCode(new Error("x"))).toBeNull();
  });

  it("odmowa ruchu CV_QC_FAILED wskazuje etap do otwarcia", () => {
    expect(qcFailedStageId({ response: { status: 409, data: { detail: { code: "CV_QC_FAILED", stage_id: 7 } } } })).toBe(7);
    expect(qcFailedStageId({ response: { status: 409, data: { detail: { code: "CV_QC_FAILED" } } } })).toBeNull();
    expect(qcFailedStageId({ response: { status: 409, data: { detail: { code: "OTHER" } } } })).toBeUndefined();
  });
});

describe("groupCproByJob — jedna linia na rekrutację", () => {
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
      row({ stage_id: 2, job_id: 20, job_title: "QA" }),
      row({ stage_id: 3, job_id: 10 }),
    ]);
    expect(groups.map((g) => [g.job_id, g.rows.map((r) => r.stage_id)])).toEqual([
      [10, [1, 3]],
      [20, [2]],
    ]);
  });
});
