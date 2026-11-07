import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";

import { appliedLabel } from "../cv-editor-issues";
import { languagePart, quickFixes } from "../cv-editor-quick-fixes";
import { cvEditorExtensions } from "../cv-editor-structure";

const CLAUSE = "I hereby consent to the processing · of my personal data by Example Company.";
const CV =
  "<h1>AML Analyst – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="why_points">WHY OUR CANDIDATE?</h2>' +
  "<ul><li><p>Junior AML Specialist at Example Bank – analysed transaction alerts.</p></li></ul>" +
  '<h2 data-cv-section="skills">SKILLS</h2><p>Java · Kotlin</p>' +
  '<h2 data-cv-section="languages">LANGUAGES</h2>' +
  "<p>English - advanced · Russian (basic)</p>" +
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

const editors: Editor[] = [];

function open(content = CV): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

describe("quickFixes", () => {
  it("finds languages separated by „·” in one paragraph — and only there", () => {
    const editor = open();
    const fixes = quickFixes(editor.state.doc);
    // „Java · Kotlin” w umiejętnościach i punkt podsumowania zostają bez wiersza.
    expect(fixes).toHaveLength(1);
    const [languages] = fixes;
    expect(languages).toMatchObject({
      action: "languages_lines",
      count: 1,
      before: "English - advanced · Russian (basic)",
      after: ["English – advanced", "Russian – basic"],
    });
    expect(editor.state.doc.textBetween(languages.where.from, languages.where.to)).toBe(
      "English - advanced · Russian (basic)",
    );
  });

  it("recognises the section by title in a CV uploaded from Word (no markers)", () => {
    const editor = open("<h2>Języki</h2><p>Polski · Angielski: C1</p>");
    expect(quickFixes(editor.state.doc)).toMatchObject([{ after: ["Polski", "Angielski – C1"] }]);
  });

  it("has nothing to do when every language already has its own line", () => {
    const editor = open('<h2 data-cv-section="languages">LANGUAGES</h2><p>English – C1</p><p>Polish – native</p>');
    expect(quickFixes(editor.state.doc)).toEqual([]);
  });

  it("never touches the consent clause", () => {
    const editor = open('<h2 data-cv-section="languages">LANGUAGES</h2>' + `<p data-cv-section="rodo">${CLAUSE}</p>`);
    expect(quickFixes(editor.state.doc)).toEqual([]);
  });
});

describe("languagePart", () => {
  it.each([
    ["English - B2", "English – B2"],
    ["English — B2", "English – B2"],
    ["English (B2)", "English – B2"],
    ["Polish: native", "Polish – native"],
    // Nic nie dopisuje: bez poziomu zostaje sam język.
    ["  Polski  ", "Polski"],
  ])("%s → %s", (input, expected) => {
    expect(languagePart(input)).toBe(expected);
  });

  it("only fixes the dash when the paragraph has formatting (server does the same)", () => {
    expect(languagePart(" English (B2) ", false)).toBe("English (B2)");
    expect(languagePart("English - B2", false)).toBe("English – B2");
  });
});

it("names the applied quick fix in „Poprawione”", () => {
  expect(appliedLabel({ action: "languages_lines" }, [], [])).toBe("Języki w osobnych liniach");
});
