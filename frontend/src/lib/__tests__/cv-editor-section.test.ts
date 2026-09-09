import { expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { CvEditorSection } from "../cv-editor-section";

it("keeps consent formatting and user emphasis through edits and reloads", () => {
  const options = { extensions: [StarterKit, CvEditorSection] };
  const editor = new Editor({...options, content: '<p>Alpha <strong>Python</strong></p><p class="rodo">Treść zgody</p>'});
  editor.commands.insertContentAt(1, "Poprawka ");
  const html = editor.getHTML();
  expect(html).toContain("<strong>Python</strong>");
  expect(html).toContain('data-cv-section="rodo"');
  const reopened = new Editor({...options, content: html});
  expect(reopened.getHTML()).toBe(html);
  expect(reopened.getText()).toContain("Treść zgody");
  editor.destroy();
  reopened.destroy();
});
