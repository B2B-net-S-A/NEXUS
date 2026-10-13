import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";

import type { CvPlanOperation } from "../api/cvEditorCommand";
import {
  applyPlan,
  commandBlocker,
  commandLines,
  cvLines,
  planEffect,
  planMarkCount,
  planMarks,
  setPlanMarks,
  type CvLine,
} from "../cv-editor-command";
import { cvEditorExtensions, loadCvHtml } from "../cv-editor-structure";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową.";
const CV =
  "<h1>Dev – Anna Przykładowa</h1>" + // 0
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' + // 1
  "<ul><li><p>Ponad 7 lat doświadczenia w <strong>Javie</strong>.</p></li>" + // 2
  "<li><p>Dobrze odnajduje się w zespole.</p></li></ul>" + // 3
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' + // 4
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' + // 5
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' + // 6
  '<p data-cv-section="duties_label">Zakres zadań:</p>' + // 7
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>" + // 8
  "<li><p>Udział w planowaniu sprintów.</p></li>" + // 9
  "<li><p>Udział w spotkaniach zespołu.</p></li></ul>" + // 10
  '<p data-cv-section="technologies">Technologie: Java, Kafka</p>' + // 11
  '<p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>' + // 12
  '<p data-cv-section="employer">Software House Przykład · IT</p>' + // 13
  "<ul><li><p>Usługi REST w Java 11.</p></li></ul>" + // 14
  "<h2>ZAINTERESOWANIA</h2>" + // 15
  "<p>Żeglarstwo, fotografia.</p>" + // 16
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

const editors: Editor[] = [];

function open(html = CV): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, html);
  editors.push(editor);
  return editor;
}

function op(id: number, type: CvPlanOperation["type"], lines: number[], text: string | null = null): CvPlanOperation {
  return { id, type, lines, text, why: "", loses: [] };
}

function apply(editor: Editor, lines: CvLine[], ...operations: CvPlanOperation[]): boolean {
  const transaction = applyPlan(editor.state, lines, operations);
  if (!transaction) return false;
  editor.view.dispatch(transaction);
  return true;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("CV wiersz po wierszu", () => {
  it("każdy blok i każdy punkt listy to wiersz; klauzula zgody nie jest wierszem", () => {
    const lines = cvLines(open().state.doc);
    expect(lines.map((line) => line.kind)).toEqual([
      "title",
      "heading",
      "bullet",
      "bullet",
      "heading",
      "role",
      "employer",
      "label",
      "bullet",
      "bullet",
      "bullet",
      "technologies",
      "role",
      "employer",
      "bullet",
      "heading",
      "text",
    ]);
    expect(lines.map((line) => line.id)).toEqual(lines.map((_, index) => index));
    expect(lines[8]).toMatchObject({ text: "Rozwój usług w **Java 17**.", section: "experience", role: 0, siblings: 3 });
    expect(lines[14]).toMatchObject({ role: 1, siblings: 1 });
    expect(lines[2]).toMatchObject({ section: "why_points", role: null });
    expect(lines.some((line) => line.text.includes("Wyrażam zgodę"))).toBe(false);
  });

  it("do serwera idzie tekst i miejsce wiersza — bez pozycji w dokumencie", () => {
    const rows = commandLines(cvLines(open().state.doc));
    expect(rows[8]).toEqual({ id: 8, kind: "bullet", text: "Rozwój usług w **Java 17**.", section: "experience", role: 0 });
    expect(rows[0]).toEqual({ id: 0, kind: "title", text: "Dev – Anna Przykładowa" });
    expect(Object.keys(rows[16]).sort()).toEqual(["id", "kind", "text"]);
  });

  it("za długie CV nie idzie do asystenta", () => {
    const lines = cvLines(open().state.doc);
    expect(commandBlocker(lines)).toBeNull();
    expect(commandBlocker([])).toMatch(/puste/);
    const long = open(`<h1>CV</h1><ul>${"<li><p>Rozwój usług w banku i systemach płatności.</p></li>".repeat(450)}</ul>`);
    expect(commandBlocker(cvLines(long.state.doc))).toMatch(/za długie/);
  });
});

describe("zastosowanie planu", () => {
  it("usunięcie punktów zostawia resztę listy, a wszystko cofa jedno „Cofnij”", () => {
    const editor = open();
    const before = editor.getHTML();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "remove", [9, 10]), op(1, "remove", [3]))).toBe(true);
    const html = editor.getHTML();
    expect(html).not.toContain("planowaniu sprintów");
    expect(html).not.toContain("spotkaniach zespołu");
    expect(html).not.toContain("odnajduje się w zespole");
    expect(html).toContain("<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li></ul>");
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("przeredagowanie podmienia treść punktu i zostawia jego miejsce na liście", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "replace", [8], "Rozwijała usługi w **Java 17**."))).toBe(true);
    expect(editor.getHTML()).toContain(
      "<ul><li><p>Rozwijała usługi w <strong>Java 17</strong>.</p></li><li><p>Udział w planowaniu sprintów.</p></li>",
    );
  });

  it("połączenie: pierwszy punkt dostaje nowy tekst, pozostałe znikają", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "merge", [9, 10], "Udział w planowaniu sprintów i spotkaniach zespołu."))).toBe(true);
    expect(editor.getHTML()).toContain(
      "<li><p>Rozwój usług w <strong>Java 17</strong>.</p></li><li><p>Udział w planowaniu sprintów i spotkaniach zespołu.</p></li></ul>",
    );
  });

  it("nowa kolejność przestawia całe punkty razem z pogrubieniem", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "reorder", [10, 8, 9]))).toBe(true);
    expect(editor.getHTML()).toContain(
      "<ul><li><p>Udział w spotkaniach zespołu.</p></li><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li><li><p>Udział w planowaniu sprintów.</p></li></ul>",
    );
  });

  it("stanowisko znika całe, następne i klauzula zostają", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "remove_role", [5, 6, 7, 8, 9, 10, 11]))).toBe(true);
    const html = editor.getHTML();
    expect(html).not.toContain("Senior Developer");
    expect(html).not.toContain("Technologie: Java, Kafka");
    expect(html).toContain('<h2 data-cv-section="experience">DOŚWIADCZENIE</h2><p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>');
    expect(html).toContain(CLAUSE);
  });

  it("sekcja znika razem z nagłówkiem; lista, z której znikają wszystkie punkty, też", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "remove_section", [15, 16]), op(1, "remove_section", [1, 2, 3]))).toBe(true);
    const html = editor.getHTML();
    expect(html).not.toContain("ZAINTERESOWANIA");
    expect(html).not.toContain("Żeglarstwo");
    expect(html).not.toContain("DLACZEGO NASZ KANDYDAT");
    expect(html.startsWith('<h1>Dev – Anna Przykładowa</h1><h2 data-cv-section="experience">')).toBe(true);
    expect(html).not.toContain("<ul></ul>");
  });

  it("kilka operacji naraz trafia we właściwe miejsca", () => {
    const editor = open();
    const before = editor.getHTML();
    const lines = cvLines(editor.state.doc);
    expect(
      apply(
        editor,
        lines,
        op(0, "replace", [2], "Ponad 7 lat pracy w **Javie**."),
        op(1, "remove", [3]),
        op(2, "merge", [9, 10], "Sprinty i spotkania zespołu."),
        op(3, "remove_section", [15, 16]),
        op(4, "replace", [14], "Tworzenie usług REST w Java 11."),
      ),
    ).toBe(true);
    const html = editor.getHTML();
    expect(html).toContain("<ul><li><p>Ponad 7 lat pracy w <strong>Javie</strong>.</p></li></ul>");
    expect(html).toContain("<li><p>Sprinty i spotkania zespołu.</p></li></ul>");
    expect(html).toContain("<ul><li><p>Tworzenie usług REST w Java 11.</p></li></ul>");
    expect(html).not.toContain("ZAINTERESOWANIA");
    expect(html).toContain(CLAUSE);
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("plan zamówiony dla innej treści niczego nie zmienia", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    editor.commands.insertContentAt(lines[9].innerFrom, "Aktywny ");
    const before = editor.getHTML();
    expect(apply(editor, lines, op(0, "remove", [9]))).toBe(false);
    expect(apply(editor, lines, op(0, "remove", [99]))).toBe(false);
    expect(editor.getHTML()).toBe(before);
    expect(applyPlan(editor.state, cvLines(editor.state.doc), [])).toBeNull();
  });
});

