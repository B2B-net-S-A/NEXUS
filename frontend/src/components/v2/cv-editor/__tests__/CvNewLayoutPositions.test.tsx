import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { CvEditorSection } from "@/lib/cv-editor-section";
import { allRoleFields } from "@/lib/cv-new-layout-form";

import { CvNewLayoutPositions } from "../CvNewLayoutPositions";

const CV =
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – obecnie</p>' +
  '<p data-cv-section="employer">Bank Przykładowy S.A. · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Mikroserwisy płatności.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 17, <strong>Kafka</strong></p>' +
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Usługi REST.</p></li></ul>" +
  '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

function Harness({ editor, disabled = false }: { editor: Editor; disabled?: boolean }) {
  const [selected, setSelected] = useState(0);
  return (
    <CvNewLayoutPositions editor={editor} lang="pl" disabled={disabled} selected={selected} onSelect={setSelected} />
  );
}

function renderPositions(disabled = false) {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content: CV });
  editors.push(editor);
  render(<Harness editor={editor} disabled={disabled} />);
  return editor;
}

function form() {
  return within(screen.getByTestId("cv-new-role-form"));
}

describe("Stanowiska", () => {
  it("lista stanowisk z CV: firma, stanowisko, okres", () => {
    renderPositions();
    expect(screen.getByRole("heading", { name: "Stanowiska (2)" })).toBeInTheDocument();
    const list = within(screen.getByRole("list"));
    expect(list.getByRole("button", { name: /Bank Przykładowy S\.A\..*Senior Java Developer.*03\.2021 – obecnie/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(list.getByRole("button", { name: /Software House Przykład.*Java Developer/ })).toBeInTheDocument();
  });

  it("formularz wybranego stanowiska pisze do jego akapitów w dokumencie", () => {
    const editor = renderPositions();
    fireEvent.click(screen.getByRole("button", { name: /^Software House Przykład/ }));
    fireEvent.change(form().getByLabelText("Firma"), { target: { value: "Software House Przykład sp. z o.o." } });
    fireEvent.change(form().getByLabelText("Stanowisko"), { target: { value: "Programista Java" } });
    fireEvent.change(form().getByLabelText("Okres do"), { target: { value: "03.2021" } });
    fireEvent.change(form().getByLabelText("Punkt 1 zakresu zadań"), { target: { value: "Usługi REST w Javie 11." } });
    fireEvent.change(form().getByLabelText("Technologie"), { target: { value: "Java 11, Spring Boot" } });
    const html = editor.getHTML();
    expect(html).toContain('<p data-cv-section="role"><strong>Programista Java</strong> 01.2017 – 03.2021</p>');
    expect(html).toContain('<p data-cv-section="employer">Software House Przykład sp. z o.o.</p>');
    expect(html).toContain("<li><p>Usługi REST w Javie 11.</p></li>");
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java 11, Spring Boot</p>');
    // Pierwsze stanowisko nietknięte.
    expect(html).toContain('<p data-cv-section="technologies">Technologie: Java 17, <strong>Kafka</strong></p>');
  });

  it("czas stanowiska obok okresu", () => {
    renderPositions();
    fireEvent.click(screen.getByRole("button", { name: /^Software House Przykład/ }));
    expect(form().getByText("(4 lata 2 mies.)")).toBeInTheDocument();
  });

  it("przestawienie stanowiska w dół zamienia całe zakresy i zostawia je wybrane", () => {
    const editor = renderPositions();
    fireEvent.click(screen.getByRole("button", { name: "Przesuń niżej: Bank Przykładowy S.A." }));
    expect(allRoleFields(editor.state.doc).map((role) => role.title)).toEqual(["Java Developer", "Senior Java Developer"]);
    expect(screen.getByRole("button", { name: /Bank Przykładowy S\.A\..*Senior/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Przesuń niżej: Bank Przykładowy S.A." })).toBeDisabled();
    // „Cofnij” w edytorze przywraca kolejność.
    editor.commands.undo();
    expect(allRoleFields(editor.state.doc)[0].title).toBe("Senior Java Developer");
  });

  it("punkt zakresu zadań: dopisanie i usunięcie", () => {
    const editor = renderPositions();
    fireEvent.click(form().getByRole("button", { name: "Punkt" }));
    expect(allRoleFields(editor.state.doc)[0].duties).toEqual(["Mikroserwisy płatności.", "Przeglądy kodu.", ""]);
    fireEvent.click(form().getByRole("button", { name: "Usuń punkt 1" }));
    expect(allRoleFields(editor.state.doc)[0].duties).toEqual(["Przeglądy kodu.", ""]);
  });

  it("„Dodaj” wstawia nowe stanowisko za wybranym z polami do wypełnienia", () => {
    const editor = renderPositions();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    expect(allRoleFields(editor.state.doc).map((role) => role.title)).toEqual([
      "Senior Java Developer",
      "[Stanowisko]",
      "Java Developer",
    ]);
    expect(form().getByLabelText("Stanowisko")).toHaveValue("[Stanowisko]");
  });

  it("Ctrl+Z w polu cofa w historii edytora", () => {
    const editor = renderPositions();
    const company = form().getByLabelText("Firma");
    fireEvent.change(company, { target: { value: "Inna firma" } });
    fireEvent.keyDown(company, { key: "z", ctrlKey: true });
    expect(allRoleFields(editor.state.doc)[0].company).toBe("Bank Przykładowy S.A. · Bankowość");
  });

  it("zablokowany formularz nie przestawia ani nie edytuje", () => {
    const dispatch = vi.fn();
    const editor = renderPositions(true);
    editor.view.dispatch = dispatch;
    expect(screen.getByRole("button", { name: "Dodaj" })).toBeDisabled();
    expect(form().getByLabelText("Firma")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Przesuń niżej: Bank Przykładowy S.A." })).toBeDisabled();
    expect(dispatch).not.toHaveBeenCalled();
  });
});
