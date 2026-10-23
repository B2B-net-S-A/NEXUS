import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";

import type { CvPlanOperation } from "../api/cvEditorCommand";
import {
  applyChanges,
  applyPlan,
  assistantHighlightCount,
  canApply,
  commandBlocker,
  commandLines,
  cvLines,
  setAssistantHighlight,
  splitPlan,
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
  return { id, type, lines, text, why: "", loses: [], new_words: [] };
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

  it("nowa kolejność omija pusty punkt i nie znika po cichu, gdy punkty stoją w dwóch listach", () => {
    // Serwer liczy tylko punkty z treścią; pusty zostaje na swoim miejscu.
    const blank = open(
      "<h1>CV</h1>" +
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
        '<p data-cv-section="role"><strong>Developer</strong> 2021 – 2024</p>' +
        "<ul><li><p>Pierwszy punkt.</p></li><li><p></p></li><li><p>Drugi punkt.</p></li></ul>",
    );
    const rows = cvLines(blank.state.doc);
    const [first, second] = rows.filter((line) => line.kind === "bullet" && line.text !== "");
    const reorder = op(0, "reorder", [second.id, first.id]);
    expect(canApply(reorder, rows)).toBe(true);
    expect(apply(blank, rows, reorder)).toBe(true);
    expect(blank.getHTML()).toContain("<ul><li><p>Drugi punkt.</p></li><li><p></p></li><li><p>Pierwszy punkt.</p></li></ul>");

    // Punkty jednego stanowiska w dwóch listach: tej operacji edytor nie umie
    // nałożyć — mówi o tym, zamiast pominąć ją przy „Zastosuj”.
    const split = open(
      "<h1>CV</h1>" +
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
        '<p data-cv-section="role"><strong>Developer</strong> 2021 – 2024</p>' +
        "<ul><li><p>Punkt A.</p></li><li><p>Punkt B.</p></li></ul><p>Projekty:</p><ul><li><p>Punkt C.</p></li></ul>",
    );
    const lines = cvLines(split.state.doc);
    const bullets = lines.filter((line) => line.kind === "bullet").map((line) => line.id);
    const across = op(0, "reorder", [bullets[2], bullets[0], bullets[1]]);
    const before = split.getHTML();
    expect(canApply(across, lines)).toBe(false);
    expect(applyPlan(split.state, lines, [across, op(1, "replace", [bullets[0]], "Punkt A zmieniony.")])).toBeNull();
    expect(split.getHTML()).toBe(before);
    expect(canApply(op(1, "replace", [bullets[0]], "Punkt A zmieniony."), lines)).toBe(true);
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

describe("asystent: nowe operacje i podświetlenie (Edytor CV 3, PR 4)", () => {
  const html = (editor: Editor) => editor.getHTML();

  it("dopisany punkt staje za wskazanym punktem tej samej listy; całość cofa jedno „Cofnij”", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    const before = html(editor);
    const result = applyChanges(editor.state, lines, [op(0, "add", [9], "Integracje przez **Kafka**.")]);
    expect(result).not.toBeNull();
    editor.view.dispatch(result!.transaction);
    expect(html(editor)).toContain(
      "<li><p>Udział w planowaniu sprintów.</p></li><li><p>Integracje przez <strong>Kafka</strong>.</p></li>",
    );
    // Zmieniona treść to nowy punkt — do podświetlenia.
    const [range] = result!.changed;
    expect(editor.state.doc.textBetween(range.from, range.to)).toBe("Integracje przez Kafka.");
    editor.commands.undo();
    expect(html(editor)).toBe(before);
  });

  // Przegląd PR 4: dopisanie za X i usunięcie następnego wiersza zaczynają się
  // w tym samym miejscu — kolejność kroków decyduje, czy dokument przeżyje.
  it("dopisanie za punktem i usunięcie następnego punktu w jednym planie", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "add", [8], "Integracje przez **Kafka**."), op(1, "remove", [9]))).toBe(true);
    expect(html(editor)).toContain(
      "<li><p>Rozwój usług w <strong>Java 17</strong>.</p></li><li><p>Integracje przez <strong>Kafka</strong>.</p></li>" +
        "<li><p>Udział w spotkaniach zespołu.</p></li>",
    );
    expect(html(editor)).not.toContain("planowaniu");
  });

  it("dwa punkty za tym samym wierszem stają w kolejności planu", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "add", [8], "Pierwszy."), op(1, "add", [8], "Drugi."))).toBe(true);
    expect(html(editor)).toContain(
      "<li><p>Rozwój usług w <strong>Java 17</strong>.</p></li><li><p>Pierwszy.</p></li><li><p>Drugi.</p></li>" +
        "<li><p>Udział w planowaniu sprintów.</p></li>",
    );
  });

  it("akapit za technologiami zostaje, gdy znika następne stanowisko", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(apply(editor, lines, op(0, "add", [11], "Wcześniej: Spring."), op(1, "remove_role", [12, 13, 14]))).toBe(true);
    expect(html(editor)).toContain("Technologie: Java, Kafka</p><p>Wcześniej: Spring.</p><h2>ZAINTERESOWANIA</h2>");
    expect(html(editor)).not.toContain("Software House Przykład");
  });

  it("za akapitem dopisuje akapit, a nie punkt listy", () => {
    const editor = open();
    expect(apply(editor, cvLines(editor.state.doc), op(0, "add", [16], "Szachy."))).toBe(true);
    expect(html(editor)).toContain("<p>Żeglarstwo, fotografia.</p><p>Szachy.</p>");
  });

  it("„Rozważany na stanowisko” podmienia tylko swoją linię", () => {
    const editor = open(
      CV.replace(
        "</h1>",
        "</h1><p><strong>Rozważany na stanowisko:</strong> Senior Java Developer</p>",
      ),
    );
    const lines = cvLines(editor.state.doc);
    const target = lines.findIndex((line) => line.text.startsWith("**Rozważany"));
    expect(
      apply(editor, lines, op(0, "considered_for", [target], "**Rozważany na stanowisko:** Senior Java Engineer")),
    ).toBe(true);
    expect(html(editor)).toContain("<p><strong>Rozważany na stanowisko:</strong> Senior Java Engineer</p>");
  });

  it("pogrubia termin wszędzie poza tytułem i nagłówkami; odpogrubia tak samo", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    const bold = { ...op(0, "bold", []), terms: ["Kafka", "Przykładowa"] };
    const result = applyChanges(editor.state, lines, [bold]);
    expect(result).not.toBeNull();
    editor.view.dispatch(result!.transaction);
    expect(html(editor)).toContain("Technologie: Java, <strong>Kafka</strong>");
    // „Przykładowa” stoi tylko w tytule — tytuł nie dostaje pogrubienia.
    expect(html(editor)).toContain("<h1>Dev – Anna Przykładowa</h1>");
    const unbold = { ...op(1, "unbold", []), terms: ["Javie"] };
    expect(apply(editor, cvLines(editor.state.doc), unbold)).toBe(true);
    expect(html(editor)).toContain("Ponad 7 lat doświadczenia w Javie.");
    // Nic do pogrubienia = nic do zrobienia.
    expect(applyChanges(editor.state, cvLines(editor.state.doc), [{ ...op(2, "bold", []), terms: ["Anna"] }])).toBeNull();
    expect(canApply({ ...op(3, "bold", []), terms: [] }, lines)).toBe(false);
  });

  it("podświetlenie zmian żyje w widoku, przesuwa się z pisaniem i znika na żądanie", () => {
    const editor = open();
    const result = applyChanges(editor.state, cvLines(editor.state.doc), [op(0, "replace", [9], "Planowanie sprintów.")]);
    editor.view.dispatch(result!.transaction);
    const saved = html(editor);
    setAssistantHighlight(editor, result!.changed);
    expect(assistantHighlightCount(editor.state)).toBe(1);
    expect(html(editor)).toBe(saved);
    expect(editor.view.dom.querySelector(".cv-assistant-new")?.textContent).toBe("Planowanie sprintów.");
    // Pisanie przed zmianą nie gubi podświetlenia.
    editor.commands.insertContentAt(1, "X");
    expect(editor.view.dom.querySelector(".cv-assistant-new")?.textContent).toBe("Planowanie sprintów.");
    setAssistantHighlight(editor, []);
    expect(assistantHighlightCount(editor.state)).toBe(0);
  });
});

