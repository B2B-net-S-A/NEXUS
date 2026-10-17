import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";

import type { QcCheck, QcFix } from "../api/cvQc";
import {
  appliedActions,
  appliedLabel,
  boldRequirements,
  buildIssueList,
  bulkPlan,
  findingsInCv,
  fixAlreadyInCv,
  fixStep,
  issueMarks,
  issueRows,
  itemQuickFix,
  locateTarget,
  rowInBulk,
  termRanges,
  yearsPreview,
} from "../cv-editor-issues";
import { cvEditorExtensions } from "../cv-editor-structure";
import { itemTarget } from "../cv-qc";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową w Javie.";
const CV =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>' +
  "<p><strong>Języki: </strong>Java, Kotlin, JavaScript</p>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
  "<ul><li><p>Rozwój usług w <strong>Java</strong> i Kafka.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java, Kafka</p>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>' +
  '<p data-cv-section="employer">Software House Przykład · IT</p>' +
  "<ul><li><p>Usługi REST w Java 11.</p></li></ul>" +
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

const editors: Editor[] = [];

function open(content = CV): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content });
  editors.push(editor);
  return editor;
}

function textAt(editor: Editor, range: { from: number; to: number } | null): string | null {
  return range ? editor.state.doc.textBetween(range.from, range.to, " ") : null;
}

