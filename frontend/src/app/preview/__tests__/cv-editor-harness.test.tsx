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

/** „Więcej” (Edytor CV 3, PR 3): polecenia spoza paska. Otwarte menu zasłania okno. */
async function chooseMore(dialog: HTMLElement, name: string, sub?: string): Promise<void> {
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Więcej" }), { key: "ArrowDown" });
  if (sub) fireEvent.keyDown(await screen.findByRole("menuitem", { name: sub }), { key: "ArrowRight" });
  fireEvent.click(await screen.findByRole("menuitem", { name }));
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  // Pozycje okna ruszają po zamknięciu menu (takt później).
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}
/** Pozycje „Więcej” z ich stanem — menu otwiera się i zamyka. */
async function moreItems(dialog: HTMLElement): Promise<Map<string, boolean>> {
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Więcej" }), { key: "ArrowDown" });
  const menu = await screen.findByRole("menu");
  const items = new Map(
    within(menu)
      .getAllByRole("menuitem")
      .map((item) => [item.textContent?.trim() ?? "", item.getAttribute("aria-disabled") !== "true"] as const),
  );
  fireEvent.keyDown(menu, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  return items;
}

it("otwiera szkic z kartką CV i nie wysyła żadnego żądania", async () => {
  const dialog = await openEditor();
  const paper = dialog.querySelector(".cv-paper") as HTMLElement;
  expect(paper).toHaveAttribute("data-cv-lang", "pl");
  expect(within(paper).getByText("Senior Java Developer – Anna Przykładowa")).toBeInTheDocument();
  expect(paper.querySelectorAll('[data-cv-section="role"]')).toHaveLength(2);
  expect(paper.querySelector(".cv-rodo-locked")).toHaveAttribute("contenteditable", "false");
  expect(within(dialog).getByRole("button", { name: "Cofnij" })).toBeDisabled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Jak u klienta" }));
  expect(await within(dialog).findByTestId("word-preview")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Edycja" }));
  noNetwork();
});

it("nowe stanowisko zatrzymuje „Gotowe”, dopóki zostały pola w nawiasach", async () => {
  const dialog = await openEditor();
  await chooseMore(dialog, "Stanowisko", "Dodaj");
  await waitFor(() =>
    expect(dialog.querySelectorAll('.cv-paper [data-cv-section="role"]')).toHaveLength(3),
  );

  fireEvent.click(within(dialog).getByRole("button", { name: "Gotowe" }));
  const alert = await within(dialog).findByText(/Uzupełnij albo usuń pola w nawiasach/);
  expect(alert).toHaveTextContent("[Stanowisko]");
  expect(alert).toHaveTextContent("Szkic jest zapisany.");
  // Okno zostaje otwarte: CV z „[Stanowisko]” nie może pójść do klienta.
  expect(screen.getByRole("dialog", { name: "Edytor CV do klienta" })).toBeInTheDocument();
  noNetwork();
});

it("„Gotowe” na zatwierdzonej wersji bez zmian zamyka okno i nie zakłada szkicu", async () => {
  const dialog = await openEditor("finalized");
  expect(within(dialog).getByText("Zatwierdzona wersja 2")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Gotowe" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edytor CV do klienta" })).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Otwórz edytor" }));
  const reopened = await screen.findByRole("dialog", { name: "Edytor CV do klienta" });
  // Nowy szkic zmieniłby stan na „Szkic v…”.
  expect(await within(reopened).findByText("Zatwierdzona wersja 2")).toBeInTheDocument();
  expect(within(reopened).queryByText(/^Szkic v/)).toBeNull();
  noNetwork();
});

it("wynik generatora bez rekrutacji mówi panelowi źródeł, że nie ma czego pokazać", async () => {
  const dialog = await openEditor("nosources");
  fireEvent.click(within(dialog).getByRole("button", { name: "Oryginał" }));
  expect(await within(dialog).findByTestId("sources")).toHaveTextContent("bez rekrutacji");
  noNetwork();
});