// 16.10.2026, zgłoszenie rekruterki: „ułóż miejsca pracy chronologicznie” —
// asystent przestawia całe stanowiska (`reorder_roles`, linie stanowisk w nowej
// kolejności; kolejność po datach liczy serwer).
describe("kolejność stanowisk", () => {
  it("przestawia całe stanowiska; zmiana punktu jedzie ze swoim stanowiskiem; całość cofa jedno „Cofnij”", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    const before = editor.getHTML();
    const result = applyChanges(editor.state, lines, [op(0, "reorder_roles", [12, 5]), op(1, "replace", [9], "Planowanie sprintów.")]);
    expect(result).not.toBeNull();
    editor.view.dispatch(result!.transaction);
    const html = editor.getHTML();
    expect(html).toContain(
      '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2><p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>' +
        '<p data-cv-section="employer">Software House Przykład · IT</p><ul><li><p>Usługi REST w Java 11.</p></li></ul>' +
        '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>',
    );
    expect(html).toContain("<li><p>Planowanie sprintów.</p></li>");
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java, Kafka</p><h2>ZAINTERESOWANIA</h2>');
    expect(html).toContain(CLAUSE);
    // Podświetlenie: przeredagowany punkt w nowym miejscu i linie przestawionych stanowisk.
    const changed = result!.changed.map((range) => editor.state.doc.textBetween(range.from, range.to));
    expect(changed).toEqual(expect.arrayContaining(["Planowanie sprintów.", "Developer 2017 – 2021", "Senior Developer 2021 – 2024"]));
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("dotyczy tylko linii stanowisk i nie nakłada się, gdy stanowisk jest inna liczba", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    expect(canApply(op(0, "reorder_roles", [12, 5]), lines)).toBe(true);
    expect(canApply(op(0, "reorder_roles", [12, 6]), lines)).toBe(false);
    expect(canApply(op(0, "reorder_roles", [12]), lines)).toBe(false);
    // Stanowisko usunięte w tym samym planie — kolejność nie zgadza się z CV.
    expect(applyChanges(editor.state, lines, [op(0, "reorder_roles", [12, 5]), op(1, "remove_role", [12, 13, 14])])).toBeNull();
  });
});

