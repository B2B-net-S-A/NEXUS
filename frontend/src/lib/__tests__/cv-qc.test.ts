import { describe, expect, it } from "vitest";

import { groupCproByJob, type BoardTaskRow } from "@/lib/api/boardTasks";
import type { QcCheck, QcCvBlock } from "@/lib/api/cvQc";
import {
  QC_OVERRIDE_REASONS,
  apiErrorCode,
  blockingTasks,
  candidateQuestion,
  checkLevelFixes,
  checkTasks,
  countForm,
  highlightTerms,
  notePreview,
  parseBoldMarkup,
  qcFailedStageId,
  qcOverrideError,
  requirementAlternatives,
  roleGaps,
  segmentCv,
  splitChecks,
  taskTitle,
  thingsLabel,
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

  it("krawędź roli: krytyczne blokują, pozostałe must-have to uwaga", () => {
    const gaps = roleGaps([
      check({
        key: "must_in_roles",
        severity: "warning",
        status: "fail",
        items: [{ requirement: "Kafka", role: "Acme", role_index: 0, fix: "ai" }],
      }),
      check({
        key: "critical_skills",
        status: "fail",
        items: [
          { requirement: "Java", role: "Acme", role_index: 0, fix: "ai" },
          // Brak w całym CV — pozycja bez roli nie zaznacza żadnego stanowiska.
          { requirement: "Scala", fix: "ask_candidate" },
        ],
      }),
      check({ key: "critical_skills", status: "pass", items: [{ requirement: "Go", role: "Acme", role_index: 1 }] }),
    ]);
    // Krytyczne pierwsze, niezależnie od kolejności sprawdzeń.
    expect(gaps).toEqual([{ role: "Acme", roleIndex: 0, requirements: ["Java", "Kafka"], blocking: ["Java"] }]);
  });

  it("klauzula RODO jest własnym segmentem i kończy ostatnie stanowisko", () => {
    const blocks: QcCvBlock[] = [
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Programista", b: true }] },
      { kind: "li", section: null, runs: [{ t: "Moduł przelewów.", b: false }] },
      { kind: "p", section: "rodo", runs: [{ t: "Wyrażam zgodę na przetwarzanie…", b: false }] },
      { kind: "p", section: null, runs: [{ t: "Stopka dokumentu", b: false }] },
    ];
    const gaps = roleGaps([
      check({ key: "critical_skills", status: "fail", items: [{ requirement: "Java", role: "Acme", role_index: 0, fix: "ai" }] }),
    ]);
    const segments = segmentCv(blocks, gaps);
    expect(segments.map((s) => [s.blocks.map((b) => b.section), s.gap?.requirements ?? null])).toEqual([
      [["experience"], null],
      [["role", null], ["Java"]],
      [["rodo"], null],
      [[null], null],
    ]);
  });

  it("pytanie do kandydata z terminem i rolą", () => {
    expect(candidateQuestion({ term: "Docker", role: "Allegro" })).toBe("Czy używał(a) Docker w Allegro?");
    expect(candidateQuestion({ requirement: "Docker" })).toBe("Czy używał(a) Docker? W którym projekcie?");
  });
});