it("panel „Do poprawy” bierze QC, uwagi i poprawki z pamięci — pełny obieg bez sieci (wariant A, 17.10.2026)", async () => {
  const dialog = await openEditor();
  // jsdom nie liczy szerokości: układ wąski, panel pod przełącznikiem kolumny.
  // 4 z QC + 1 uwaga generatora + 1 linia kontroli AI. „MUST-HAVE: … Kafka …”
  // generatora stoi przy pozycji QC o Kafce — nie liczy się drugi raz.
  fireEvent.click(await within(dialog).findByRole("button", { name: "Do poprawy (6)" }));
  expect(within(dialog).getByText("2 blokują wysyłkę")).toBeInTheDocument();
  const blocking = within(dialog).getByRole("region", { name: "Blokuje wysyłkę" });
  expect(blocking).toHaveTextContent("Jenkins — jest w CV, a nie ma tego w oryginale");
  expect(blocking).toHaveTextContent("Kafka — brak opisu w 1 roli");
  // D5 (14.10.2026): zdanie AI ładuje się samo; od 17.10 stoi w wierszu swojej blokady.
  expect(await within(blocking).findByRole("button", { name: "Dopisz: Kafka" })).toBeInTheDocument();
  expect(blocking).toHaveTextContent("przez kolejki Kafka (zdarzenia płatności).");
  expect(within(dialog).queryByRole("region", { name: "Propozycje AI" })).not.toBeInTheDocument();
  const fixable = within(dialog).getByRole("region", { name: "Do poprawy" });
  expect(fixable).toHaveTextContent("Pisownia: „Github” → „GitHub”");
  expect(fixable).toHaveTextContent("Pogrub: PostgreSQL");
  const decide = within(dialog).getByRole("region", { name: "Do decyzji · nie blokuje" });
  expect(decide).toHaveTextContent("WERYFIKUJ");
  expect(decide).toHaveTextContent("Przeglądy kodu");
  expect(within(dialog).getByRole("region", { name: "Informacje" })).toHaveTextContent(
    "1 uwaga generatora o brakującym wymaganiu stoi przy pozycji QC o tym samym wymaganiu.",
  );
  // Miejsca uwag są zaznaczone na kartce, ale nie w zapisywanej treści.
  const paper = dialog.querySelector(".cv-paper .ProseMirror") as HTMLElement;
  expect(paper.querySelector(".cv-issue-term.cv-issue--blocking")).toHaveTextContent("Jenkins");
  expect(paper.querySelector(".cv-issue-block.cv-issue--blocking")).toHaveTextContent("Java Developer 01.2017");

  // „Popraw wszystkie”: zdanie AI, pogrubienie i pisownia jednym kliknięciem.
  fireEvent.click(within(fixable).getByRole("button", { name: /Popraw wszystkie \(3\)/ }));
  await waitFor(() => expect(paper).toHaveTextContent("Docker, Jenkins, GitHub"));
  expect(paper.querySelectorAll("strong")).toContainEqual(expect.objectContaining({ textContent: "PostgreSQL" }));
  expect(paper).toHaveTextContent("przez kolejki Kafka (zdarzenia płatności)");
  // Usunięcie „Jenkins” (treść) nie wchodzi do hurtu.
  expect(paper).toHaveTextContent("Jenkins");
  // Poprawka przełącza na kartkę; „Poprawione” z „Cofnij wszystkie” czeka w panelu.
  fireEvent.click(within(dialog).getByRole("button", { name: /^Do poprawy \(/ }));
  const done = within(dialog).getByRole("region", { name: "Poprawione" });
  expect(done).toHaveTextContent("Dopisano zdanie: Kafka");
  expect(done).toHaveTextContent("Pogrubiono: PostgreSQL");
  expect(done).toHaveTextContent("Poprawiono pisownię technologii");
  fireEvent.click(within(done).getByRole("button", { name: "Cofnij wszystkie" }));
  expect(paper).toHaveTextContent("Docker, Jenkins, Github");
  expect(paper).not.toHaveTextContent("przez kolejki Kafka");
  noNetwork();
});

it("CV z Redakcji: QC „nie dotyczy”, a „Pogrub wymagania (1)” i tak pogrubia (16.10.2026)", async () => {
  const dialog = await openEditor("redakcja");
  // Pogrubienie nie jest uwagą: w „Do poprawy” o jedną mniej niż w szkicu.
  expect(await within(dialog).findByRole("button", { name: "Do poprawy (5)" })).toBeInTheDocument();
  const bold = await within(dialog).findByRole("button", { name: "Pogrub wymagania (1)" });
  expect(bold).toBeEnabled();
  fireEvent.click(bold);
  const paper = dialog.querySelector(".cv-paper .ProseMirror") as HTMLElement;
  await waitFor(() =>
    expect(paper.querySelectorAll("strong")).toContainEqual(expect.objectContaining({ textContent: "PostgreSQL" })),
  );
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

// ── Asystent w kolumnie (Edytor CV 3, PR 4) ─────────────────────────────────

/** jsdom nie liczy szerokości: układ wąski, asystent w kolumnie „Do poprawy”. */
async function openAssistant(dialog: HTMLElement): Promise<HTMLElement> {
  fireEvent.click(await within(dialog).findByRole("button", { name: /^Do poprawy/ }));
  // Od 17.10.2026 asystent stoi zwinięty do jednej linii pod listą uwag.
  fireEvent.click(within(dialog).getByRole("button", { name: "Napisz, co zmienić w CV…" }));
  return within(dialog).getByRole("region", { name: "Asystent CV" });
}

function say(assistant: HTMLElement, text: string): void {
  const field = within(assistant).getByRole("textbox", { name: "Napisz, co zmienić" });
  fireEvent.change(field, { target: { value: text } });
  fireEvent.keyDown(field, { key: "Enter" });
}

const SLOW = { timeout: 3000 };

it("asystent: za długa lista poprawek nie ucina się — licznik mówi, o ile skrócić, a Enter nic nie wysyła", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  const assistant = await openAssistant(dialog);
  const field = within(assistant).getByRole("textbox", { name: "Napisz, co zmienić" });
  expect(within(assistant).getByText("Enter wyślij · Shift+Enter nowa linia")).toBeInTheDocument();
  say(assistant, "x".repeat(2050));
  expect(field).toHaveValue("x".repeat(2050));
  expect(within(assistant).getByTestId("text-limit-counter")).toHaveTextContent("2050 / 2000 znaków — skróć o 50");
  expect(within(assistant).getByRole("button", { name: "Wyślij" })).toBeDisabled();
  expect(within(assistant).queryByText(/Asystent pracuje/)).toBeNull();
  expect(editor.getHTML()).toBe(before);
});

it("asystent: „Skróć do 2 stron” zmienia CV od razu, na zielono, jednym „Cofnij” — bez sieci", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  const assistant = await openAssistant(dialog);
  fireEvent.click(within(assistant).getByRole("button", { name: "Skróć do 2 stron" }));
  // Do odpowiedzi kartka czeka — plan odnosi się do treści z chwili wysłania.
  expect(editor.isEditable).toBe(false);
  expect(within(assistant).getByText(/Asystent pracuje/)).toBeInTheDocument();
  const reply = await within(assistant).findByTestId("cv-assistant-reply", {}, SLOW);
  expect(reply).toHaveTextContent("Zrobione — 3 zmiany, na kartce na zielono.");
  const html = editor.getHTML();
  expect(html).not.toContain("JĘZYKI");
  expect(html).toContain("Optymalizacja zapytań w PostgreSQL; przeglądy kodu i wdrażanie młodszych programistów.");
  expect(editor.view.dom.querySelectorAll(".cv-assistant-new").length).toBeGreaterThan(0);
  expect(dialog.querySelector(".cv-rodo-locked")).not.toBeNull();
  expect(editor.isEditable).toBe(true);

  fireEvent.click(within(reply).getByRole("button", { name: "Cofnij" }));
  expect(editor.getHTML()).toBe(before);
  expect(within(reply).getByText("Cofnięte.")).toBeInTheDocument();
  expect(editor.view.dom.querySelector(".cv-assistant-new")).toBeNull();
  noNetwork();
});

it("fakt spoza CV: asystent pyta, „Tak, dopisz” zapisuje go i dopisuje punkt", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const assistant = await openAssistant(dialog);
  say(assistant, "dopisz terraform w banku");
  const question = await within(assistant).findByText(/Nie widzę „Terraform” w CV ani w notatkach/, {}, SLOW);
  const reply = question.closest('[data-testid="cv-assistant-reply"]') as HTMLElement;
  // Zanim rekruter odpowie, CV jest bez zmian.
  expect(editor.getHTML()).not.toContain("Terraform");
  expect(reply).toHaveTextContent("„Tak” zapisze w notatkach rekrutacji: „Potwierdzone z kandydatem: Terraform”.");
  fireEvent.click(within(reply).getByRole("button", { name: "Tak, dopisz" }));
  await waitFor(() => expect(editor.getHTML()).toContain("Infrastruktura jako kod w <strong>Terraform</strong>."));
  expect(reply).toHaveTextContent("Dopisane. Fakt jest w notatkach rekrutacji z Twoim nazwiskiem.");
  expect(within(reply).getByRole("button", { name: "Cofnij" })).toBeEnabled();
  noNetwork();
});

