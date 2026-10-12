import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { DOMParser } from "@tiptap/pm/model";

import { cvOutline } from "../cv-editor-blocks";
import { cvEditorExtensions, loadCvHtml } from "../cv-editor-structure";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową.";
const RODO = `<p data-cv-section="rodo" style="font-size: 8pt; line-height: 1.35">${CLAUSE}</p>`;
const BODY =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Dev</strong> 2020 – 2022</p>' +
  '<p data-cv-section="employer">Acme</p><ul><li><p>Usługi REST.</p></li></ul>';
const CV = BODY + RODO;

const TAIL_CV = `${BODY}<p>Ostatni akapit.</p>${RODO}`;

const editors: Editor[] = [];

function open(content: string): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content });
  editors.push(editor);
  return editor;
}

function positionOf(editor: Editor, text: string): number {
  let at = -1;
  editor.state.doc.descendants((node, position) => {
    const offset = node.isText ? (node.text ?? "").indexOf(text) : -1;
    if (at < 0 && offset >= 0) at = position + offset;
  });
  expect(at, `brak tekstu „${text}”`).toBeGreaterThanOrEqual(0);
  return at;
}

/** Klawisz Delete obsługuje model ProseMirrora, nie przeglądarka — `contenteditable` go nie zatrzyma. */
function pressKey(editor: Editor, key: string, keyCode: number): void {
  editor.view.dom.dispatchEvent(
    new KeyboardEvent("keydown", { key, keyCode, bubbles: true, cancelable: true }),
  );
}

function pressDelete(editor: Editor): void {
  pressKey(editor, "Delete", 46);
}

function clauses(editor: Editor): number {
  return editor.getHTML().split(CLAUSE).length - 1;
}

