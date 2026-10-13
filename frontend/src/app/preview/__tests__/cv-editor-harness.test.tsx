/**
 * Harness `/preview/cv-editor` (Edytor CV 2, 12.10.2026).
 *
 * Test montuje CAŁĄ stronę z prawdziwym edytorem (bez atrapy Tiptapa, którą
 * mają testy okna) i sprawdza to, czego atrapa nie pokaże: żadne żądanie nie
 * idzie do sieci, „Dodaj → Stanowisko” zatrzymuje „Zapisz” do wypełnienia pól,
 * a „Zapisz” na zatwierdzonej wersji bez zmian nie zakłada nowego szkicu.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { Editor } from "@tiptap/core";
import {
  Axios,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

// pdf.js i podgląd DOCX nie działają w jsdom; panel źródeł ma własny test.
vi.mock("@/components/v2/cv-editor/CvEditorSources", () => ({
  CvEditorSources: (props: { stageId?: number; context?: unknown }) => (
    <div data-testid="sources">{props.context === null ? "bez rekrutacji" : `etap ${props.stageId}`}</div>
  ),
}));
vi.mock("@/components/v2/cv-editor/CvEditorWordPreview", () => ({
  CvEditorWordPreview: () => <div data-testid="word-preview" />,
}));

import { api } from "@/lib/api";
import CvEditorPreviewPage from "../cv-editor/page";

const sent: InternalAxiosRequestConfig[] = [];
const attempts = vi.spyOn(Axios.prototype, "request");

beforeAll(() => {
  const adapter: AxiosAdapter = async (config) => {
    sent.push(config);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config } as AxiosResponse;
  };
  api.defaults.adapter = adapter;
  // ProseMirror przewija do kursora po każdej zmianie; jsdom nie liczy układu.
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  Element.prototype.scrollIntoView = () => undefined;
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  window.history.replaceState(null, "", "/preview/cv-editor");
});

afterEach(() => {
  sent.length = 0;
  attempts.mockClear();
});

async function openEditor(state?: string): Promise<HTMLElement> {
  if (state) window.history.replaceState(null, "", `/preview/cv-editor?state=${state}`);
  render(<CvEditorPreviewPage />);
  const dialog = await screen.findByRole("dialog", { name: "Edytor CV do klienta" });
  await waitFor(() => expect(dialog.querySelector(".ProseMirror h1")).not.toBeNull());
  return dialog;
}

const noNetwork = () => {
  expect(sent).toEqual([]);
  expect(attempts).not.toHaveBeenCalled();
};

it("otwiera szkic z kartką CV i nie wysyła żadnego żądania", async () => {
  const dialog = await openEditor();
  const paper = dialog.querySelector(".cv-paper") as HTMLElement;
  expect(paper).toHaveAttribute("data-cv-lang", "pl");
  expect(within(paper).getByText("Senior Java Developer – Anna Przykładowa")).toBeInTheDocument();
  expect(paper.querySelectorAll('[data-cv-section="role"]')).toHaveLength(2);
  expect(paper.querySelector(".cv-rodo-locked")).toHaveAttribute("contenteditable", "false");
  expect(within(dialog).getByRole("button", { name: "Cofnij" })).toBeDisabled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Podgląd Word" }));
  expect(await within(dialog).findByTestId("word-preview")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Edycja" }));
  noNetwork();
});

it("nowe stanowisko zatrzymuje „Zapisz”, dopóki zostały pola w nawiasach", async () => {
  const dialog = await openEditor();
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Dodaj" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Stanowisko" }));
  await waitFor(() =>
    expect(dialog.querySelectorAll('.cv-paper [data-cv-section="role"]')).toHaveLength(3),
  );

  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  const alert = await within(dialog).findByText(/Uzupełnij albo usuń pola w nawiasach/);
  expect(alert).toHaveTextContent("[Stanowisko]");
  expect(alert).toHaveTextContent("Szkic jest zapisany.");
  // Okno zostaje otwarte: CV z „[Stanowisko]” nie może pójść do klienta.
  expect(screen.getByRole("dialog", { name: "Edytor CV do klienta" })).toBeInTheDocument();
  noNetwork();
});

it("„Zapisz” na zatwierdzonej wersji bez zmian zamyka okno i nie zakłada szkicu", async () => {
  const dialog = await openEditor("finalized");
  expect(within(dialog).getByRole("button", { name: /Pobierz zatwierdzony DOCX/ })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edytor CV do klienta" })).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Otwórz edytor" }));
  const reopened = await screen.findByRole("dialog", { name: "Edytor CV do klienta" });
  // Nowy szkic zmieniłby przycisk na „Pobierz szkic DOCX”.
  expect(await within(reopened).findByRole("button", { name: /Pobierz zatwierdzony DOCX/ })).toBeInTheDocument();
  noNetwork();
});

it("wynik generatora bez rekrutacji mówi panelowi źródeł, że nie ma czego pokazać", async () => {
  const dialog = await openEditor("nosources");
  fireEvent.click(within(dialog).getByRole("button", { name: "Źródła" }));
  expect(await within(dialog).findByTestId("sources")).toHaveTextContent("bez rekrutacji");
  noNetwork();
});

it("panel „Do poprawy” bierze QC, uwagi i poprawki z pamięci — pełny obieg bez sieci", async () => {
  const dialog = await openEditor();
  // jsdom nie liczy szerokości: układ wąski, panel pod przełącznikiem kolumny.
  fireEvent.click(await within(dialog).findByRole("button", { name: "Do poprawy (7)" }));
  expect(within(dialog).getByText("Blokuje wysyłkę: 2")).toBeInTheDocument();
  expect(within(dialog).getByRole("region", { name: "Uwagi generatora" })).toHaveTextContent("MUST-HAVE");
  expect(within(dialog).getByRole("region", { name: "Kontrola AI" })).toHaveTextContent("Przeglądy kodu");
  // Miejsca uwag są zaznaczone na kartce, ale nie w zapisywanej treści.
  const paper = dialog.querySelector(".cv-paper .ProseMirror") as HTMLElement;
  expect(paper.querySelector(".cv-issue-term.cv-issue--blocking")).toHaveTextContent("Jenkins");
  expect(paper.querySelector(".cv-issue-block.cv-issue--blocking")).toHaveTextContent("Java Developer 01.2017");

  fireEvent.click(within(dialog).getByRole("button", { name: "Popraw wszystko (2)" }));
  await waitFor(() => expect(paper).toHaveTextContent("Docker, Jenkins, GitHub"));
  expect(paper.querySelectorAll("strong")).toContainEqual(expect.objectContaining({ textContent: "PostgreSQL" }));
  // Usunięcie „Jenkins” (treść) nie wchodzi do hurtu.
  expect(paper).toHaveTextContent("Jenkins");
  // Poprawka przełącza na kartkę; wynik z „Cofnij” czeka w panelu.
  fireEvent.click(within(dialog).getByRole("button", { name: /^Do poprawy \(/ }));
  const outcome = within(dialog).getByRole("region", { name: "Wynik poprawek" });
  expect(outcome).toHaveTextContent("Nałożono: 2 poprawki.");
  fireEvent.click(within(outcome).getByRole("button", { name: "Cofnij" }));
  expect(paper).toHaveTextContent("Docker, Jenkins, Github");
  noNetwork();
});

it("QC nie odpowiada: panel mówi o awarii, a nie że CV jest bez uwag", async () => {
  const dialog = await openEditor("qcdown");
  fireEvent.click(await within(dialog).findByRole("button", { name: /^Do poprawy \(/ }));
  expect(await within(dialog).findByText(/Nie udało się policzyć QC — to nie znaczy, że CV jest bez uwag/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/Nic nie blokuje wysyłki/)).not.toBeInTheDocument();
  noNetwork();
});

it("wynik generatora bez rekrutacji ma w panelu same uwagi generatora", async () => {
  const dialog = await openEditor("nosources");
  fireEvent.click(await within(dialog).findByRole("button", { name: "Do poprawy (2)" }));
  expect(within(dialog).getByText(/nie jest jeszcze na etapie rekrutacji/)).toBeInTheDocument();
  expect(within(dialog).getByRole("region", { name: "Uwagi generatora" })).toHaveTextContent("WERYFIKUJ");
  expect(within(dialog).queryByRole("region", { name: "Kontrola AI" })).not.toBeInTheDocument();
  noNetwork();
});

/** Prawdziwy edytor strony — Tiptap wiesza go na elemencie `.ProseMirror`. */
function liveEditor(dialog: HTMLElement): Editor {
  return (dialog.querySelector(".cv-paper .ProseMirror") as HTMLElement & { editor: Editor }).editor;
}