function check(partial: Partial<QcCheck> & Pick<QcCheck, "key">): QcCheck {
  return { label: partial.key, severity: "warning", status: "fail", summary: null, items: [], ...partial };
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("miejsce uwagi w dokumencie", () => {
  it("stanowisko po numerze w sekcji doświadczenia wskazuje jego tytuł", () => {
    const editor = open();
    const second = locateTarget(editor.state.doc, { kind: "role", roleIndex: 1, label: null });
    expect(textAt(editor, second)).toBe("Developer 2017 – 2021");
    expect(second?.block).toBe(true);
  });

  it("bez numeru (albo z numerem spoza CV) szuka stanowiska po etykiecie roli", () => {
    const editor = open();
    const byLabel = locateTarget(editor.state.doc, {
      kind: "role",
      roleIndex: null,
      label: "Software House Przykład — Developer · 2017–2021",
    });
    expect(textAt(editor, byLabel)).toBe("Developer 2017 – 2021");
    const outOfRange = locateTarget(editor.state.doc, { kind: "role", roleIndex: 7, label: "Bank Przykładowy — Senior Developer" });
    expect(textAt(editor, outOfRange)).toBe("Senior Developer 2021 – 2024");
    expect(locateTarget(editor.state.doc, { kind: "role", roleIndex: 7, label: "Inna Firma — Tester" })).toBeNull();
  });

  it("termin z numerem roli wskazuje wystąpienie W TEJ roli, nie pierwsze w CV", () => {
    const editor = open();
    const inSecondRole = locateTarget(editor.state.doc, { kind: "term", term: "Java", roleIndex: 1, label: null });
    expect(inSecondRole?.block).toBe(false);
    const around = editor.state.doc.textBetween(inSecondRole!.from - 3, inSecondRole!.to + 3);
    expect(around).toBe(" w Java 11");
    // Bez roli — pierwsze wystąpienie w dokumencie (sekcja umiejętności).
    const first = locateTarget(editor.state.doc, { kind: "term", term: "Java", roleIndex: null, label: null });
    expect(first!.from).toBeLessThan(inSecondRole!.from);
  });

  it("termin, którego nie ma w roli, spada na całe CV, a potem na tytuł roli", () => {
    const editor = open();
    const elsewhere = locateTarget(editor.state.doc, { kind: "term", term: "Kotlin", roleIndex: 0, label: null });
    expect(textAt(editor, elsewhere)).toBe("Kotlin");
    const missing = locateTarget(editor.state.doc, { kind: "term", term: "Kubernetes", roleIndex: 0, label: null });
    expect(textAt(editor, missing)).toBe("Senior Developer 2021 – 2024");
    expect(locateTarget(editor.state.doc, { kind: "term", term: "Kubernetes", roleIndex: null, label: null })).toBeNull();
  });

  it("granice słowa: „Java” nie trafia w „JavaScript”", () => {
    const editor = open();
    const found = termRanges(editor.state.doc, "Java").map((range) => textAt(editor, range));
    // Umiejętności, punkt roli 1, technologie roli 1, punkt roli 2 — bez „JavaScript”.
    expect(found).toEqual(["Java", "Java", "Java", "Java"]);
  });

  it("klauzula zgody nie jest miejscem żadnej uwagi", () => {
    const editor = open();
    expect(locateTarget(editor.state.doc, { kind: "term", term: "Javie", roleIndex: null, label: null })).toBeNull();
    expect(locateTarget(editor.state.doc, { kind: "line", text: CLAUSE })).toBeNull();
  });

  it("linia kontroli AI: cały blok o tej treści, bez względu na odstępy i wielkość liter", () => {
    const editor = open();
    const line = locateTarget(editor.state.doc, { kind: "line", text: "  rozwój usług w java i kafka. " });
    expect(textAt(editor, line)).toBe("Rozwój usług w Java i Kafka.");
    expect(line?.block).toBe(true);
    expect(locateTarget(editor.state.doc, { kind: "line", text: "Rozwój usług" })).toBeNull();
  });

  it("pozycja QC bez miejsca w tekście nie ma celu", () => {
    expect(itemTarget({ detail: "Brak zrzutu zgody RODO.", fix: "upload_consent" })).toBeNull();
    expect(itemTarget({ requirement: "Kafka", role: "Bank — Dev", role_index: 0 })).toEqual({
      kind: "role",
      roleIndex: 0,
      label: "Bank — Dev",
    });
    expect(itemTarget({ term: " Javascript ", fix: "spelling" })).toEqual({
      kind: "term",
      term: "Javascript",
      roleIndex: null,
      label: null,
    });
  });
});

describe("znaczniki przy tekście", () => {
  const checks: QcCheck[] = [
    check({
      key: "critical_skills",
      severity: "blocking",
      items: [{ requirement: "Kubernetes", role: "Bank Przykładowy — Senior Developer", role_index: 0, fix: "ai" }],
    }),
    check({ key: "must_in_roles", items: [{ requirement: "Kafka", role: "Software House — Developer", role_index: 1 }] }),
    check({ key: "must_bolded", items: [{ requirement: "Java", term: "Java", fix: "bold_all" }] }),
    check({ key: "no_unsupported", severity: "blocking", items: [{ term: "Kafka", fix: "remove_term" }] }),
    check({ key: "spelling", status: "pass", items: [{ term: "Kotlin", fix: "spelling" }] }),
  ];

  it("stanowisko z brakiem krytycznej jest czerwone, z brakiem zwykłym — uwagą", () => {
    const editor = open();
    const blocks = issueMarks(editor.state.doc, checks, []).filter((mark) => mark.block);
    expect(blocks.map((mark) => [textAt(editor, mark), mark.tone])).toEqual([
      ["Senior Developer 2021 – 2024", "blocking"],
      ["Developer 2017 – 2021", "note"],
    ]);
  });

  it("sprawdzenie pogrubień zaznacza tylko wystąpienia BEZ pogrubienia", () => {
    const editor = open();
    const java = issueMarks(editor.state.doc, [checks[2]], []);
    // Pogrubione „Java” w punkcie roli 1 jest w porządku — zostają trzy pozostałe.
    expect(java).toHaveLength(3);
    expect(java.every((mark) => mark.tone === "note" && !mark.block)).toBe(true);
  });

  it("termin spoza oryginału jest zaznaczony wszędzie, zaliczone sprawdzenie — nigdzie", () => {
    const editor = open();
    const marks = issueMarks(editor.state.doc, [checks[3], checks[4]], []);
    expect(marks.map((mark) => [textAt(editor, mark), mark.tone])).toEqual([
      ["Kafka", "blocking"],
      ["Kafka", "blocking"],
    ]);
  });

  it("linia z kontroli AI ma znacznik, dopóki stoi w CV", () => {
    const editor = open();
    const findings = [
      { text: "Przeglądy kodu.", status: "unsupported" },
      { text: "Tej linii już nie ma.", status: "contradicted" },
    ];
    expect(findingsInCv(editor.state.doc, findings)).toEqual([findings[0]]);
    const marks = issueMarks(editor.state.doc, [], findings);
    expect(marks.map((mark) => textAt(editor, mark))).toEqual(["Przeglądy kodu."]);
  });

  it("po zmianie tekstu znacznik znika razem z miejscem", () => {
    const editor = open();
    const before = issueMarks(editor.state.doc, [checks[3]], []);
    const first = before[0];
    editor.view.dispatch(editor.state.tr.delete(first.from, first.to));
    expect(issueMarks(editor.state.doc, [checks[3]], [])).toHaveLength(before.length - 1);
  });
});

describe("„Popraw wszystko”", () => {
  const fix = (id: string): QcFix => ({
    id,
    check_key: "critical_skills",
    requirement: "Kafka",
    role: null,
    current_text: null,
    proposed_text: "Zdanie.",
    source: "original",
    source_quote: "cytat",
  });

  it("zbiera poprawki formalne i zdania AI, a pomija usunięcie terminu", () => {
    const plan = bulkPlan(
      [
        check({
          key: "must_bolded",
          items: [
            { term: "Java", fix: "bold_all" },
            { term: "Kafka", fix: "bold_all" },
          ],
        }),
        check({ key: "nice_bolded", items: [{ term: "Docker", fix: "bold_all" }] }),
        check({ key: "spelling", items: [{ term: "Javascript", fix: "spelling" }] }),
        check({ key: "no_unsupported", severity: "blocking", items: [{ term: "AWS", fix: "remove_term" }] }),
      ],
      [fix("f1"), fix("f2")],
    );
    // Zdania AI pierwsze: szukają swojej linii po tekście, który pisownia zmienia.
    expect(plan.actions).toEqual([
      { action: "ai_fix", fix_id: "f1" },
      { action: "ai_fix", fix_id: "f2" },
      { action: "bold_all", scope: "must" },
      { action: "bold_all", scope: "nice" },
      { action: "spelling" },
    ]);
    expect(plan.parts).toEqual([
      "pogrubienie 2 wymagań must-have",
      "pogrubienie 1 wymagania mile widzianych",
      "pisownia 1 technologii",
      "2 zdania AI z cytatem ze źródła",
    ]);
  });

  it("zaliczone sprawdzenie i lista bez poprawek dają pusty plan", () => {
    const passed = check({ key: "must_bolded", status: "pass", items: [{ term: "Java", fix: "bold_all" }] });
    expect(bulkPlan([passed], [])).toEqual({ actions: [], parts: [] });
  });
});

describe("„Pogrub wymagania (N)” (Edytor CV 3, PR 3)", () => {
  it("liczy niepogrubione wymagania must i nice, po jednej poprawce na zakres", () => {
    const result = boldRequirements([
      check({ key: "must_bolded", items: [{ term: "Java", fix: "bold_all" }, { term: "Kafka", fix: "bold_all" }] }),
      check({ key: "nice_bolded", items: [{ term: "Terraform", fix: "bold_all" }] }),
      check({ key: "tech_spelling", items: [{ term: "Github", fix: "spelling" }] }),
    ]);
    expect(result.count).toBe(3);
    expect(result.actions).toEqual([
      { action: "bold_all", scope: "must" },
      { action: "bold_all", scope: "nice" },
    ]);
  });

  it("CV, które z założenia nie pogrubia: liczy informacje QC z poprawką „Pogrub” (16.10.2026)", () => {
    // QC mówi „nie dotyczy” (Redakcja) i nie ma uwag — przycisk i tak pogrubia.
    const result = boldRequirements([
      check({ key: "must_bolded", status: "skip", info: [{ term: "Kubernetes", fix: "bold_all" }] }),
      check({ key: "nice_bolded", status: "skip", info: [{ term: "Kafka", fix: "bold_all" }] }),
      check({ key: "must_in_roles", status: "fail", info: [{ term: "Java", fix: null }] }),
    ]);
    expect(result.count).toBe(2);
    expect(result.actions).toEqual([
      { action: "bold_all", scope: "must" },
      { action: "bold_all", scope: "nice" },
    ]);
  });

  it("zaliczone sprawdzenie z wymaganiem pogrubionym nie wszędzie też się liczy (16.10.2026)", () => {
    const partly = check({ key: "must_bolded", status: "pass", info: [{ term: "Java", fix: "bold_all" }] });
    expect(boldRequirements([partly])).toEqual({ count: 1, actions: [{ action: "bold_all", scope: "must" }] });
  });

  it("wszystko pogrubione = zero i brak poprawki; brak wyniku QC = bez liczby", () => {
    const passed = check({ key: "must_bolded", status: "pass", items: [{ term: "Java", fix: "bold_all" }] });
    expect(boldRequirements([passed])).toEqual({ count: 0, actions: [] });
    expect(boldRequirements(null)).toEqual({ count: null, actions: [] });
  });
});

describe("nałożenie wyniku serwera", () => {
  it("zamienia tylko zmieniony blok i cofa się jednym krokiem", () => {
    const editor = open();
    const before = editor.getHTML();
    const fixed = before.replace("Przeglądy kodu.", "Przeglądy kodu i <strong>Kubernetes</strong>.");
    const step = fixStep(editor.state, fixed);
    expect(step).not.toBeNull();
    editor.view.dispatch(step!.transaction);
    expect(editor.getHTML()).toBe(fixed);
    // Wyróżnione miejsce to sam zmieniony punkt, nie reszta CV.
    expect(step!.changed.map((range) => textAt(editor, range))).toEqual(["Przeglądy kodu i Kubernetes."]);
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("dwie poprawki w różnych sekcjach to dwa małe miejsca i nadal JEDNO cofnięcie", () => {
    const editor = open();
    const before = editor.getHTML();
    const fixed = before.replace("Kotlin", "Kotlin, Scala").replace("Usługi REST w Java 11.", "Usługi REST w <strong>Java</strong> 11.");
    const step = fixStep(editor.state, fixed)!;
    editor.view.dispatch(step.transaction);
    expect(editor.getHTML()).toBe(fixed);
    expect(step.changed.map((range) => textAt(editor, range))).toEqual([
      "Języki: Java, Kotlin, Scala, JavaScript",
      "Usługi REST w Java 11.",
    ]);
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("poprawka jest osobnym krokiem historii — „Cofnij” nie zabiera tekstu wpisanego tuż przed nią", () => {
    const editor = open();
    const at = editor.state.doc.content.size - CLAUSE.length - 3;
    editor.commands.insertContentAt(at, " Dopisek.");
    const typed = editor.getHTML();
    expect(typed).toContain("Dopisek.");
    editor.view.dispatch(fixStep(editor.state, typed.replace("Dopisek.", "Dopisek i poprawka."))!.transaction);
    editor.commands.undo();
    expect(editor.getHTML()).toBe(typed);
  });

  it("propozycja AI znika z listy, gdy jej zdanie stoi w CV, i wraca po cofnięciu", () => {
    const editor = open();
    const fix = {
      id: "f1",
      check_key: "critical_skills",
      requirement: "Kubernetes",
      role: null,
      current_text: "Przeglądy kodu.",
      proposed_text: "Przeglądy kodu i wdrożenia na **Kubernetes**.",
      source: "original" as const,
      source_quote: null,
    };
    expect(fixAlreadyInCv(editor.state.doc, fix)).toBe(false);
    const fixed = editor.getHTML().replace("Przeglądy kodu.", "Przeglądy kodu i wdrożenia na <strong>Kubernetes</strong>.");
    editor.view.dispatch(fixStep(editor.state, fixed)!.transaction);
    expect(fixAlreadyInCv(editor.state.doc, fix)).toBe(true);
    editor.commands.undo();
    expect(fixAlreadyInCv(editor.state.doc, fix)).toBe(false);
  });

  it("dopisany punkt (także taki sam jak sąsiedni) zmienia tylko listę", () => {
    const editor = open();
    const before = editor.getHTML();
    const fixed = before.replace("<li><p>Przeglądy kodu.</p></li>", "<li><p>Przeglądy kodu.</p></li><li><p>Przeglądy kodu.</p></li>");
    const step = fixStep(editor.state, fixed)!;
    editor.view.dispatch(step.transaction);
    expect(editor.getHTML()).toBe(fixed);
    expect(step.changed.map((range) => textAt(editor, range))).toEqual(["Przeglądy kodu."]);
  });

  it("usunięty blok i zmieniona liczba bloków też dają nową treść", () => {
    const editor = open();
    const fixed = editor.getHTML().replace('<p data-cv-section="technologies">Technologie: Java, Kafka</p>', "").replace("Kotlin", "Scala");
    editor.view.dispatch(fixStep(editor.state, fixed)!.transaction);
    expect(editor.getHTML()).toBe(fixed);
  });

  // Starsze CV: klauzula zgody bez znacznika ma tę samą budowę co zwykły akapit.
  // Najmniejsza zamiana sąsiedniego akapitu zaczynającego się tą samą literą
  // („W…” jak „Wyrażam…”) wchodziła wtedy W ŚRODEK klauzuli: wtyczka struktury
  // odrzucała ją po cichu albo — gorzej — przyjmowała, ale odrzucała jej cofnięcie.
  const UNMARKED = `<p>${CLAUSE}</p>`;

  it.each(["Wolontariat.", "Wyrażam się jasno."])(
    "klauzula bez znacznika: akapit „%s” dopisany tuż przed nią wchodzi i daje się cofnąć",
    (added) => {
      const editor = open(`<h1>CV</h1><p>Opis.</p>${UNMARKED}`);
      const before = editor.getHTML();
      const fixed = `<h1>CV</h1><p>Opis.</p><p>${added}</p>${UNMARKED}`;
      const step = fixStep(editor.state, fixed)!;
      expect(editor.state.applyTransaction(step.transaction).transactions).toContain(step.transaction);
      editor.view.dispatch(step.transaction);
      expect(editor.getHTML()).toBe(fixed);
      editor.commands.undo();
      expect(editor.getHTML()).toBe(before);
      expect(editor.can().undo()).toBe(false);
    },
  );

  it.each(["Wolontariat.", "Wyrażam się jasno."])(
    "klauzula bez znacznika: akapit „%s” usunięty tuż przed nią daje się cofnąć",
    (removed) => {
      const editor = open(`<h1>CV</h1><p>Opis.</p><p>${removed}</p>${UNMARKED}`);
      const before = editor.getHTML();
      const fixed = `<h1>CV</h1><p>Opis.</p>${UNMARKED}`;
      const step = fixStep(editor.state, fixed)!;
      editor.view.dispatch(step.transaction);
      expect(editor.getHTML()).toBe(fixed);
      editor.commands.undo();
      // Bez poprawki: „Cofnij” nic nie robiło i blokowało wcześniejsze zmiany.
      expect(editor.getHTML()).toBe(before);
      expect(editor.can().undo()).toBe(false);
    },
  );

  it("klauzula bez znacznika: zmienione miejsca nadal wskazują sam dopisany akapit", () => {
    const editor = open(`<h1>CV</h1><p>Opis.</p>${UNMARKED}`);
    const step = fixStep(editor.state, `<h1>CV</h1><p>Opis.</p><p>Wolontariat.</p>${UNMARKED}`)!;
    editor.view.dispatch(step.transaction);
    // Podświetlenie po poprawce nie obejmuje całego dokumentu ani klauzuli.
    const marked = step.changed.map((range) => textAt(editor, range)).join(" ");
    expect(marked).toContain("olontariat.");
    expect(marked).not.toContain("przetwarzanie");
  });

  it("treść równa bieżącej (po wczytaniu do schematu) nie daje transakcji", () => {
    const editor = open();
    // `<b>` i dodatkowe odstępy serwera to dla edytora ten sam dokument.
    const same = editor.getHTML().replace("<strong>Senior Developer</strong>", "<b>Senior Developer</b>");
    expect(fixStep(editor.state, same)).toBeNull();
  });

  it("klauzula zgody zostaje jedna i na końcu", () => {
    const editor = open();
    const fixed = editor.getHTML().replace("Kotlin", "Kotlin, Scala");
    editor.view.dispatch(fixStep(editor.state, fixed)!.transaction);
    expect(editor.getHTML().split(CLAUSE)).toHaveLength(2);
    expect(editor.getHTML().endsWith(`${CLAUSE}</p>`)).toBe(true);
  });
});

describe("jedna lista „Do poprawy” (PR 4, 13.10.2026)", () => {
  const ids = (entries: { id: string }[]) => entries.map((entry) => entry.id);

  it("grupuje po sekcjach CV w kolejności kartki, „Całe CV” pierwsze, w grupie blokady pierwsze", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [
        check({ key: "client_rules", severity: "blocking", items: [{ detail: "Stawka w CV" }] }),
        check({ key: "must_bolded", items: [{ requirement: "Java", term: "Java", fix: "bold_all" }] }),
        check({ key: "no_unsupported", severity: "blocking", items: [{ term: "Kafka", fix: "remove_term" }] }),
        check({ key: "title_matches_role", items: [{ term: "Dev" }] }),
        check({ key: "dates", status: "pass" }),
        check({ key: "years_header", status: "skip" }),
      ],
      warnings: ["WERYFIKUJ: usunięto „OpenTelemetry” z umiejętności", "Wyróżnienia: pogrubiono 4 terminy."],
      findings: [{ text: "Przeglądy kodu.", status: "unsupported" }],
    });
    expect(list.sections.map((group) => [group.key, group.label])).toEqual([
      ["whole", "Całe CV"],
      ["header", "Nagłówek"],
      ["skills", "Umiejętności"],
      ["experience", "Doświadczenie"],
    ]);
    const [whole, header, skills, experience] = list.sections;
    expect(ids(whole.entries)).toEqual([
      "qc:client_rules:#0",
      "generator:WERYFIKUJ: usunięto „OpenTelemetry” z umiejętności",
    ]);
    expect(ids(header.entries)).toEqual(["qc:title_matches_role"]);
    // Pierwsze „Java” stoi w umiejętnościach.
    expect(ids(skills.entries)).toEqual(["qc:must_bolded"]);
    // W grupie najpierw to, co zatrzymuje wysyłkę, potem reszta w kolejności tekstu.
    expect(ids(experience.entries)).toEqual(["qc:no_unsupported:Kafka", "review:0:unsupported:Przeglądy kodu."]);
    expect(experience.entries.map((entry) => entry.source)).toEqual(["qc", "review"]);
    expect(list.info.map((item) => item.text)).toEqual(["Wyróżnienia: pogrubiono 4 terminy."]);
    expect(list.passed.map((c) => c.key)).toEqual(["dates"]);
    expect(list.skipped.map((c) => c.key)).toEqual(["years_header"]);
    // 2 blokady + 2 uwagi QC + 1 uwaga generatora + 1 linia kontroli AI.
    expect(list.total).toBe(6);
  });

  it("„MUST-HAVE: X” od generatora nie dubluje pozycji QC o X — zostaje w „covered”", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [check({ key: "must_in_cv", items: [{ requirement: "Apache Kafka", detail: "Brak w CV", fix: "ai" }] })],
      warnings: ["MUST-HAVE: Kafka", "MUST-HAVE: Kubernetes"],
      findings: [],
    });
    const all = list.sections.flatMap((group) => group.entries);
    expect(ids(all)).toEqual(["qc:must_in_cv", "generator:MUST-HAVE: Kubernetes"]);
    expect(list.covered.map((item) => item.text)).toEqual(["MUST-HAVE: Kafka"]);
    expect(list.total).toBe(2);
  });

  it("„Zapytaj kandydata”: krytyczna bez opisu w oryginale i uwaga z samymi pytaniami", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [
        check({
          key: "critical_skills",
          severity: "blocking",
          items: [
            { requirement: "Docker", role: "Bank Przykładowy — Senior Developer", role_index: 0, evidence_kind: "technologies" },
            { requirement: "Kafka", role: "Bank Przykładowy — Senior Developer", role_index: 0, evidence_kind: "description" },
          ],
        }),
        check({ key: "must_in_cv", items: [{ requirement: "Terraform", fix: "ask_candidate" }] }),
      ],
      warnings: [],
      findings: [],
    });
    expect(ids(list.ask)).toEqual(["qc:critical_skills:Docker", "qc:must_in_cv"]);
    // Kafka ma zdanie w oryginale — AI dopisze, więc zostaje przy stanowisku.
    expect(list.sections.map((group) => [group.key, ids(group.entries)])).toEqual([
      ["experience", ["qc:critical_skills:Kafka"]],
    ]);
    expect(list.total).toBe(3);
  });

  it("pozycja w kilku sekcjach i bez dokumentu trafia do „Całe CV”", () => {
    const editor = open();
    const spread = check({
      key: "spelling",
      items: [
        { term: "Kotlin", fix: "spelling" },
        { term: "REST", role_index: 1, fix: "spelling" },
      ],
    });
    expect(buildIssueList({ doc: editor.state.doc, checks: [spread], warnings: [], findings: [] }).sections[0].key).toBe(
      "whole",
    );
    const blind = buildIssueList({
      doc: null,
      checks: [check({ key: "must_bolded", items: [{ term: "Java", fix: "bold_all" }] })],
      warnings: [],
      findings: [{ text: "Przeglądy kodu.", status: "unsupported" }],
    });
    expect(blind.sections.map((group) => [group.key, group.entries.length])).toEqual([["whole", 2]]);
  });

  it("wyciszone w „Jakość QC” stoją w informacjach i się nie liczą", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [check({ key: "must_bolded", muted: true, items: [{ term: "Java", fix: "bold_all" }] })],
      warnings: [],
      findings: [],
    });
    expect(list.sections).toEqual([]);
    expect(list.muted.map((c) => c.key)).toEqual(["must_bolded"]);
    expect(list.total).toBe(0);
  });
});