describe("podgląd planu", () => {
  it("pokazuje tylko zaznaczone operacje: co znika, co się zmienia, co się przestawia", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    const operations = [
      op(0, "remove", [3]),
      op(1, "merge", [9, 10], "Sprinty i spotkania."),
      op(2, "reorder", [14]),
      op(3, "remove_section", [15, 16]),
    ];
    const marks = planMarks(lines, operations, new Set([0, 1, 2]));
    expect(marks.map((mark) => [mark.operation, mark.tone])).toEqual([
      [0, "remove"],
      [1, "change"],
      [1, "remove"],
      [2, "move"],
    ]);
    expect(marks[1]).toMatchObject({ from: lines[9].from, to: lines[9].to, text: "Sprinty i spotkania.", at: lines[9].innerTo });
    expect(marks[3].order).toBe(1);

    const html = editor.getHTML();
    setPlanMarks(editor, marks);
    // Dekoracje i podgląd nowej treści żyją w widoku — treść dokumentu się nie zmienia.
    expect(planMarkCount(editor.state)).toBe(5);
    expect(editor.getHTML()).toBe(html);
    expect(editor.view.dom.querySelectorAll(".cv-plan-remove")).toHaveLength(2);
    expect(editor.view.dom.querySelector(".cv-plan-new")?.textContent).toBe("Sprinty i spotkania.");
    setPlanMarks(editor, []);
    expect(planMarkCount(editor.state)).toBe(0);
  });

  it("liczy, o ile krótsze będzie CV po zaznaczonych operacjach", () => {
    const lines = cvLines(open().state.doc);
    const operations = [op(0, "remove", [3]), op(1, "merge", [9, 10], "Sprinty i spotkania."), op(2, "reorder", [14])];
    const all = planEffect(lines, operations, new Set([0, 1, 2]));
    expect(all.before - all.after).toBe(
      "Dobrze odnajduje się w zespole.".length +
        "Udział w planowaniu sprintów.".length +
        "Udział w spotkaniach zespołu.".length -
        "Sprinty i spotkania.".length,
    );
    expect(planEffect(lines, operations, new Set([2])).after).toBe(all.before);
  });
});
