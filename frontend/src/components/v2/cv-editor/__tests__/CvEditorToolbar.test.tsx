import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { afterEach, expect, it } from "vitest";

import { cvOutline } from "@/lib/cv-editor-blocks";
import { cvEditorExtensions } from "@/lib/cv-editor-structure";

import { CvEditorToolbar } from "../CvEditorToolbar";

const CV =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy</p><ul><li><p>Usługi płatnicze.</p></li></ul>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2018 – 2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>' +
  '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';

const editors: Editor[] = [];

function mount(): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: CV });
  editors.push(editor);
  render(<CvEditorToolbar editor={editor} language="pl" />);
  return editor;
}

function caretIn(editor: Editor, text: string): void {
  let at = -1;
  editor.state.doc.descendants((node, position) => {
    const offset = node.isText ? (node.text ?? "").indexOf(text) : -1;
    if (at < 0 && offset >= 0) at = position + offset + 1;
  });
  act(() => {
    editor.commands.setTextSelection(at);
  });
}

const button = (name: string) => screen.getByRole("button", { name });
const roles = (editor: Editor) => cvOutline(editor.state.doc).roles.map((role) => role.title);

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

it("poza stanowiskiem nie pokazuje jego przycisków, a po wczytaniu nie ma czego cofać", () => {
  mount();
  expect(button("Cofnij")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Usuń stanowisko" })).toBeNull();
});

it("przenosi stanowisko pod kursorem i wyłącza kierunek, w którym nie ma sąsiada", () => {
  const editor = mount();
  caretIn(editor, "Bank Przykładowy");
  expect(screen.getByText("Senior Developer 2021 – 2024")).toBeInTheDocument();
  expect(button("Przenieś stanowisko wyżej")).toBeDisabled();
  fireEvent.click(button("Przenieś stanowisko niżej"));
  expect(roles(editor)).toEqual(["Developer 2018 – 2021", "Senior Developer 2021 – 2024"]);
  expect(button("Przenieś stanowisko niżej")).toBeDisabled();
  expect(button("Cofnij")).toBeEnabled();
  fireEvent.click(button("Cofnij"));
  expect(roles(editor)).toEqual(["Senior Developer 2021 – 2024", "Developer 2018 – 2021"]);
});

it("powiela stanowisko, a usuwa dopiero po potwierdzeniu", async () => {
  const editor = mount();
  caretIn(editor, "Software House");
  fireEvent.click(button("Powiel stanowisko"));
  expect(roles(editor)).toHaveLength(3);

  fireEvent.click(button("Usuń stanowisko"));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Usunąć stanowisko?")).toBeInTheDocument();
  expect(roles(editor)).toHaveLength(3);
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń stanowisko" }));
  await screen.findByRole("button", { name: "Powiel stanowisko" });
  expect(roles(editor)).toHaveLength(2);
  expect(editor.getHTML()).toContain("Wyrażam zgodę");
});

it("typ akapitu jest wyłączony w liście i na klauzuli zgody, a lista — na oznaczonym akapicie", () => {
  const editor = mount();
  caretIn(editor, "Usługi płatnicze.");
  expect(button("Typ akapitu: —")).toBeDisabled();
  expect(button("Lista punktowana")).toBeEnabled();
  caretIn(editor, "Bank Przykładowy");
  expect(button("Typ akapitu: Firma")).toBeEnabled();
  expect(button("Lista punktowana")).toBeDisabled();
  caretIn(editor, "Wyrażam zgodę");
  expect(button("Typ akapitu: Zwykły tekst")).toBeDisabled();
});

it("„Typ akapitu” oznacza akapit, a „Dodaj” wstawia stanowisko z polami do wypełnienia", async () => {
  const editor = mount();
  caretIn(editor, "Software House");
  fireEvent.keyDown(button("Typ akapitu: Firma"), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitemradio", { name: "Zwykły tekst" }));
  expect(editor.getHTML()).toContain("<p>Software House Przykład</p>");

  fireEvent.keyDown(button("Dodaj"), { key: "ArrowDown" });
  expect(await screen.findByRole("menuitem", { name: "Punkt" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("menuitem", { name: "Stanowisko" }));
  expect(roles(editor)).toEqual([
    "Senior Developer 2021 – 2024",
    "Developer 2018 – 2021",
    "[Stanowisko] [MM.RRRR – MM.RRRR]",
  ]);
});

it("pogrubienie i lista działają na zaznaczeniu, wyłączony pasek nie robi nic", () => {
  const editor = mount();
  caretIn(editor, "Usługi płatnicze.");
  act(() => {
    editor.commands.selectParentNode();
  });
  fireEvent.click(button("Pogrubienie"));
  expect(editor.getHTML()).toContain("<strong>Usługi płatnicze.</strong>");
  fireEvent.click(button("Lista punktowana"));
  expect(editor.getHTML()).toContain("<p><strong>Usługi płatnicze.</strong></p>");
  expect(editor.getHTML()).not.toContain("<ul>");
});

it("menu domykane po zamknięciu edytora nie sięga do nieistniejącego widoku", async () => {
  const editor = mount();
  fireEvent.keyDown(button("Dodaj"), { key: "ArrowDown" });
  const item = await screen.findByRole("menuitem", { name: "Język" });
  act(() => editor.destroy());
  // Radix oddaje fokus po zamknięciu menu; nieobsłużony wyjątek wywraca bieg vitest.
  fireEvent.keyDown(item, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menuitem", { name: "Język" })).toBeNull());
});
