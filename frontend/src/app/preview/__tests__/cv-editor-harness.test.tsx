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

it("panel „Do poprawy” bierze QC, uwagi i poprawki z pamięci — pełny obieg bez sieci", async () => {
  const dialog = await openEditor();
  // jsdom nie liczy szerokości: układ wąski, panel pod przełącznikiem kolumny.
  // Jedna lista: 4 z QC + 1 uwaga generatora + 1 linia kontroli AI. „MUST-HAVE: … Kafka …”
  // generatora stoi przy pozycji QC o Kafce — nie liczy się drugi raz.
  fireEvent.click(await within(dialog).findByRole("button", { name: "Do poprawy (6)" }));
  expect(within(dialog).getByText("Blokuje wysyłkę: 2")).toBeInTheDocument();
  expect(within(dialog).getByRole("region", { name: "Całe CV" })).toHaveTextContent("WERYFIKUJ");
  expect(within(dialog).getByRole("region", { name: "Doświadczenie" })).toHaveTextContent("Przeglądy kodu");
  expect(within(dialog).getByRole("region", { name: "Informacje" })).toHaveTextContent(
    "1 uwaga generatora o brakującym wymaganiu stoi przy pozycji QC o tym samym wymaganiu.",
  );
  // Miejsca uwag są zaznaczone na kartce, ale nie w zapisywanej treści.
  const paper = dialog.querySelector(".cv-paper .ProseMirror") as HTMLElement;
  expect(paper.querySelector(".cv-issue-term.cv-issue--blocking")).toHaveTextContent("Jenkins");
  expect(paper.querySelector(".cv-issue-block.cv-issue--blocking")).toHaveTextContent("Java Developer 01.2017");

  // D5 (14.10.2026): propozycja AI ładuje się sama — bez „Zaproponuj poprawki (AI)” —
  // i od razu wchodzi do „Popraw wszystko” obok pogrubienia i pisowni.
  const ai = within(dialog).getByRole("region", { name: "Propozycje AI" });
  expect(await within(ai).findByRole("listitem", { name: "Propozycja: Kafka" })).toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: /Zaproponuj poprawki/ })).not.toBeInTheDocument();
  fireEvent.click(await within(dialog).findByRole("button", { name: "Popraw wszystko (3)" }));
  await waitFor(() => expect(paper).toHaveTextContent("Docker, Jenkins, GitHub"));
  expect(paper.querySelectorAll("strong")).toContainEqual(expect.objectContaining({ textContent: "PostgreSQL" }));
  expect(paper).toHaveTextContent("przez kolejki Kafka (zdarzenia płatności)");
  // Usunięcie „Jenkins” (treść) nie wchodzi do hurtu.
  expect(paper).toHaveTextContent("Jenkins");
  // Poprawka przełącza na kartkę; wynik z „Cofnij” czeka w panelu.
  fireEvent.click(within(dialog).getByRole("button", { name: /^Do poprawy \(/ }));
  const outcome = within(dialog).getByRole("region", { name: "Wynik poprawek" });
  expect(outcome).toHaveTextContent("Nałożono: 3 poprawki.");
  fireEvent.click(within(outcome).getByRole("button", { name: "Cofnij" }));
  expect(paper).toHaveTextContent("Docker, Jenkins, Github");
  expect(paper).not.toHaveTextContent("przez kolejki Kafka");
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
  await chooseMore(dialog, "Polecenie dla całego CV");
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

it("„Polecenie dla całego CV” z „Więcej” zostawia fokus w polu polecenia, nie w kartce", async () => {
  const dialog = await openEditor();
  const editor = liveEditor(dialog);
  const before = editor.getHTML();
  await chooseMore(dialog, "Polecenie dla całego CV");
  const bar = within(dialog).getByRole("form", { name: "Polecenie dla całego CV" });
  // Menu oddaje fokus po zamknięciu — sprawdzamy także chwilę później.
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(bar.contains(document.activeElement)).toBe(true);
  // Pisanie trafia w polecenie, a nie w treść CV.
  expect(editor.getHTML()).toBe(before);
  noNetwork();
});

it("polecenie: Escape w trakcie liczenia planu nie zamyka edytora", async () => {
  const dialog = await openEditor();
  await chooseMore(dialog, "Polecenie dla całego CV");
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
  await chooseMore(dialog, "Polecenie dla całego CV");
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
  await chooseMore(dialog, "Polecenie dla całego CV");
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
  const items = await moreItems(dialog);
  expect(items.has("Polecenie dla całego CV")).toBe(false);
  expect(items.has("AI na zaznaczonym tekście")).toBe(false);
  noNetwork();
});

it("zatwierdzona wersja: „Przyjmij” zakłada szkic i nakłada propozycję", async () => {
  const dialog = await openEditor("finalized");
  const editor = liveEditor(dialog);
  selectText(editor, "Optymalizacja zapytań w PostgreSQL.");
  fireEvent.click(within(await within(dialog).findByRole("toolbar", { name: "Zaznaczony tekst" })).getByRole("button", { name: "Przeredaguj" }));
  const card = await within(dialog).findByRole("dialog", { name: "Propozycja AI" });
  // Samo zamówienie propozycji nie rusza zatwierdzonej wersji.
  expect(within(dialog).getByText("Zatwierdzona wersja 2")).toBeInTheDocument();
  fireEvent.click(await within(card).findByRole("button", { name: "Przyjmij" }));
  await waitFor(() => expect(editor.getHTML()).toContain("<li><p>Optymalizowała zapytań w PostgreSQL.</p></li>"));
  expect(await within(dialog).findByText(/^Szkic v/)).toBeInTheDocument();
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

it("historia i polecenie wykluczają się; w trakcie planu zmian „Historia” jest wyłączona", async () => {
  const dialog = await openEditor();
  await chooseMore(dialog, "Polecenie dla całego CV");
  expect(within(dialog).getByRole("form", { name: "Polecenie dla całego CV" })).toBeInTheDocument();
  await openHistory(dialog);
  expect(within(dialog).queryByRole("form", { name: "Polecenie dla całego CV" })).toBeNull();

  await chooseMore(dialog, "Polecenie dla całego CV");
  expect(within(dialog).queryByRole("region", { name: "Historia wersji" })).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Skróć do 2 stron" }));
  const plan = await within(dialog).findByRole("region", { name: "Plan zmian" });
  await within(plan).findByRole("button", { name: /Zastosuj zaznaczone/ });
  expect((await moreItems(dialog)).get("Historia wersji")).toBe(false);
  fireEvent.click(within(plan).getByRole("button", { name: "Odrzuć plan" }));
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