describe("wiersze po wadze (wariant A, 17.10.2026)", () => {
  const kafkaFix = (overrides: Partial<QcFix> = {}): QcFix => ({
    id: "f-kafka",
    check_key: "critical_skills",
    requirement: "Kafka",
    role: "Bank Przykładowy — Senior Developer",
    role_index: 0,
    cv_role_label: "Senior Developer · Bank Przykładowy",
    current_text: null,
    proposed_text: "Integracje przez **Kafka**.",
    source: "original",
    source_quote: "Kafka w integracjach",
    ...overrides,
  });
  const shape = (rows: { kind: string; id: string }[]) => rows.map((row) => `${row.kind}:${row.id}`);

  it("blokady osobno, poprawki jednym przyciskiem w „Do poprawy”, reszta w „Do decyzji”", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [
        check({ key: "no_unsupported", severity: "blocking", items: [{ key: "u", term: "Kafka", fix: "remove_term" }] }),
        check({
          key: "must_bolded",
          items: [
            { key: "b1", requirement: "Java", term: "Java", fix: "bold_all" },
            { key: "b2", requirement: "Kotlin", term: "Kotlin", fix: "bold_all" },
          ],
        }),
        check({ key: "spelling", items: [{ key: "s", term: "Github", fix: "spelling", detail: "„Github” → „GitHub”" }] }),
        check({ key: "role_order", items: [{ key: "r", role: "Developer", fix: "role_order", role_index: 1 }] }),
        check({ key: "years_header", items: [{ key: "y", term: "10 lat", detail: "Nagłówek mówi „10 lat”, a z dat historii wychodzi 7." }] }),
        check({ key: "title_matches_role", status: "manual", items: [] }),
      ],
      warnings: ["WERYFIKUJ: usunięto „OpenTelemetry” z umiejętności"],
      findings: [{ text: "Przeglądy kodu.", status: "unsupported" }],
    });
    const rows = issueRows(list, [], false);
    expect(shape(rows.blocking)).toEqual(["task:qc:no_unsupported:Kafka"]);
    // Pogrubienie i pisownia: jeden wiersz na sprawdzenie, nie na wymaganie.
    // Od PR 2 lata w nagłówku też mają przycisk (D3) — są w „Do poprawy”.
    // Kolejność idzie za miejscem w CV (lata stoją w nagłówku) — liczą się rodzaje.
    expect(rows.fixable.map((row) => row.kind).sort()).toEqual(["check-fix", "check-fix", "item", "item"]);
    const bold = rows.fixable.find((row) => row.kind === "check-fix" && row.fix === "bold_all");
    expect(bold?.kind === "check-fix" ? bold.items.map((item) => item.requirement) : null).toEqual(["Java", "Kotlin"]);
    expect(rows.fixable.some((row) => row.kind === "item" && row.item.fix === "role_order")).toBe(true);
    // Bez gotowej poprawki: uwaga do obejrzenia ręcznie, generator, kontrola AI.
    expect(rows.decide.map((row) => row.kind).sort()).toEqual(["check", "finding", "warning"]);
  });

  it("zdanie AI stoi w wierszu swojej uwagi; propozycja bez pozycji dostaje własny wiersz", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [
        check({
          key: "critical_skills",
          severity: "blocking",
          items: [{ key: "c", requirement: "Kafka", role: "Bank Przykładowy — Senior Developer", role_index: 0, fix: "ai", evidence_kind: "description" }],
        }),
        check({ key: "must_in_roles", items: [{ key: "m", requirement: "Docker", role: "Software House Przykład — Developer", role_index: 1, fix: "ai" }] }),
      ],
      warnings: [],
      findings: [],
    });
    const loose = kafkaFix({ id: "f-old", check_key: "must_in_roles", requirement: "Terraform", role_index: 1 });
    const docker = kafkaFix({ id: "f-docker", check_key: "must_in_roles", requirement: "Docker", role_index: 1, role: "Software House Przykład — Developer" });
    const rows = issueRows(list, [kafkaFix(), docker, loose], false);
    expect(rows.blocking[0].kind === "task" ? rows.blocking[0].fixes.map((fix) => fix.id) : null).toEqual(["f-kafka"]);
    expect(rows.fixable.map((row) => (row.kind === "item" ? `item:${row.fixes.map((f) => f.id)}` : row.kind))).toEqual([
      "item:f-docker",
      "proposal",
    ]);
    // Rola się nie zgadza — propozycja nie trafia do cudzej pozycji.
    const wrongRole = issueRows(list, [kafkaFix({ role_index: 1 })], false);
    expect(wrongRole.blocking[0].kind === "task" ? wrongRole.blocking[0].fixes : null).toEqual([]);
    expect(wrongRole.fixable.map((row) => row.kind)).toEqual(["proposal"]);
    expect([...rows.blocking, ...rows.fixable].every(rowInBulk)).toBe(true);
  });

  it("pozycja z poprawką AI: w trakcie ładowania w „Do poprawy”, bez propozycji — w „Do decyzji”", () => {
    const editor = open();
    const list = buildIssueList({
      doc: editor.state.doc,
      checks: [check({ key: "must_in_roles", items: [{ key: "m", requirement: "Docker", role_index: 1, fix: "ai" }] })],
      warnings: [],
      findings: [],
    });
    expect(issueRows(list, [], true).fixable.map((row) => row.kind)).toEqual(["item"]);
    expect(issueRows(list, [], false).decide.map((row) => row.kind)).toEqual(["item"]);
    expect(rowInBulk(issueRows(list, [], true).fixable[0])).toBe(false);
  });

  it("„Poprawione” mówi, co nałożono: nazwy wymagań, termin, miejsce zdania", () => {
    const checks = [
      check({ key: "must_bolded", items: [{ requirement: "Java", fix: "bold_all" }, { requirement: "Kotlin", fix: "bold_all" }] }),
    ];
    const fixes = [kafkaFix()];
    expect(appliedLabel({ action: "bold_all", scope: "must" }, checks, fixes)).toBe("Pogrubiono: Java, Kotlin");
    expect(appliedLabel({ action: "bold_all", scope: "nice" }, checks, fixes)).toBe("Pogrubiono wymagania klienta");
    expect(appliedLabel({ action: "remove_term", term: "AWS" }, checks, fixes)).toBe("Usunięto „AWS” z CV");
    expect(appliedLabel({ action: "ai_fix", fix_id: "f-kafka" }, checks, fixes)).toBe(
      "Dopisano zdanie: Kafka · Senior Developer · Bank Przykładowy",
    );
    expect(appliedLabel({ action: "role_order" }, checks, fixes)).toBe("Ułożono stanowiska od najnowszego");
    // Z „Popraw wszystkie” liczy się tylko to, co serwer naprawdę nałożył.
    expect(
      appliedActions(
        [{ action: "ai_fix", fix_id: "a" }, { action: "ai_fix", fix_id: "b" }, { action: "spelling" }],
        [{ action: "ai_fix", fix_id: "b" }],
      ),
    ).toEqual([{ action: "ai_fix", fix_id: "b" }]);
    // Pogrubienie must nałożone, nice pominięte — „Poprawione” nie może mówić o nice (przegląd 17.10).
    expect(
      appliedActions(
        [{ action: "bold_all", scope: "must" }, { action: "bold_all", scope: "nice" }, { action: "remove_term", term: "AWS" }],
        [{ action: "bold_all", scope: "must", count: 2 }, { action: "remove_term", term: "Kafka", count: 1 }],
      ),
    ).toEqual([{ action: "bold_all", scope: "must" }]);
  });
});