it("usunięcie jedynego miejsca z wymaganiem: „Nie” niczego nie zmienia, „Tak, zmień” usuwa", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  const assistant = await openAssistant(dialog);
  // Z „Napisz od nowa…” w podpowiedziach „Usuń najstarsze role” wpisuje się słowami.
  expect(within(assistant).queryByRole("button", { name: "Usuń najstarsze role" })).toBeNull();
  say(assistant, "usuń najstarsze stanowiska");
  const first = await within(assistant).findByText(/nie będzie „JUnit”/, {}, SLOW);
  fireEvent.click(within(first.closest('[data-testid="cv-assistant-reply"]') as HTMLElement).getByRole("button", { name: "Nie" }));
  expect(await within(assistant).findByText("Pominięte.")).toBeInTheDocument();
  expect(editor.getHTML()).toBe(before);

  say(assistant, "usuń najstarsze stanowiska");
  await waitFor(() => expect(within(assistant).getAllByText(/nie będzie „JUnit”/)).toHaveLength(2), SLOW);
  const second = within(assistant).getAllByText(/nie będzie „JUnit”/)[1].closest('[data-testid="cv-assistant-reply"]') as HTMLElement;
  fireEvent.click(within(second).getByRole("button", { name: "Tak, zmień" }));
  await waitFor(() => expect(editor.getHTML()).not.toContain("Software House Przykład"));
  noNetwork();
});

