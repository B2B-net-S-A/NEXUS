import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";

import type { QcCheck, QcFix } from "../api/cvQc";
import {
  bulkPlan,
  findingsInCv,
  fixAlreadyInCv,
  fixStep,
  issueMarks,
  locateTarget,
  termRanges,
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