// Zgłoszenie 23.10.2026: jedna jałowa albo nienakładalna operacja unieważniała
// cały plan, a asystent mówił wtedy „CV zmieniło się w międzyczasie”.
describe("splitPlan — operacje, które nic nie zmieniają albo których edytor nie nałoży", () => {
  const bold = (id: number, terms: string[]): CvPlanOperation => ({ ...op(id, "bold", []), terms });

  it("pogrubienie już pogrubionego słowa i przestawienie punktów z dwóch list wypadają, reszta wchodzi", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    const split = splitPlan(editor.state, lines, [
      bold(0, ["Java 17"]),
      op(1, "reorder", [14, 8]),
      op(2, "replace", [9], "Planowanie sprintów w **Scrum**."),
    ]);
    expect(split.applied.map((item) => item.id)).toEqual([2]);
    expect(split.idle.map((item) => item.id)).toEqual([0]);
    expect(split.unsupported.map((item) => item.id)).toEqual([1]);
    editor.view.dispatch(split.result!.transaction);
    expect(editor.getHTML()).toContain("Planowanie sprintów w <strong>Scrum</strong>.");
  });

  it("nic do zrobienia: bez transakcji", () => {
    const editor = open();
    const split = splitPlan(editor.state, cvLines(editor.state.doc), [bold(0, ["Java 17"]), op(1, "replace", [9], "Udział w planowaniu sprintów.")]);
    expect(split.result).toBeNull();
    expect(split.idle.map((item) => item.id)).toEqual([0, 1]);
  });

  it("pogrubienie słowa z punktu dopisanego wcześniej w tym samym planie wchodzi", () => {
    const editor = open();
    const lines = cvLines(editor.state.doc);
    // „Kafka” stoi w CV tylko w linii technologii — po dopisaniu punktu jest i w nim.
    const split = splitPlan(editor.state, lines, [op(0, "add", [10], "Przetwarzanie zdarzeń w Kafka."), bold(1, ["Kafka"])]);
    expect(split.applied.map((item) => item.id)).toEqual([0, 1]);
    editor.view.dispatch(split.result!.transaction);
    expect(editor.getHTML()).toContain("Przetwarzanie zdarzeń w <strong>Kafka</strong>.");
  });
});