it("„Napisz od nowa…”: podpowiedź wpisuje początek zdania, Enter zapisuje, zamyka edytor i oddaje uwagę karcie", async () => {
  const dialog = await openEditor();
  const assistant = await openAssistant(dialog);
  fireEvent.click(within(assistant).getByRole("button", { name: "Napisz od nowa…" }));
  const field = within(assistant).getByRole("textbox", { name: "Napisz, co zmienić" });
  expect(field).toHaveValue("Napisz od nowa: ");
  fireEvent.change(field, { target: { value: "Napisz od nowa: więcej o Kafce" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(await screen.findByTestId("harness-rewrite", {}, SLOW)).toHaveTextContent("z uwagą: „więcej o Kafce”");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  noNetwork();
});

it("pogrubienie i „Rozważany na stanowisko” z rozmowy", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const assistant = await openAssistant(dialog);
  say(assistant, "pogrub postgresa i dockera");
  await waitFor(() => expect(editor.getHTML()).toContain("<strong>PostgreSQL</strong>"), SLOW);
  expect(editor.getHTML()).toContain("<strong>Docker</strong>");
  say(assistant, "stanowisko: Senior Java Engineer");
  await waitFor(
    () => expect(editor.getHTML()).toContain("<strong>Rozważany na stanowisko:</strong> Senior Java Engineer"),
    SLOW,
  );
  noNetwork();
});

it("zaznaczony tekst to kontekst wiadomości", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const assistant = await openAssistant(dialog);
  selectText(editor, "Optymalizacja zapytań");
  expect(await within(assistant).findByTestId("cv-assistant-selection")).toHaveTextContent(
    "Dotyczy zaznaczenia: „Optymalizacja zapytań”",
  );
  say(assistant, "pogrub postgresa");
  expect(await within(assistant).findByText("Zaznaczenie: „Optymalizacja zapytań”")).toBeInTheDocument();
  noNetwork();
});

it("asystent niedostępny: zdanie w kolumnie, kartka od razu do edycji", async () => {
  const dialog = await openEditor("aidown");
  const editor = liveEditor(dialog);
  const assistant = await openAssistant(dialog);
  fireEvent.click(within(assistant).getByRole("button", { name: "Skróć do 2 stron" }));
  expect(await within(assistant).findByText(/Asystent jest chwilowo niedostępny/, {}, SLOW)).toBeInTheDocument();
  expect(editor.isEditable).toBe(true);
  noNetwork();
});

it("Escape, gdy asystent pracuje, nie zamyka edytora", async () => {
  const dialog = await openEditor();
  const assistant = await openAssistant(dialog);
  fireEvent.click(within(assistant).getByRole("button", { name: "Skróć do 2 stron" }));
  expect(within(assistant).getByText(/Asystent pracuje/)).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(dialog.isConnected).toBe(true);
  await within(assistant).findByTestId("cv-assistant-reply", {}, SLOW);
  noNetwork();
});

it("zatwierdzona wersja: pierwsza zmiana asystenta zakłada szkic", async () => {
  const dialog = await openEditor("finalized");
  const editor = liveEditor(dialog);
  expect(within(dialog).getByText("Zatwierdzona wersja 2")).toBeInTheDocument();
  const assistant = await openAssistant(dialog);
  say(assistant, "pogrub postgresa");
  await waitFor(() => expect(editor.getHTML()).toContain("<strong>PostgreSQL</strong>"), SLOW);
  expect(await within(dialog).findByText(/^Szkic v/)).toBeInTheDocument();
  noNetwork();
});

it("wynik generatora bez rekrutacji nie ma asystenta", async () => {
  const dialog = await openEditor("nosources");
  expect(within(dialog).queryByRole("region", { name: "Asystent CV" })).toBeNull();
  const items = await moreItems(dialog);
  expect(items.has("Polecenie dla całego CV")).toBe(false);
  noNetwork();
});

// ── Historia wersji i powrót pliku Word (PR 5) ───────────────────────────────

async function openHistory(dialog: HTMLElement): Promise<HTMLElement> {
  await chooseMore(dialog, "Historia wersji");
  const panel = await within(dialog).findByRole("region", { name: "Historia wersji" });
  await within(panel).findByTestId("history-version-1");
  return panel;
}

function chooseWordFile(dialog: HTMLElement, name: string): void {
  fireEvent.change(within(dialog).getByTestId("history-word-file"), {
    target: { files: [new File(["docx"], name)] },
  });
}

it("historia: różnice z wersją 1, „Przywróć treść wersji” to jedna cofalna zmiana — bez sieci", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  const panel = await openHistory(dialog);
  expect(within(panel).getByTestId("history-version-2")).toHaveTextContent("bieżąca");
  expect(within(panel).getByTestId("history-version-2")).toHaveTextContent(/zatwierdzona 10\.10\.2026,? 11:00 · Marta Testowa/);
  // Plik Word ma tylko wersja, która go zamroziła.
  expect(within(panel).getAllByRole("button", { name: "Pobierz DOCX" })).toHaveLength(1);

  fireEvent.click(within(within(panel).getByTestId("history-version-1")).getByRole("button", { name: "Porównaj" }));
  await within(panel).findByRole("heading", { name: "Wersja 1 a bieżąca treść" });
  expect(within(panel).getByRole("status")).toHaveTextContent("3 różnice");
  expect([...panel.querySelectorAll("[data-diff-kind]")].map((item) => item.getAttribute("data-diff-kind"))).toEqual([
    "removed",
    "changed",
    "added",
  ]);
  expect(panel).toHaveTextContent("W wersji 1: Strojenie zapytań i indeksów w PostgreSQL.");
  expect(panel).toHaveTextContent("Tylko w wersji 1 — dojdzie do CV");
  // Porównanie niczego nie zmienia; kartka zostaje do edycji.
  expect(editor.getHTML()).toBe(before);
  expect(editor.isEditable).toBe(true);

  fireEvent.click(within(panel).getByRole("button", { name: "Przywróć treść wersji 1" }));
  await waitFor(() => expect(editor.getHTML()).toContain("<li><p>Strojenie zapytań i indeksów w PostgreSQL.</p></li>"));
  const html = editor.getHTML();
  expect(html).toContain("<li><p>Dyżury wsparcia produkcyjnego raz w miesiącu.</p></li>");
  expect(html).not.toContain("Projektowała mikroserwisy płatności");
  expect(dialog.querySelector(".cv-rodo-locked")).not.toBeNull();
  // Wąski układ (jsdom): po nałożeniu treści wraca kartka.
  expect(dialog.querySelector(".cv-paper")).not.toHaveAttribute("hidden");
  act(() => {
    editor.commands.undo();
  });
  expect(editor.getHTML()).toBe(before);
  noNetwork();
});