function selectText(editor: Editor, text: string): void {
  let from = -1;
  editor.state.doc.descendants((node, position) => {
    if (from >= 0 || !node.isTextblock) return from < 0;
    const offset = node.textContent.indexOf(text);
    if (offset >= 0) from = position + 1 + offset;
    return false;
  });
  expect(from).toBeGreaterThan(0);
  act(() => {
    editor.commands.setTextSelection({ from, to: from + text.length });
  });
}

it("AI na zaznaczeniu: propozycja z pamięci, „Przyjmij” zmienia tylko zaznaczony fragment — bez sieci", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  selectText(editor, "Optymalizacja zapytań w PostgreSQL.");
  const bubble = await within(dialog).findByRole("toolbar", { name: "Zaznaczony tekst" });
  fireEvent.click(within(bubble).getByRole("button", { name: "Przeredaguj" }));

  const card = await within(dialog).findByRole("dialog", { name: "Propozycja AI" });
  expect(await within(card).findByText("Optymalizowała zapytań w PostgreSQL.")).toBeInTheDocument();
  fireEvent.click(within(card).getByRole("button", { name: "Przyjmij" }));
  await waitFor(() => expect(editor.getHTML()).toContain("<li><p>Optymalizowała zapytań w PostgreSQL.</p></li>"));
  // Reszta CV bez zmian, klauzula na miejscu.
  expect(editor.getHTML()).toContain("Przeglądy kodu i wdrażanie młodszych programistów.");
  expect(dialog.querySelector(".cv-rodo-locked")).not.toBeNull();
  noNetwork();
});

