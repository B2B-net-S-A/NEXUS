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

it("keeps section and role markers through an actual Tiptap roundtrip", () => {
  const options = {extensions: [StarterKit, CvEditorSection]};
  const input = '<h2 data-cv-section="experience">Doświadczenie</h2><p data-cv-section="role"><b>Engineer</b> 2020–2024</p><ul><li>Python API</li></ul>';
  const editor = new Editor({...options, content: input});
  const output = editor.getHTML();
  expect(output).toContain('data-cv-section="experience"');
  expect(output).toContain('data-cv-section="role"');
  const reopened = new Editor({...options, content: output});
  expect(reopened.getHTML()).toBe(output);
  editor.destroy(); reopened.destroy();
});
