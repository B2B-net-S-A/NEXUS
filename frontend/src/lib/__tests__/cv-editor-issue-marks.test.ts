import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";

import { clearIssueFocus, issueMarkCount, setIssueMarks, showIssueInCv } from "../cv-editor-issue-marks";
import { issueMarks, locateTarget } from "../cv-editor-issues";
import { cvEditorExtensions, loadCvHtml } from "../cv-editor-structure";
import type { QcCheck } from "../api/cvQc";

const CV =
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2020 – 2022</p>' +
  "<ul><li><p>Usługi w Kafka i AWS.</p></li></ul>" +
  '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';

const CHECKS: QcCheck[] = [
  {
    key: "no_unsupported",
    label: "Zgodność z oryginałem",
    severity: "blocking",
    status: "fail",
    summary: null,
    items: [{ term: "AWS", fix: "remove_term" }],
  },
  {
    key: "must_in_roles",
    label: "Wymagania w rolach",
    severity: "warning",
    status: "fail",
    summary: null,
    items: [{ requirement: "Java", role: "Developer", role_index: 0 }],
  },
];

const editors: Editor[] = [];

function open(): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, CV);
  editors.push(editor);
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("znaczniki uwag w edytorze", () => {
  it("rysują się w widoku, a nie w zapisywanej treści ani w historii cofania", () => {
    const editor = open();
    const updates = vi.fn();
    editor.on("update", updates);
    const saved = editor.getHTML();
    setIssueMarks(editor, issueMarks(editor.state.doc, CHECKS, []));

    const term = editor.view.dom.querySelector(".cv-issue-term");
    expect(term?.textContent).toBe("AWS");
    expect(term?.className).toContain("cv-issue--blocking");
    const block = editor.view.dom.querySelector(".cv-issue-block");
    expect(block?.textContent).toBe("Developer 2020 – 2022");
    expect(block?.className).toContain("cv-issue--note");

    expect(editor.getHTML()).toBe(saved);
    expect(editor.getHTML()).not.toContain("cv-issue");
    // Dekoracja to nie edycja: autozapis nie rusza, „Cofnij” nie ma czego cofać.
    expect(updates).not.toHaveBeenCalled();
    expect(editor.can().undo()).toBe(false);
  });

  it("znacznik jedzie z tekstem, gdy rekruter pisze wyżej", () => {
    const editor = open();
    setIssueMarks(editor, issueMarks(editor.state.doc, CHECKS, []));
    editor.commands.insertContentAt(1, "NOWE ");
    expect(editor.view.dom.querySelector(".cv-issue-term")?.textContent).toBe("AWS");
    expect(issueMarkCount(editor).marks).toBe(2);
  });

  it("pusta lista zdejmuje znaczniki", () => {
    const editor = open();
    setIssueMarks(editor, issueMarks(editor.state.doc, CHECKS, []));
    setIssueMarks(editor, []);
    expect(editor.view.dom.querySelector("[class*=cv-issue]")).toBeNull();
  });

  it("„Pokaż w CV” wyróżnia miejsce, stawia kursor i przewija, bez zmiany treści", () => {
    const editor = open();
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const updates = vi.fn();
    editor.on("update", updates);
    const range = locateTarget(editor.state.doc, { kind: "term", term: "AWS", roleIndex: null, label: null })!;
    showIssueInCv(editor, range);

    expect(editor.view.dom.querySelector(".cv-issue-focus")?.textContent).toBe("AWS");
    expect(editor.state.selection.from).toBe(range.from);
    expect(scrolled).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
    expect(updates).not.toHaveBeenCalled();

    clearIssueFocus(editor);
    expect(editor.view.dom.querySelector(".cv-issue-focus")).toBeNull();
  });

  it("wyróżnienie gaśnie przy pierwszej zmianie treści, a zakres spoza dokumentu jest pomijany", () => {
    const editor = open();
    const role = locateTarget(editor.state.doc, { kind: "role", roleIndex: 0, label: null })!;
    showIssueInCv(editor, role);
    expect(issueMarkCount(editor).focus).toBe(1);
    editor.commands.insertContentAt(1, "x");
    expect(issueMarkCount(editor).focus).toBe(0);

    showIssueInCv(editor, { from: 5, to: 99_999, block: false });
    setIssueMarks(editor, [{ from: 99_990, to: 99_999, block: true, tone: "note" }]);
    expect(issueMarkCount(editor)).toEqual({ marks: 0, focus: 0 });
  });
});
