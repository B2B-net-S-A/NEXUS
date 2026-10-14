import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { afterEach, expect, it, vi } from "vitest";

import { cvOutline } from "@/lib/cv-editor-blocks";
import { cvEditorExtensions } from "@/lib/cv-editor-structure";

import { CvEditorToolbar, type CvEditorToolbarProps } from "../CvEditorToolbar";

const CV =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy</p><ul><li><p>Usługi płatnicze.</p></li></ul>' +
  '<p data-cv-section="role"><strong>Developer</strong> 2018 – 2021</p>' +
  '<p data-cv-section="employer">Software House Przykład</p>' +
  '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>';

const editors: Editor[] = [];

function mount(
  defaultAlign?: "justify" | "left",
  content = CV,
  extra: Partial<CvEditorToolbarProps> = {},
): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content });
  editors.push(editor);
  render(<CvEditorToolbar editor={editor} language="pl" defaultAlign={defaultAlign} {...extra} />);
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

/** „Więcej” (Edytor CV 3, PR 3): reszta poleceń paska. Otwarte menu zasłania stronę. */
async function openMore(): Promise<HTMLElement> {
  fireEvent.keyDown(button("Więcej"), { key: "ArrowDown" });
  return screen.findByRole("menu");
}
async function openSub(name: string | RegExp): Promise<HTMLElement> {
  await openMore();
  const trigger = await screen.findByRole("menuitem", { name });
  fireEvent.keyDown(trigger, { key: "ArrowRight" });
  return trigger;
}
async function closeMenus(): Promise<void> {
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
}
const menuItem = (name: string | RegExp) => screen.findByRole("menuitem", { name });
const isOff = (element: HTMLElement) => element.getAttribute("aria-disabled") === "true";

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

it("poza stanowiskiem „Więcej” nie ma poleceń stanowiska, a po wczytaniu nie ma czego cofać", async () => {
  mount();
  expect(button("Cofnij")).toBeDisabled();
  await openMore();
  expect(screen.queryByRole("menuitem", { name: /^Stanowisko:/ })).toBeNull();
  await closeMenus();
});

