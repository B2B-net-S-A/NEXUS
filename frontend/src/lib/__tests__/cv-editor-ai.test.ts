import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";

import { acceptStep, clearPending, pendingTarget, selectionTarget, setPending, type CvAiTarget } from "../cv-editor-ai";
import { cvEditorExtensions, loadCvHtml } from "../cv-editor-structure";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową.";
const CV =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad 7 lat doświadczenia w <strong>Javie</strong>.</p></li></ul>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong> i <em>Spring Boot</em>.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java, Kafka</p>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2017 – 2021</p>' +
  '<p data-cv-section="employer">Software House Przykład · IT</p>' +
  "<ul><li><p>Usługi REST w Java 11.</p></li></ul>" +
  "<p>Zwykły akapit z twardym<br>łamaniem wiersza.</p>" +
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

const editors: Editor[] = [];

function open(): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, CV);
  editors.push(editor);
  return editor;
}

/** Zaznacza `text` (pierwsze wystąpienie; może przechodzić przez znaczniki w jednym bloku). */
function select(editor: Editor, text: string, endText = text): void {
  const find = (needle: string, end: boolean): number => {
    let at = -1;
    editor.state.doc.descendants((node, position) => {
      if (at >= 0 || !node.isTextblock) return at < 0;
      const offset = node.textContent.indexOf(needle);
      if (offset >= 0) at = position + 1 + offset + (end ? needle.length : 0);
      return false;
    });
    expect(at, `brak tekstu „${needle}”`).toBeGreaterThan(0);
    return at;
  };
  editor.commands.setTextSelection({ from: find(text, false), to: find(endText, true) });
}