it("AI niedostępne: karta mówi o tym wprost, edytor działa dalej", async () => {
  const dialog = await openEditor("aidown");
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  selectText(editor, "Optymalizacja zapytań");
  fireEvent.click(within(await within(dialog).findByRole("toolbar", { name: "Zaznaczony tekst" })).getByRole("button", { name: "Skróć" }));
  const card = await within(dialog).findByRole("dialog", { name: "Propozycja AI" });
  expect(await within(card).findByText(/Podpowiedź AI jest chwilowo niedostępna/)).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Przyjmij" })).toBeNull();
  fireEvent.click(within(card).getByRole("button", { name: "Zamknij" }));
  expect(editor.getHTML()).toBe(before);
  noNetwork();
});

it("polecenie dla całego CV: plan z pamięci, kartka czeka na decyzję, „Zastosuj” to jedna cofalna zmiana — bez sieci", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  fireEvent.click(within(dialog).getByRole("button", { name: "Polecenie" }));
  const bar = within(dialog).getByRole("form", { name: "Polecenie dla całego CV" });
  fireEvent.click(within(bar).getByRole("button", { name: "Skróć do 2 stron" }));

  const plan = await within(dialog).findByRole("region", { name: "Plan zmian" });
  const apply = await within(plan).findByRole("button", { name: "Zastosuj zaznaczone (3)" });
  expect(within(dialog).getByText("Podgląd zmian — nic nie jest jeszcze zapisane")).toBeInTheDocument();
  expect(plan).toHaveTextContent("Połącz 2 punkty w jeden");
  expect(plan).toHaveTextContent("Usuń sekcję");
  expect(plan).toHaveTextContent("Odrzuciła 1 propozycję asystenta");
  // Do decyzji kartka jest tylko do odczytu i pokazuje podgląd; treść bez zmian.
  expect(editor.isEditable).toBe(false);
  expect(editor.view.dom.querySelectorAll(".cv-plan-remove").length).toBeGreaterThan(0);
  expect(editor.view.dom.querySelector(".cv-plan-new")).not.toBeNull();
  expect(editor.getHTML()).toBe(before);
  // Panel „Do poprawy” ustępuje planowi.
  expect(within(dialog).queryByRole("complementary", { name: "Do poprawy" })).toBeNull();

  fireEvent.click(apply);
  await waitFor(() => expect(within(dialog).queryByRole("region", { name: "Plan zmian" })).toBeNull());
  const html = editor.getHTML();
  expect(html).not.toContain("JĘZYKI");
  expect(html).toContain("Optymalizacja zapytań w PostgreSQL; przeglądy kodu i wdrażanie młodszych programistów.");
  expect(dialog.querySelector(".cv-rodo-locked")).not.toBeNull();
  expect(editor.isEditable).toBe(true);
  act(() => {
    editor.commands.undo();
  });
  expect(editor.getHTML()).toBe(before);
  noNetwork();
});