describe("poprawki jednym kliknięciem po kluczu sprawdzenia (PR 2, 17.10.2026)", () => {
  const years = check({
    key: "years_header",
    items: [{ term: "Ponad 10 lat doświadczenia", detail: "Nagłówek mówi „Ponad 10 lat doświadczenia”, a z dat historii wychodzi 3." }],
  });
  const title = check({ key: "title_matches_role", items: [{ term: "Senior Java Developer", detail: "Początek CV nie mówi…" }] });
  const rules = check({
    key: "client_rules",
    severity: "blocking",
    items: [
      { detail: "Stawka w CV: „150 zł/h”. Usuń — stawek w CV nie wysyłamy." },
      { detail: "Klient wymaga zrzutu zgody RODO pod CV — brak zrzutu.", fix: "upload_consent" },
    ],
  });

  it("rozpoznaje lata, tytuł i stawkę bez nowego pola w wyniku QC", () => {
    expect(itemQuickFix(years, years.items[0])).toEqual({ action: "years" });
    expect(itemQuickFix(title, title.items[0])).toEqual({ action: "title" });
    expect(itemQuickFix(rules, rules.items[0])).toEqual({ action: "strip_client_rules" });
    // Pozycja z własną poprawką (zgoda RODO) i zaliczone sprawdzenie — nic.
    expect(itemQuickFix(rules, rules.items[1])).toBeNull();
    expect(itemQuickFix({ ...years, status: "pass" }, years.items[0])).toBeNull();
    expect(itemQuickFix(check({ key: "dates", items: [{ role: "Dev", detail: "Rola bez dat." }] }), { role: "Dev" })).toBeNull();
  });

  it("lata bez przycisku, gdy serwer ich nie poprawi: zero lat albo staż kilku firm naraz (17.10.2026)", () => {
    const company = (term: string, n: number) =>
      itemQuickFix(years, { term, detail: `CV mówi „${term}”, a z dat roli w Bank Alfa wychodzi ${n}.` });
    // Produkcja: „3 lata w <A> i <B>”, z dat A wychodzi 0.
    expect(company("3 lata w Bank Alfa i Delta Soft", 0)).toBeNull();
    expect(company("12 lat w Bank Alfa i Delta Soft", 8)).toBeNull();
    expect(company("12 lat w Bank Alfa & Delta", 8)).toBeNull();
    expect(company("12 lat w Bank Alfa", 8)).toEqual({ action: "years" });
    // Nagłówek z „i” po stażu to nie kilka firm.
    expect(
      itemQuickFix(years, { term: "Ponad 10 lat w Javie i Kotlinie", detail: "Nagłówek mówi „…”, a z dat historii wychodzi 7." }),
    ).toEqual({ action: "years" });
    expect(bulkPlan([check({ key: "years_header", items: [{ term: "3 lata w Bank Alfa i Delta Soft", detail: "… z dat roli w Bank Alfa wychodzi 0." }] })], []).actions).toEqual([]);
  });

  it("podgląd lat odmienia „lat” → „lata” i bez liczby z historii nie zgaduje", () => {
    expect(yearsPreview(years.items[0])).toEqual({ before: "Ponad 10 lat doświadczenia", after: "Ponad 3 lata doświadczenia" });
    expect(yearsPreview({ term: "8+ years of experience", detail: "… wychodzi 1." })).toEqual({
      before: "8+ years of experience",
      after: "1+ year of experience",
    });
    expect(yearsPreview({ term: "Ponad 10 lat", detail: "historia bez dat" })).toBeNull();
  });

  it("lata i tytuł w „Do poprawy” i w „Popraw wszystkie” (D4); stawka zostaje blokadą bez hurtu", () => {
    const editor = open();
    const list = buildIssueList({ doc: editor.state.doc, checks: [years, title, rules], warnings: [], findings: [] });
    const rows = issueRows(list, [], false);
    expect(rows.fixable.map((row) => (row.kind === "item" ? itemQuickFix(row.check, row.item)?.action : row.kind))).toEqual([
      "years",
      "title",
    ]);
    expect(rows.fixable.every(rowInBulk)).toBe(true);
    expect(rows.blocking.map((row) => row.kind)).toEqual(["task", "task"]);
    expect(rows.blocking.some(rowInBulk)).toBe(false);
    const plan = bulkPlan([years, title, rules], []);
    expect(plan.actions).toEqual([{ action: "years" }, { action: "title" }]);
    expect(plan.parts).toEqual(["lata doświadczenia według historii", "tytuł CV z rekrutacji"]);
  });
});