function target(editor: Editor): CvAiTarget {
  const found = selectionTarget(editor.state);
  if (!found.ok) throw new Error(`zaznaczenie odrzucone: ${found.reason}`);
  return found.target;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("zaznaczenie → żądanie do AI", () => {
  it("fragment niesie pogrubienie jako **tekst**, a kontekst to cały punkt i jego stanowisko", () => {
    const editor = open();
    select(editor, "usług w Java 17 i");
    const found = target(editor);
    expect(found.fragment).toBe("usług w **Java 17** i");
    expect(found.blockText).toBe("Rozwój usług w **Java 17** i Spring Boot.");
    expect(found.blockKind).toBe("li");
    expect(found.section).toBe("experience");
    expect(found.role).toEqual({
      title: "Senior Developer 2021 – 2024",
      employer: "Bank Przykładowy · Bankowość",
      points: ["Przeglądy kodu."],
    });
  });

  it("fragment w drugiej roli dostaje jej stanowisko, a poza doświadczeniem — żadnego", () => {
    const editor = open();
    select(editor, "Usługi REST");
    expect(target(editor).role?.title).toBe("Developer 2017 – 2021");
    select(editor, "7 lat doświadczenia");
    const why = target(editor);
    expect(why.role).toBeUndefined();
    expect(why.section).toBe("why_points");
  });

  it("odstępy na brzegach zaznaczenia nie wchodzą do fragmentu ani do zakresu", () => {
    const editor = open();
    select(editor, " kodu");
    const found = target(editor);
    expect(found.fragment).toBe("kodu");
    expect(editor.state.doc.textBetween(found.from, found.to)).toBe("kodu");
  });

  it.each([
    ["dwa punkty", "Spring Boot.", "Przeglądy", /jednym akapicie albo punkcie/],
    ["nagłówek", "DOŚWIADCZENIE", "DOŚWIADCZENIE", /Nagłówk/],
    ["stanowisko", "Senior Developer", "Senior Developer", /popraw ręcznie/],
    ["firma", "Bank Przykładowy", "Bank Przykładowy", /popraw ręcznie/],
    ["technologie", "Java, Kafka", "Java, Kafka", /popraw ręcznie/],
    ["łamanie wiersza", "twardym", "łamaniem", /łamanie wiersza/],
    ["za krótkie", "RE", "RE", /kilka znaków/],
  ])("AI wyłączone z powodem: %s", (_name, from, to, reason) => {
    const editor = open();
    select(editor, from, to);
    const found = selectionTarget(editor.state);
    expect(found.ok).toBe(false);
    if (!found.ok) expect(found.reason).toMatch(reason);
  });

  it("klauzula zgody i puste zaznaczenie nie pokazują AI wcale", () => {
    const editor = open();
    select(editor, "Wyrażam zgodę");
    expect(selectionTarget(editor.state)).toEqual({ ok: false, reason: null, hidden: true });
    editor.commands.setTextSelection(5);
    expect(selectionTarget(editor.state)).toEqual({ ok: false, reason: null, hidden: true });
    editor.commands.selectAll();
    const all = selectionTarget(editor.state);
    expect(all.ok).toBe(false);
  });

  it("zaznaczenie dłuższe niż limit mówi, ile wolno", () => {
    const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
    editors.push(editor);
    loadCvHtml(editor, `<p>${"słowo ".repeat(260)}</p>`);
    editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
    const found = selectionTarget(editor.state);
    expect(found.ok).toBe(false);
    if (!found.ok) expect(found.reason).toMatch(/1200/);
  });
});

describe("zakres czekający na propozycję", () => {
  it("to dekoracja: nie ma jej w zapisie, w historii ani w zdarzeniu „update”", () => {
    const editor = open();
    const updates = vi.fn();
    editor.on("update", updates);
    const saved = editor.getHTML();
    select(editor, "Przeglądy kodu");
    setPending(editor, target(editor));
    expect(editor.view.dom.querySelector(".cv-ai-pending")?.textContent).toBe("Przeglądy kodu");
    expect(editor.getHTML()).toBe(saved);
    expect(updates).not.toHaveBeenCalled();
    expect(editor.can().undo()).toBe(false);
    clearPending(editor);
    expect(editor.view.dom.querySelector(".cv-ai-pending")).toBeNull();
    expect(pendingTarget(editor.state)).toBeNull();
  });

  it("jedzie z tekstem, gdy rekruter pisze gdzie indziej, i gaśnie, gdy zmieni sam fragment", () => {
    const editor = open();
    select(editor, "Przeglądy kodu");
    setPending(editor, target(editor));
    editor.commands.insertContentAt(2, "X");
    const moved = pendingTarget(editor.state)!;
    expect(editor.state.doc.textBetween(moved.from, moved.to)).toBe("Przeglądy kodu");

    editor.commands.insertContentAt(moved.from + 3, "!");
    expect(pendingTarget(editor.state)).toBeNull();
    expect(editor.view.dom.querySelector(".cv-ai-pending")).toBeNull();
  });

  it("przeżywa ponowne wczytanie tej samej treści (nowy szkic), a innej — nie", () => {
    const editor = open();
    select(editor, "Przeglądy kodu");
    setPending(editor, target(editor));
    loadCvHtml(editor, editor.getHTML());
    const kept = pendingTarget(editor.state)!;
    expect(editor.state.doc.textBetween(kept.from, kept.to)).toBe("Przeglądy kodu");
    loadCvHtml(editor, editor.getHTML().replace("Przeglądy kodu", "Code review"));
    expect(pendingTarget(editor.state)).toBeNull();
  });
});

describe("przyjęcie propozycji", () => {
  it("zamienia dokładnie zaznaczony zakres, z pogrubieniem z zapisu **tekst**", () => {
    const editor = open();
    select(editor, "usług w Java 17 i");
    setPending(editor, target(editor));
    const step = acceptStep(editor.state, "mikroserwisów w **Java 17** oraz **Kafka** i");
    editor.view.dispatch(step!.transaction);
    expect(editor.getHTML()).toContain(
      "<li><p>Rozwój mikroserwisów w <strong>Java 17</strong> oraz <strong>Kafka</strong> i <em>Spring Boot</em>.</p></li>",
    );
    expect(editor.state.doc.textBetween(step!.changed.from, step!.changed.to)).toBe("mikroserwisów w Java 17 oraz Kafka i");
    expect(pendingTarget(editor.state)).toBeNull();
  });

  it("znacznik inny niż pogrubienie, który obejmował cały fragment, zostaje", () => {
    const editor = open();
    select(editor, "Spring Boot");
    setPending(editor, target(editor));
    editor.view.dispatch(acceptStep(editor.state, "Spring **Boot** 3")!.transaction);
    expect(editor.getHTML()).toContain("<em>Spring </em><strong><em>Boot</em></strong><em> 3</em>");
  });

  it("jedno „Cofnij” zdejmuje propozycję i nie zabiera tekstu wpisanego tuż przed nią", () => {
    const editor = open();
    editor.commands.insertContentAt(2, "X");
    const typed = editor.getHTML();
    select(editor, "Przeglądy kodu");
    setPending(editor, target(editor));
    editor.view.dispatch(acceptStep(editor.state, "Code review")!.transaction);
    expect(editor.getHTML()).toContain("Code review");
    editor.commands.undo();
    expect(editor.getHTML()).toBe(typed);
  });

  it("bez zakresu, po zmianie fragmentu albo z pustą propozycją nie ma czego nakładać", () => {
    const editor = open();
    expect(acceptStep(editor.state, "tekst")).toBeNull();
    select(editor, "Przeglądy kodu");
    setPending(editor, target(editor));
    expect(acceptStep(editor.state, "  ")).toBeNull();
    editor.commands.insertContentAt(pendingTarget(editor.state)!.from + 2, "!");
    expect(acceptStep(editor.state, "Code review")).toBeNull();
  });

  it("klauzula zgody zostaje jedna i na końcu", () => {
    const editor = open();
    select(editor, "Usługi REST w Java 11");
    setPending(editor, target(editor));
    editor.view.dispatch(acceptStep(editor.state, "REST services in Java 11")!.transaction);
    expect(editor.getHTML().split(CLAUSE)).toHaveLength(2);
    expect(editor.getHTML().endsWith(`${CLAUSE}</p>`)).toBe(true);
  });
});