/** Akapit klauzuli tak, jak zapisuje go edytor (przeglądarka normalizuje `style`). */
function savedClause(content: string): string {
  const html = open(content).getHTML();
  return html.slice(html.lastIndexOf("<p"));
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("klauzula zgody jest stała", () => {
  it("wraca po „zaznacz wszystko i usuń”", () => {
    const editor = open(CV);
    editor.chain().selectAll().deleteSelection().run();
    expect(editor.getHTML()).toBe(`<p></p>${savedClause(CV)}`);
  });

  it("cofa wpisany w nią tekst i nie daje jej skasować", () => {
    const editor = open(CV);
    const at = positionOf(editor, "Wyrażam");
    editor.chain().setTextSelection(at + 3).insertContent("XYZ").run();
    expect(editor.getHTML()).toBe(open(CV).getHTML());
    editor.chain().setTextSelection({ from: at, to: at + CLAUSE.length }).deleteSelection().run();
    expect(editor.getHTML()).toBe(open(CV).getHTML());
  });

  it("Delete na końcu ostatniego punktu nie wciąga jej do listy", () => {
    const editor = open(CV);
    const before = editor.getHTML();
    editor.commands.setTextSelection(positionOf(editor, "Usługi REST.") + "Usługi REST.".length);
    pressDelete(editor);
    expect(editor.getHTML()).toBe(before);
  });

  it("Delete na końcu ostatniego akapitu nie dokleja jej do niego", () => {
    const editor = open(TAIL_CV);
    const before = editor.getHTML();
    editor.commands.setTextSelection(positionOf(editor, "Ostatni akapit.") + "Ostatni akapit.".length);
    pressDelete(editor);
    expect(editor.getHTML()).toBe(before);
    // Następny klawisz działa normalnie — blokada nie zostawia edytora w złym stanie.
    editor.commands.insertContent(" Dopisek.");
    expect(editor.getHTML()).toContain("<p>Ostatni akapit. Dopisek.</p>");
    expect(clauses(editor)).toBe(1);
  });

  it("Backspace na jej początku nie dokleja jej do poprzedniego punktu ani akapitu", () => {
    // W liście Tiptap przenosi treść przez „usuń i wstaw” — mapowanie pozycji
    // tego nie pokazuje, więc pilnuje tego naprawa, nie filtr.
    for (const content of [CV, TAIL_CV]) {
      const editor = open(content);
      const before = editor.getHTML();
      editor.commands.setTextSelection(positionOf(editor, "Wyrażam"));
      pressKey(editor, "Backspace", 8);
      expect(editor.getHTML()).toBe(before);
    }
  });

  it("usunięcie zaznaczenia sięgającego w głąb klauzuli nie zostawia jej reszty w treści", () => {
    const editor = open(TAIL_CV);
    const before = editor.getHTML();
    const from = positionOf(editor, "Ostatni akapit.") + 3;
    const to = positionOf(editor, "Wyrażam") + 20;
    editor.chain().setTextSelection({ from, to }).deleteSelection().run();
    expect(editor.getHTML()).toBe(before);
  });

  it("zaznaczenie od środka akapitu do końca dokumentu kasuje treść, a klauzula zostaje", () => {
    const editor = open(TAIL_CV);
    const from = positionOf(editor, "Ostatni akapit.") + 3;
    const to = positionOf(editor, "Wyrażam") + CLAUSE.length;
    editor.chain().setTextSelection({ from, to }).deleteSelection().run();
    expect(editor.getHTML()).toBe(`${open(BODY).getHTML()}<p>Ost</p>${savedClause(CV)}`);
  });

  it("zostaje ostatnia, gdy ktoś dopisze akapit pod nią", () => {
    const editor = open(CV);
    const end = editor.state.doc.content.size;
    editor.commands.insertContentAt(end, "<p>Dopisek pod klauzulą</p>");
    const { blocks, rodo } = cvOutline(editor.state.doc);
    expect(rodo).toBe(blocks[blocks.length - 1]);
    expect(editor.getHTML()).toContain("<p>Dopisek pod klauzulą</p>");
    expect(clauses(editor)).toBe(1);
  });

  it("usuwa klauzulę wklejoną drugi raz razem z treścią innego CV", () => {
    const editor = open(CV);
    editor.commands.insertContentAt(1, `<p>Wklejone</p>${RODO}<p data-cv-section="rodo">Inna zgoda</p>`);
    expect(clauses(editor)).toBe(1);
    expect(editor.getHTML()).not.toContain("Inna zgoda");
    expect(editor.getHTML()).toContain("Wklejone");
  });

  it("usuwa jej kopię wklejoną w głąb listy, razem z pustym punktem", () => {
    const editor = open(CV);
    const inList = positionOf(editor, "Usługi REST.") + 3;
    editor.commands.insertContentAt(inList, `<p>Wklejone</p>${RODO}`);
    expect(clauses(editor)).toBe(1);
    expect(editor.getHTML()).toContain("Wklejone");

    const lone = open(`${BODY}<ul><li><p>${CLAUSE}</p></li></ul>${RODO}`);
    lone.commands.insertContentAt(1, "<p>x</p>");
    expect(clauses(lone)).toBe(1);
    expect(lone.getHTML()).toBe(`<p>x</p>${open(BODY).getHTML()}${savedClause(CV)}`);
  });

  it("wklejona ze schowka klauzula nie zabiera reszty akapitu, z którą się skleiła", () => {
    // Schowek daje wycinek otwarty z obu stron: ostatni wklejony akapit
    // (klauzula z innego CV) skleja się z końcem akapitu, w który wklejono.
    const editor = open(`${BODY}<p>Pierwsza połowa. Druga połowa.</p>${RODO}`);
    editor.commands.setTextSelection(positionOf(editor, "Druga połowa."));
    const clipboard = document.createElement("div");
    clipboard.innerHTML = `<p>Wklejone</p>${RODO}`;
    const slice = DOMParser.fromSchema(editor.schema).parseSlice(clipboard);
    editor.view.dispatch(editor.state.tr.replaceSelection(slice));
    expect(editor.getHTML()).toBe(
      `${open(BODY).getHTML()}<p>Pierwsza połowa. Wklejone</p><p>Druga połowa.</p>${savedClause(CV)}`,
    );
  });

  it("rozpoznaje klauzulę bez znacznika po pierwszych słowach szablonu", () => {
    const legacy = `${BODY}<p>${CLAUSE}</p>`;
    const editor = open(legacy);
    editor.chain().selectAll().deleteSelection().run();
    expect(editor.getHTML()).toBe(`<p></p><p>${CLAUSE}</p>`);
  });

  it("nie dokłada klauzuli do CV, które jej nie ma", () => {
    const editor = open(BODY);
    editor.chain().selectAll().deleteSelection().run();
    expect(editor.getHTML()).toBe("<p></p>");
  });

  it("po cofnięciu zmiany dokument jest taki jak przed nią", () => {
    const editor = open(CV);
    const before = editor.getHTML();
    editor.chain().selectAll().deleteSelection().run();
    const emptied = editor.getHTML();
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
    expect(clauses(editor)).toBe(1);
    // Cofnięcie i ponowienie przechodzą PRZEZ klauzulę — filtr ich nie odrzuca.
    editor.commands.redo();
    expect(editor.getHTML()).toBe(emptied);
  });
});

describe("wczytanie treści", () => {
  it("nie trafia do historii cofania", () => {
    const editor = open("");
    loadCvHtml(editor, CV);
    expect(editor.can().undo()).toBe(false);
    editor.commands.undo();
    expect(editor.getHTML()).toBe(open(CV).getHTML());
  });

  it("podmienia klauzulę na tę z nowej treści", () => {
    const editor = open(CV);
    const other = CLAUSE.replace("Firmę Przykładową", "Inną Firmę");
    loadCvHtml(editor, `<p>Nowe CV</p><p data-cv-section="rodo">${other}</p>`);
    expect(editor.getHTML()).toContain(other);
    expect(clauses(editor)).toBe(0);
    editor.chain().selectAll().deleteSelection().run();
    expect(editor.getHTML()).toContain(other);
  });

  it("nie zgłasza zmiany treści", () => {
    const editor = open("");
    let updates = 0;
    editor.on("update", () => {
      updates += 1;
    });
    loadCvHtml(editor, CV);
    expect(updates).toBe(0);
  });
});

describe("znaczniki struktury", () => {
  it("znika znacznik stanowiska, które trafiło do listy", () => {
    const editor = open(CV);
    editor.chain().setTextSelection(positionOf(editor, " 2020 – 2022") + 2).toggleBulletList().run();
    const html = editor.getHTML();
    expect(html).toContain("<li><p><strong>Dev</strong> 2020 – 2022</p></li>");
    expect(html).not.toContain('data-cv-section="role"');
    expect(html).toContain('data-cv-section="employer"');
  });

  it("dekoracje widoku nie trafiają do zapisywanego HTML-a", () => {
    const editor = open(CV);
    editor.commands.setTextSelection(positionOf(editor, "Acme") + 1);
    const html = editor.getHTML();
    expect(html).toBe(open(CV).getHTML());
    for (const leak of ["cv-rodo-locked", "contenteditable", "data-cv-in", "cv-role-current", "cv-tech-label"]) {
      expect(html).not.toContain(leak);
    }
    // …ale są w widoku: blokada klauzuli, sekcja bloku, stanowisko pod kursorem.
    const view = editor.view.dom.innerHTML;
    expect(view).toContain('class="cv-rodo-locked"');
    expect(view).toContain('contenteditable="false"');
    expect(view).toContain('data-cv-in="experience"');
    expect(view).toContain("cv-role-current");
  });

  it("w widoku pogrubia samą etykietę technologii, jak Word", () => {
    const editor = open(`${BODY}<p data-cv-section="technologies">Technologie: Java 17, Kafka</p>${RODO}`);
    expect(editor.view.dom.innerHTML).toContain('<span class="cv-tech-label">Technologie:</span> Java 17, Kafka');
    expect(editor.getHTML()).toContain('<p data-cv-section="technologies">Technologie: Java 17, Kafka</p>');
  });
});