describe("co jest do poprawy, a co jest uwagą", () => {
  const failing = [
    check({ key: "cv_present", status: "pass" }),
    check({
      key: "critical_skills",
      status: "fail",
      items: [
        { requirement: "Hibernate", role: "Alfa", role_index: 0, fix: "ai" },
        { requirement: "Hibernate", role: "Beta", role_index: 1, fix: "ai" },
        { requirement: "Scala", fix: "ask_candidate" },
      ],
    }),
    check({ key: "no_unsupported", status: "fail", items: [{ requirement: "REST API", term: "REST API", fix: "remove_term" }] }),
    check({
      key: "client_rules",
      status: "fail",
      items: [
        { detail: "Stawka w CV: „150 zł/h”. Usuń — stawek w CV nie wysyłamy." },
        { detail: "Klient wymaga zrzutu zgody RODO pod CV — brak zrzutu.", fix: "upload_consent" },
      ],
    }),
    check({ key: "must_in_cv", severity: "warning", status: "fail", items: [{ requirement: "Kafka" }] }),
    check({ key: "years_header", severity: "warning", status: "manual" }),
    check({ key: "no_such_blocking", status: "manual" }),
    check({ key: "dates", severity: "warning", status: "skip" }),
  ];

  it("jedno wymaganie w kilku rolach to jedna rzecz; pozycje bez nazwy liczą się osobno (lustro `cv_qc._tasks`)", () => {
    const tasks = blockingTasks(failing);
    expect(tasks.map((t) => [t.check.key, t.name, t.items.length])).toEqual([
      ["critical_skills", "Hibernate", 2],
      ["critical_skills", "Scala", 1],
      ["no_unsupported", "REST API", 1],
      ["client_rules", null, 1],
      ["client_rules", null, 1],
    ]);
    // Serwer policzyłby tu `blocking_failed = 5`.
    expect(tasks).toHaveLength(5);
    expect(new Set(tasks.map((t) => t.id)).size).toBe(5);
  });

  it("niezaliczone sprawdzenie bez pozycji to nadal jedna rzecz", () => {
    expect(checkTasks(check({ key: "client_rules", status: "fail" }))).toHaveLength(1);
  });

  it("uwagi i sprawdzenia „ręcznie” nie blokują, niezależnie od wagi", () => {
    const split = splitChecks(failing);
    expect(split.notes.map((c) => c.key)).toEqual(["must_in_cv", "years_header", "no_such_blocking"]);
    expect(split.passed.map((c) => c.key)).toEqual(["cv_present"]);
    expect(split.skipped.map((c) => c.key)).toEqual(["dates"]);
  });

  it("tytuły kart mówią, co jest nie tak", () => {
    expect(blockingTasks(failing).map(taskTitle)).toEqual([
      "Hibernate — brak opisu w 2 rolach",
      "Scala — brak w CV i w oryginale",
      "REST API — jest w CV, a nie ma tego w oryginale",
      "Stawka w CV: „150 zł/h”. Usuń — stawek w CV nie wysyłamy.",
      "Klient wymaga zrzutu zgody RODO pod CV — brak zrzutu.",
    ]);
    const inSources = checkTasks(check({ key: "critical_skills", status: "fail", items: [{ requirement: "Go" }] }));
    expect(taskTitle(inSources[0])).toBe("Go — brak w CV");
    expect(taskTitle(checkTasks(check({ key: "cv_present", label: "CV firmowe jest przygotowane", status: "fail" }))[0])).toBe(
      "CV firmowe jest przygotowane",
    );
  });

  it("odmiana liczebników", () => {
    expect([1, 2, 5].map(thingsLabel)).toEqual(["1 rzecz", "2 rzeczy", "5 rzeczy"]);
    expect([1, 3, 5, 12, 22].map((n) => countForm(n, ["inna", "inne", "innych"]))).toEqual([
      "1 inna",
      "3 inne",
      "5 innych",
      "12 innych",
      "22 inne",
    ]);
  });

  it("linia pod uwagą: nazwy pozycji albo opis jedynej", () => {
    const names = ["Kafka", "JUnit 5", "Liquibase", "Confluence", "Jira"].map((requirement) => ({ requirement }));
    expect(notePreview(check({ items: names }))).toBe("Kafka, JUnit 5, Liquibase i 2 inne");
    expect(notePreview(check({ items: names.slice(0, 2) }))).toBe("Kafka, JUnit 5");
    expect(notePreview(check({ items: [{ detail: "Rola bez dat." }] }))).toBe("Rola bez dat.");
    expect(notePreview(check({ items: [] }))).toBeNull();
  });
});

describe("powody obejścia QC", () => {
  it("cztery powody, ostatni to „Inny powód”", () => {
    expect(QC_OVERRIDE_REASONS.map((r) => r.code)).toEqual([
      "client_short_cv",
      "confirmed_in_call",
      "requirement_not_applicable",
      "other",
    ]);
  });

  it("opis wymagany tylko przy „Inny powód”, bez minimum znaków", () => {
    expect(qcOverrideError(null, "")).toBe("Wybierz powód.");
    expect(qcOverrideError("client_short_cv", "")).toBeNull();
    expect(qcOverrideError("other", "  ")).toBe("Przy „Inny powód” napisz, dlaczego przepuszczasz.");
    expect(qcOverrideError("other", "ok")).toBeNull();
    expect(qcOverrideError("other", "x".repeat(901))).toMatch(/najwyżej 900 znaków/);
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