it("pasek ma tylko częste polecenia; reszta jest w „Więcej”", async () => {
  mount();
  for (const name of ["Dodaj", "Typ akapitu: Zwykły tekst", "Usuń stanowisko"]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
  await openMore();
  for (const name of ["Dodaj", /^Typ akapitu:/, "Wyjustuj całe CV", "Całe CV do lewej"]) {
    expect(await menuItem(name)).toBeInTheDocument();
  }
  await closeMenus();
});

it("przenosi stanowisko pod kursorem i wyłącza kierunek, w którym nie ma sąsiada", async () => {
  const editor = mount();
  caretIn(editor, "Bank Przykładowy");
  expect((await openSub(/^Stanowisko:/)).textContent).toContain("Senior Developer 2021 – 2024");
  expect(isOff(await menuItem("Przenieś stanowisko wyżej"))).toBe(true);
  fireEvent.click(await menuItem("Przenieś stanowisko niżej"));
  expect(roles(editor)).toEqual(["Developer 2018 – 2021", "Senior Developer 2021 – 2024"]);
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  await openSub(/^Stanowisko:/);
  expect(isOff(await menuItem("Przenieś stanowisko niżej"))).toBe(true);
  await closeMenus();
  expect(button("Cofnij")).toBeEnabled();
  fireEvent.click(button("Cofnij"));
  expect(roles(editor)).toEqual(["Senior Developer 2021 – 2024", "Developer 2018 – 2021"]);
});

it("powiela stanowisko, a usuwa dopiero po potwierdzeniu", async () => {
  const editor = mount();
  caretIn(editor, "Software House");
  await openSub(/^Stanowisko:/);
  fireEvent.click(await menuItem("Powiel stanowisko"));
  expect(roles(editor)).toHaveLength(3);
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

  await openSub(/^Stanowisko:/);
  fireEvent.click(await menuItem("Usuń stanowisko"));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Usunąć stanowisko?")).toBeInTheDocument();
  expect(roles(editor)).toHaveLength(3);
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń stanowisko" }));
  await waitFor(() => expect(roles(editor)).toHaveLength(2));
  expect(editor.getHTML()).toContain("Wyrażam zgodę");
});

it("typ akapitu jest wyłączony w liście i na klauzuli zgody, a lista — na oznaczonym akapicie", async () => {
  const editor = mount();
  caretIn(editor, "Usługi płatnicze.");
  expect(button("Lista punktowana")).toBeEnabled();
  await openMore();
  expect(isOff(await menuItem("Typ akapitu: —"))).toBe(true);
  await closeMenus();
  caretIn(editor, "Bank Przykładowy");
  expect(button("Lista punktowana")).toBeDisabled();
  await openMore();
  expect(isOff(await menuItem("Typ akapitu: Firma"))).toBe(false);
  await closeMenus();
  caretIn(editor, "Wyrażam zgodę");
  await openMore();
  expect(isOff(await menuItem("Typ akapitu: Zwykły tekst"))).toBe(true);
  await closeMenus();
});

it("„Typ akapitu” oznacza akapit, a „Dodaj” wstawia stanowisko z polami do wypełnienia", async () => {
  const editor = mount();
  caretIn(editor, "Software House");
  await openSub("Typ akapitu: Firma");
  fireEvent.click(await screen.findByRole("menuitemradio", { name: "Zwykły tekst" }));
  expect(editor.getHTML()).toContain("<p>Software House Przykład</p>");
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

  await openSub("Dodaj");
  expect(await menuItem("Punkt")).toBeInTheDocument();
  fireEvent.click(await menuItem("Stanowisko"));
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
  await openSub("Dodaj");
  const item = await menuItem("Język");
  act(() => editor.destroy());
  // Radix oddaje fokus po zamknięciu menu; nieobsłużony wyjątek wywraca bieg vitest.
  fireEvent.keyDown(item, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menuitem", { name: "Język" })).toBeNull());
});

// ── Wyrównanie (decyzja J1, 14.10.2026) ─────────────────────────────────────

it("akapit bez jawnego wyrównania idzie za domyślnym CV — wyjustowanym albo do lewej", () => {
  const editor = mount();
  caretIn(editor, "Usługi płatnicze");
  expect(button("Wyjustuj")).toHaveAttribute("aria-pressed", "true");
  expect(button("Do lewej")).toHaveAttribute("aria-pressed", "false");
});

it("reguła klienta „do lewej” zaznacza „Do lewej”", () => {
  const editor = mount("left");
  caretIn(editor, "Usługi płatnicze");
  expect(button("Do lewej")).toHaveAttribute("aria-pressed", "true");
});

it("„Do lewej” zapisuje wyrównanie tylko w akapicie z kursorem i daje się cofnąć", () => {
  const editor = mount();
  caretIn(editor, "Usługi płatnicze");
  fireEvent.click(button("Do lewej"));
  expect(editor.getHTML()).toContain('<li><p style="text-align: left;">Usługi płatnicze.</p></li>');
  expect(editor.getHTML().match(/text-align/g)).toHaveLength(1);
  expect(button("Do lewej")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(button("Cofnij"));
  expect(editor.getHTML()).not.toContain("text-align");
});

it("zaznaczenie całego CV wyjustowuje akapity, ale nie klauzulę zgody", () => {
  const editor = mount("left");
  act(() => {
    editor.commands.selectAll();
  });
  fireEvent.click(button("Wyjustuj"));
  const page = new DOMParser().parseFromString(editor.getHTML(), "text/html");
  const align = (selector: string) =>
    [...page.querySelectorAll<HTMLElement>(selector)].map((node) => node.style.textAlign);
  expect(align('p[data-cv-section="role"], p[data-cv-section="employer"], li > p')).toEqual(
    Array(5).fill("justify"),
  );
  expect(align('p[data-cv-section="rodo"]')).toEqual([""]);
  expect(align("h1, h2")).toEqual(["", ""]);
});

it("nagłówek i klauzula zgody nie mają przycisków wyrównania", () => {
  const editor = mount();
  caretIn(editor, "DOŚWIADCZENIE");
  expect(button("Wyjustuj")).toBeDisabled();
  caretIn(editor, "Wyrażam zgodę");
  expect(button("Do lewej")).toBeDisabled();
});

it("wyrównanie z zapisanego CV przeżywa wczytanie i zmianę typu akapitu", async () => {
  const content = CV.replace(
    '<p data-cv-section="employer">Bank Przykładowy</p>',
    '<p data-cv-section="employer" style="text-align: left">Bank Przykładowy</p>',
  );
  const editor = mount(undefined, content);
  caretIn(editor, "Bank Przykładowy");
  expect(button("Do lewej")).toHaveAttribute("aria-pressed", "true");
  await openSub("Typ akapitu: Firma");
  fireEvent.click(await screen.findByRole("menuitemradio", { name: "Zwykły tekst" }));
  expect(editor.getHTML()).toContain('<p style="text-align: left;">Bank Przykładowy</p>');
});

// ── Edytor CV 3, PR 3: „Wyjustuj całe CV”, „Pogrub wymagania (N)”, pozycje okna ──

it("„Wyjustuj całe CV” wyrównuje każdy akapit poza klauzulą zgody i nie rusza kursora", async () => {
  const editor = mount("left");
  caretIn(editor, "Bank Przykładowy");
  const caret = editor.state.selection.from;
  await openMore();
  fireEvent.click(await menuItem("Wyjustuj całe CV"));
  const page = new DOMParser().parseFromString(editor.getHTML(), "text/html");
  const align = (selector: string) =>
    [...page.querySelectorAll<HTMLElement>(selector)].map((node) => node.style.textAlign);
  expect(align('p[data-cv-section="role"], p[data-cv-section="employer"], li > p')).toEqual(
    Array(5).fill("justify"),
  );
  expect(align('p[data-cv-section="rodo"]')).toEqual([""]);
  expect(editor.state.selection.from).toBe(caret);
  // Jeden krok cofania.
  fireEvent.click(button("Cofnij"));
  expect(editor.getHTML()).not.toContain("text-align");
});

it("„Pogrub wymagania (N)” pokazuje liczbę z QC i woła poprawkę panelu", () => {
  const onRun = vi.fn();
  mount(undefined, CV, { boldRequirements: { count: 3, disabled: false, onRun } });
  fireEvent.click(button("Pogrub wymagania (3)"));
  expect(onRun).toHaveBeenCalledTimes(1);
});

it("„Pogrub wymagania” bez liczby, gdy QC jeszcze liczy; przy zerze wyłączony z wyjaśnieniem", () => {
  mount(undefined, CV, { boldRequirements: { count: null, disabled: false, onRun: vi.fn() } });
  expect(button("Pogrub wymagania")).toBeDisabled();
});

it("przy zerze „Pogrub wymagania (0)” jest wyłączony i mówi dlaczego", () => {
  mount(undefined, CV, { boldRequirements: { count: 0, disabled: false, onRun: vi.fn() } });
  expect(button("Pogrub wymagania (0)")).toBeDisabled();
  expect(button("Pogrub wymagania (0)")).toHaveAttribute("title", "Wymagania klienta są już pogrubione.");
});

it("edytor bez QC nie ma „Pogrub wymagania”", () => {
  mount();
  expect(screen.queryByRole("button", { name: /Pogrub wymagania/ })).toBeNull();
});

it("pozycje okna w „Więcej” działają także przy wyłączonym pasku (widok „Jak u klienta”)", async () => {
  const onPdf = vi.fn();
  const editor = new Editor({ extensions: cvEditorExtensions(), content: CV });
  editors.push(editor);
  render(
    <CvEditorToolbar
      editor={editor}
      language="pl"
      disabled
      moreGroups={[[{ label: "Pobierz PDF", onSelect: onPdf }, { label: "Drukuj", onSelect: vi.fn(), disabled: true }]]}
    />,
  );
  expect(button("Pogrubienie")).toBeDisabled();
  await openMore();
  expect(isOff(await menuItem("Dodaj"))).toBe(true);
  expect(isOff(await menuItem("Wyjustuj całe CV"))).toBe(true);
  expect(isOff(await menuItem("Drukuj"))).toBe(true);
  fireEvent.click(await menuItem("Pobierz PDF"));
  // Pozycja okna rusza po zamknięciu menu — inaczej menu zabrałoby fokus otwieranemu polu.
  await waitFor(() => expect(onPdf).toHaveBeenCalledTimes(1));
});