it("historia na zatwierdzonej wersji: bieżąca ma tę samą treść, a szkic powstaje dopiero przy „Przywróć”", async () => {
  const dialog = await openEditor("finalized");
  const editor = liveEditor(dialog);
  const panel = await openHistory(dialog);
  fireEvent.click(within(within(panel).getByTestId("history-version-2")).getByRole("button", { name: "Porównaj" }));
  await within(panel).findByRole("heading", { name: "Wersja 2 a bieżąca treść" });
  expect(within(panel).getByRole("status")).toHaveTextContent("Treść jest taka sama.");
  expect(within(panel).queryByRole("button", { name: /Przywróć/ })).toBeNull();
  fireEvent.click(within(panel).getByRole("button", { name: "Wróć do listy" }));

  fireEvent.click(within(within(panel).getByTestId("history-version-1")).getByRole("button", { name: "Porównaj" }));
  const restore = await within(panel).findByRole("button", { name: "Przywróć treść wersji 1" });
  // Otwarcie panelu i porównanie nie ruszyły zatwierdzonej wersji.
  expect(within(dialog).getByText("Zatwierdzona wersja 2")).toBeInTheDocument();
  fireEvent.click(restore);
  await waitFor(() => expect(editor.getHTML()).toContain("Strojenie zapytań i indeksów w PostgreSQL."));
  expect(await within(dialog).findByText(/^Szkic v/)).toBeInTheDocument();
  noNetwork();
});