it("polecenie: Escape w trakcie liczenia planu nie zamyka edytora", async () => {
  const dialog = await openEditor();
  fireEvent.click(within(dialog).getByRole("button", { name: "Polecenie" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Skróć do 2 stron" }));
  expect(await within(dialog).findByText("Asystent przygotowuje plan zmian…")).toBeInTheDocument();
  // Pole polecenia jest wtedy wyłączone, więc klawisz trafia w `body`, nie w pasek.
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(dialog.isConnected).toBe(true);
  expect(await within(dialog).findByRole("button", { name: /Zastosuj zaznaczone/ })).toBeInTheDocument();
  noNetwork();
});

it("polecenie: operacja, po której znika wymaganie, nie jest zaznaczona; „Odrzuć plan” niczego nie zmienia", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  fireEvent.click(within(dialog).getByRole("button", { name: "Polecenie" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń najstarsze role" }));
  const plan = await within(dialog).findByRole("region", { name: "Plan zmian" });
  expect(await within(plan).findByRole("button", { name: "Zastosuj zaznaczone (0)" })).toBeDisabled();
  expect(plan).toHaveTextContent("Usuń stanowisko");
  expect(plan).toHaveTextContent("znika wymaganie klienta: JUnit");
  fireEvent.click(within(plan).getByRole("button", { name: "Odrzuć plan" }));
  expect(within(dialog).queryByRole("region", { name: "Plan zmian" })).toBeNull();
  expect(editor.getHTML()).toBe(before);
  expect(editor.isEditable).toBe(true);
  noNetwork();
});

it("polecenie przy niedostępnym asystencie: zdanie w panelu, kartka od razu do edycji", async () => {
  const dialog = await openEditor("aidown");
  fireEvent.click(within(dialog).getByRole("button", { name: "Polecenie" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Skróć do 2 stron" }));
  const plan = await within(dialog).findByRole("region", { name: "Plan zmian" });
  expect(await within(plan).findByText(/Asystent jest chwilowo niedostępny/)).toBeInTheDocument();
  expect(within(plan).queryByRole("button", { name: /Zastosuj/ })).toBeNull();
  expect(liveEditor(dialog).isEditable).toBe(true);
  noNetwork();
});

it("wynik generatora bez rekrutacji nie ma AI na zaznaczeniu", async () => {
  const dialog = await openEditor("nosources");
  selectText(liveEditor(dialog), "Optymalizacja zapytań");
  expect(within(dialog).queryByRole("toolbar", { name: "Zaznaczony tekst" })).toBeNull();
  // Polecenie dla całego CV też wymaga rekrutacji (wymagania, uprawnienia etapu).
  expect(within(dialog).queryByRole("button", { name: "Polecenie" })).toBeNull();
  expect(within(dialog).queryByRole("button", { name: "AI na zaznaczonym tekście" })).toBeNull();
  noNetwork();
});

it("zatwierdzona wersja: „Przyjmij” zakłada szkic i nakłada propozycję", async () => {
  const dialog = await openEditor("finalized");
  const editor = liveEditor(dialog);
  selectText(editor, "Optymalizacja zapytań w PostgreSQL.");
  fireEvent.click(within(await within(dialog).findByRole("toolbar", { name: "Zaznaczony tekst" })).getByRole("button", { name: "Przeredaguj" }));
  const card = await within(dialog).findByRole("dialog", { name: "Propozycja AI" });
  // Samo zamówienie propozycji nie rusza zatwierdzonej wersji.
  expect(within(dialog).getByRole("button", { name: /Pobierz zatwierdzony DOCX/ })).toBeInTheDocument();
  fireEvent.click(await within(card).findByRole("button", { name: "Przyjmij" }));
  await waitFor(() => expect(editor.getHTML()).toContain("<li><p>Optymalizowała zapytań w PostgreSQL.</p></li>"));
  expect(await within(dialog).findByRole("button", { name: "Pobierz szkic DOCX" })).toBeInTheDocument();
  expect(within(dialog).queryByText(/Zaznaczony tekst zmienił się/)).toBeNull();
  noNetwork();
});

it("Escape w karcie propozycji odrzuca propozycję, a edytor zostaje otwarty", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  selectText(editor, "Optymalizacja zapytań w PostgreSQL.");
  fireEvent.click(within(await within(dialog).findByRole("toolbar", { name: "Zaznaczony tekst" })).getByRole("button", { name: "Skróć" }));
  const card = await within(dialog).findByRole("dialog", { name: "Propozycja AI" });
  fireEvent.keyDown(await within(card).findByRole("button", { name: "Przyjmij" }), { key: "Escape" });
  await waitFor(() => expect(within(dialog).queryByRole("dialog", { name: "Propozycja AI" })).toBeNull());
  expect(screen.getByRole("dialog", { name: "Edytor CV do klienta" })).toBeInTheDocument();
  noNetwork();
});