it("plik Word: uszkodzony to komunikat, poprawny — różnice i wstawienie z klauzulą bieżącego CV", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  const panel = await openHistory(dialog);

  chooseWordFile(dialog, "uszkodzony.docx");
  expect(await within(panel).findByRole("alert")).toHaveTextContent(
    "Nie udało się odczytać pliku Word — jest uszkodzony albo zabezpieczony hasłem.",
  );
  expect(editor.getHTML()).toBe(before);

  chooseWordFile(dialog, "CV_Anna_P_poprawione.docx");
  await within(panel).findByRole("heading", { name: "Plik Word: CV_Anna_P_poprawione.docx a bieżąca treść" });
  expect(within(panel).getByRole("status")).toHaveTextContent("3 różnice");
  expect(panel).toHaveTextContent("Tylko w pliku Word — dojdzie do CV");
  expect(panel).toHaveTextContent("Tylko w bieżącej treści — zniknie z CV");

  fireEvent.click(within(panel).getByRole("button", { name: "Wstaw treść z pliku Word" }));
  await waitFor(() =>
    expect(editor.getHTML()).toContain("<li><p>Przeglądy kodu oraz wdrażanie i mentoring młodszych programistów.</p></li>"),
  );
  const html = editor.getHTML();
  expect(html).toContain("<li><p>Prowadziła warsztaty z testów kontraktowych dla zespołu.</p></li>");
  expect(html).not.toContain("kolejki komunikatów");
  // Klauzula z pliku nie wchodzi — zostaje ta z edytora, jedna, na końcu.
  expect(html).not.toContain("dla potrzeb przyszłych rekrutacji");
  expect(html.match(/Wyrażam zgodę/g)).toHaveLength(1);
  expect(html).toContain("przez Firmę Przykładową S.A.");
  expect(dialog.querySelector(".cv-rodo-locked")).not.toBeNull();
  act(() => {
    editor.commands.undo();
  });
  expect(editor.getHTML()).toBe(before);
  noNetwork();
});

it("gdy asystent pracuje, „Historia wersji” czeka na jego odpowiedź", async () => {
  const dialog = await openEditor();
  const assistant = await openAssistant(dialog);
  fireEvent.click(within(assistant).getByRole("button", { name: "Skróć do 2 stron" }));
  expect((await moreItems(dialog)).get("Historia wersji")).toBe(false);
  await within(assistant).findByTestId("cv-assistant-reply", {}, SLOW);
  expect((await moreItems(dialog)).get("Historia wersji")).toBe(true);
  noNetwork();
});

it("Escape w panelu historii nie zamyka edytora", async () => {
  const dialog = await openEditor();
  const panel = await openHistory(dialog);
  fireEvent.keyDown(within(panel).getByRole("button", { name: "Wgraj poprawiony plik Word" }), { key: "Escape" });
  expect(dialog.isConnected).toBe(true);
  expect(screen.getByRole("dialog", { name: "Edytor CV do klienta" })).toBeInTheDocument();
  noNetwork();
});

it("wynik generatora bez rekrutacji nie ma historii wersji", async () => {
  const dialog = await openEditor("nosources");
  expect((await moreItems(dialog)).has("Historia wersji")).toBe(false);
  noNetwork();
});

it("`?state=handoff`: stopka z uwagą dla DL, „Gotowe, przekaż do DL” zamyka edytor bez sieci", async () => {
  const dialog = await openEditor("handoff");
  const bar = within(dialog).getByRole("group", { name: "Przekazanie Delivery Leadowi" });
  await waitFor(() =>
    expect(within(bar).getByRole("status")).toHaveTextContent(/rzeczy do decyzji · nic nie blokuje wysyłki/),
  );
  fireEvent.change(within(bar).getByRole("textbox", { name: "Uwaga dla Delivery Leada (opcjonalnie)" }), {
    target: { value: "Dostępna od listopada." },
  });
  fireEvent.click(within(bar).getByRole("button", { name: /Gotowe, przekaż do DL/ }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edytor CV do klienta" })).toBeNull(), {
    timeout: 4000,
  });
  expect(screen.getByTestId("harness-handed-off")).toHaveTextContent(
    "Karta przeszła do „QC CV” z uwagą: „Dostępna od listopada.”.",
  );
  noNetwork();
});

it("`?state=handoff-blocking`: blokady QC → „Przekaż mimo uwag…” otwiera okno obejścia", async () => {
  const dialog = await openEditor("handoff-blocking");
  const bar = within(dialog).getByRole("group", { name: "Przekazanie Delivery Leadowi" });
  await waitFor(() => expect(within(bar).getByRole("status")).toHaveTextContent(/2 blokują wysyłkę/));
  expect(within(bar).queryByRole("button", { name: /Gotowe, przekaż do DL/ })).not.toBeInTheDocument();
  fireEvent.click(within(bar).getByRole("button", { name: "Przekaż mimo uwag…" }));
  const form = await screen.findByRole("dialog", { name: "Przesuń mimo uwag QC" });
  expect(form).toHaveTextContent("CV pójdzie dalej z 2 niepoprawionymi rzeczami");
  noNetwork();
});

it("`?state=handoff-blocking`: „Przekaż mimo uwag…” stoi też w nagłówku blokad w panelu", async () => {
  const dialog = await openEditor("handoff-blocking");
  fireEvent.click(await within(dialog).findByRole("button", { name: /^Do poprawy/ }));
  const blocking = await within(dialog).findByRole("region", { name: "Blokuje wysyłkę" });
  fireEvent.click(within(blocking).getByRole("button", { name: "Przekaż mimo uwag…" }));
  expect(await screen.findByRole("dialog", { name: "Przesuń mimo uwag QC" })).toBeInTheDocument();
  noNetwork();
});
