import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Editor, Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";

import type { CvEditorHistoryApi, CvVersionSummary } from "@/lib/api/cvEditorHistory";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { CvEditorHistory } from "../CvEditorHistory";
import { CV_WORD_IMPORT_MAX_BYTES, useCvHistory } from "../useCvHistory";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych.";
const CLAUSE_P = `<p data-cv-section="rodo">${CLAUSE}</p>`;
const HEAD =
  "<h1>Dev – Anna Przykładowa</h1>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>';
const CV =
  HEAD +
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>" +
  "<li><p>Integracje przez kolejki Kafka.</p></li>" +
  "<li><p>Udział w spotkaniach zespołu.</p></li></ul>" +
  "<h2>ZAINTERESOWANIA</h2><p>Żeglarstwo, fotografia.</p>" +
  CLAUSE_P;
/** Wersja 1: inny pierwszy punkt, bez punktu o spotkaniach, z akapitem, którego dziś nie ma. */
const VERSION_1 =
  HEAD +
  "<ul><li><p>Rozwój usług w <strong>Java 11</strong>.</p></li>" +
  "<li><p>Integracje przez kolejki Kafka.</p></li></ul>" +
  "<h2>ZAINTERESOWANIA</h2><p>Żeglarstwo, fotografia.</p><p>Biegi górskie.</p>" +
  CLAUSE_P;
/** Plik Word: opakowanie, punkty bez akapitu, cudza klauzula. */
const WORD =
  '<article class="cv">' +
  HEAD +
  "<ul><li>Rozwój usług w <strong>Java 17</strong> i Kotlinie.</li>" +
  "<li>Integracje przez kolejki Kafka.</li>" +
  "<li>Udział w spotkaniach zespołu.</li></ul>" +
  "<h2>ZAINTERESOWANIA</h2><p>Żeglarstwo, fotografia.</p>" +
  '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych przez Inną Firmę.</p>' +
  "</article>";

const VERSIONS: CvVersionSummary[] = [
  {
    version: 2,
    approved_at: "2026-10-10T09:00:00Z",
    approved_by_name: "Marta Testowa",
    language: "pl",
    docx_available: true,
    is_current: true,
  },
  { version: 1, approved_at: null, approved_by_name: null, language: "pl", docx_available: false, is_current: false },
];

function failure(status: number, detail: string): Error {
  return Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: { detail } } });
}

const editors: Editor[] = [];

/** Wtyczka z filtrem: po włączeniu edytor odrzuca każdą zmianę treści — po cichu, jak ProseMirror. */
const refusal = { on: false };
const RefuseChanges = Extension.create({
  name: "testRefuseChanges",
  addProseMirrorPlugins() {
    return [new Plugin({ filterTransaction: (transaction) => !(refusal.on && transaction.docChanged) })];
  },
});

function openEditor(html = CV): Editor {
  const element = document.body.appendChild(document.createElement("div"));
  const editor = new Editor({ element, extensions: [...cvEditorExtensions(), RefuseChanges], content: "" });
  loadCvHtml(editor, html);
  editors.push(editor);
  return editor;
}

interface HostProps {
  editor: Editor;
  api: CvEditorHistoryApi;
  ensureDraft: () => Promise<boolean>;
  download: (version: number) => Promise<void>;
  onApplied: () => void;
  disabled?: boolean;
  noStage?: boolean;
}

function Host({ editor, api, ensureDraft, download, onApplied, disabled = false, noStage = false }: HostProps) {
  const history = useCvHistory({
    editor,
    stageId: noStage ? undefined : 5,
    disabled,
    ensureDraft,
    downloadVersion: download,
    onApplied,
    api,
  });
  // Jak okno edytora: przycisk w pasku otwiera i zamyka panel.
  return (
    <div>
      <button type="button" onClick={() => (history.open ? history.close() : history.show())}>
        przełącz historię
      </button>
      {history.open ? <CvEditorHistory controller={history} /> : null}
    </div>
  );
}

function setup(overrides: Partial<HostProps> & { apiOverrides?: Partial<CvEditorHistoryApi> } = {}) {
  const { apiOverrides, ...hostOverrides } = overrides;
  const editor = hostOverrides.editor ?? openEditor();
  const api = {
    versions: vi.fn<CvEditorHistoryApi["versions"]>(async () => ({ versions: VERSIONS })),
    version: vi.fn<CvEditorHistoryApi["version"]>(async (_stage, version) => ({
      version,
      content_html: version === 1 ? VERSION_1 : CV,
      language: "pl",
      approved_at: null,
    })),
    importPreview: vi.fn<CvEditorHistoryApi["importPreview"]>(async (_stage, file) => ({
      content_html: WORD,
      filename: file.name,
    })),
    ...apiOverrides,
  };
  const ensureDraft = vi.fn(async () => true);
  const download = vi.fn(async () => undefined);
  const onApplied = vi.fn();
  const props: HostProps = { editor, api, ensureDraft, download, onApplied, ...hostOverrides };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (host: HostProps) => (
    <QueryClientProvider client={client}>
      <Host {...host} />
    </QueryClientProvider>
  );
  const view = render(wrap(props));
  return {
    editor,
    api,
    ensureDraft: props.ensureDraft as typeof ensureDraft,
    download,
    onApplied,
    rerender: (next: Partial<HostProps>) => view.rerender(wrap({ ...props, ...next })),
  };
}

const toggle = () => fireEvent.click(screen.getByRole("button", { name: "przełącz historię" }));
const panel = () => screen.getByRole("region", { name: "Historia wersji" });
const row = (version: number) => screen.getByTestId(`history-version-${version}`);
const items = () => [...panel().querySelectorAll<HTMLElement>("[data-diff-kind]")];

async function openPanel() {
  toggle();
  await within(panel()).findByText("Wersja 2");
}

async function compare(version: number) {
  fireEvent.click(within(row(version)).getByRole("button", { name: "Porównaj" }));
  await within(panel()).findByRole("heading", { name: `Wersja ${version} a bieżąca treść` });
}

function chooseFile(file: File) {
  fireEvent.change(screen.getByTestId("history-word-file"), { target: { files: [file] } });
}

const wordFile = (name = "CV Anna poprawione.docx") => new File(["docx"], name);

beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  Element.prototype.scrollIntoView = vi.fn();
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  toast.showError.mockClear();
  toast.showSuccess.mockClear();
  refusal.on = false;
});

afterEach(() => {
  while (editors.length) {
    const editor = editors.pop()!;
    const mount = editor.view.dom.parentElement;
    editor.destroy();
    mount?.remove();
  }
});

describe("lista wersji", () => {
  it("pokazuje wersje z datą w kalendarzu firmy, autorem i plakietką bieżącej; samo otwarcie niczego nie zmienia", async () => {
    const { editor, api, ensureDraft, download } = setup();
    const before = editor.getHTML();
    expect(api.versions).not.toHaveBeenCalled();
    await openPanel();

    expect(api.versions).toHaveBeenCalledWith(5);
    expect(row(2)).toHaveTextContent("bieżąca");
    // 09:00 UTC to 11:00 w Warszawie (czas letni) — nie strefa przeglądarki.
    expect(row(2)).toHaveTextContent(/zatwierdzona 10\.10\.2026,? 11:00 · Marta Testowa/);
    expect(row(1)).not.toHaveTextContent("bieżąca");
    expect(row(1)).toHaveTextContent(/^Wersja 1zatwierdzonaPorównaj$/);
    // Plik Word tylko tam, gdzie wersja go ma.
    expect(within(row(1)).queryByRole("button", { name: "Pobierz DOCX" })).toBeNull();
    fireEvent.click(within(row(2)).getByRole("button", { name: "Pobierz DOCX" }));
    expect(download).toHaveBeenCalledWith(2);

    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();
  });

  it("w trakcie wczytywania nie udaje pustej historii", async () => {
    setup({ apiOverrides: { versions: vi.fn(() => new Promise<never>(() => undefined)) } });
    toggle();
    expect(within(panel()).getByRole("status")).toHaveTextContent("Wczytuję historię wersji…");
    expect(within(panel()).queryByText(/nie było jeszcze zatwierdzone/)).toBeNull();
  });

  it("awaria zapytania to komunikat z „Ponów”, nie „brak wersji”", async () => {
    const versions = vi
      .fn<CvEditorHistoryApi["versions"]>()
      .mockRejectedValueOnce(failure(503, "Historia wersji jest chwilowo niedostępna."))
      .mockResolvedValue({ versions: VERSIONS });
    setup({ apiOverrides: { versions } });
    toggle();
    const alert = await within(panel()).findByRole("alert");
    expect(alert).toHaveTextContent("Historia wersji jest chwilowo niedostępna.");
    expect(within(panel()).queryByText(/nie było jeszcze zatwierdzone/)).toBeNull();
    expect(within(panel()).queryByText("Wersja 2")).toBeNull();

    fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(await within(panel()).findByText("Wersja 2")).toBeInTheDocument();
    expect(within(panel()).queryByRole("alert")).toBeNull();
  });

  it("CV bez zatwierdzonej wersji mówi, kiedy historia się pojawi — plik Word da się wgrać i tak", async () => {
    setup({ apiOverrides: { versions: vi.fn(async () => ({ versions: [] })) } });
    toggle();
    expect(
      await within(panel()).findByText("To CV nie było jeszcze zatwierdzone — historia pojawi się po pierwszym „Zapisz”."),
    ).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Wgraj poprawiony plik Word" })).toBeEnabled();
  });

  it("nieudane pobranie pliku wersji to komunikat serwera", async () => {
    const download = vi.fn(async () => {
      throw failure(409, "Kandydat nie wyraził zgody na przetwarzanie danych.");
    });
    setup({ download });
    await openPanel();
    fireEvent.click(within(row(2)).getByRole("button", { name: "Pobierz DOCX" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Kandydat nie wyraził zgody na przetwarzanie danych."));
  });
});

describe("porównanie z wersją i przywrócenie", () => {
  it("„Porównaj” pokazuje różnice z bieżącą treścią i niczego jeszcze nie zmienia", async () => {
    const { editor, api, ensureDraft } = setup();
    const before = editor.getHTML();
    await openPanel();
    await compare(1);

    expect(api.version).toHaveBeenCalledWith(5, 1);
    expect(within(panel()).getByRole("status")).toHaveTextContent("3 różnice");
    const [changed, removed, added] = items();
    expect(changed).toHaveAttribute("data-diff-kind", "changed");
    expect(changed).toHaveTextContent("Zmienione");
    expect(changed).toHaveTextContent("Senior Developer 2021 – 2024");
    expect(changed).toHaveTextContent("Teraz: Rozwój usług w Java 17.");
    expect(changed).toHaveTextContent("W wersji 1: Rozwój usług w Java 11.");
    // Pogrubienie jako tekst w React, nie HTML: znaczników `**` nie widać.
    expect(changed.querySelector("del strong")).toHaveTextContent("Java 17");
    expect(changed.querySelector("ins strong")).toHaveTextContent("Java 11");
    expect(changed).not.toHaveTextContent("**");
    expect(removed).toHaveTextContent("Tylko w bieżącej treści — zniknie z CV");
    expect(removed.querySelector("del")).toHaveTextContent("Udział w spotkaniach zespołu.");
    expect(removed.querySelector("ins")).toBeNull();
    expect(added).toHaveTextContent("Tylko w wersji 1 — dojdzie do CV");
    expect(added).toHaveTextContent("ZAINTERESOWANIA");
    expect(added.querySelector("ins")).toHaveTextContent("Biegi górskie.");
    expect(panel()).toHaveTextContent("Klauzula zgody i układ szablonu zostają z bieżącej wersji.");
    expect(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" })).toBeEnabled();

    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();
    expect(editor.can().undo()).toBe(false);
  });

  it("„Przywróć treść wersji” to jedna cofalna zmiana; szkic powstaje dopiero wtedy, raz", async () => {
    const { editor, ensureDraft, onApplied } = setup();
    const before = editor.getHTML();
    const updates = vi.fn();
    editor.on("update", updates);
    await openPanel();
    await compare(1);
    expect(updates).not.toHaveBeenCalled();

    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await within(panel()).findByText("Wersja 2");

    expect(ensureDraft).toHaveBeenCalledTimes(1);
    const html = editor.getHTML();
    expect(html).toContain("<li><p>Rozwój usług w <strong>Java 11</strong>.</p></li>");
    expect(html).toContain("<p>Biegi górskie.</p>");
    expect(html).not.toContain("spotkaniach zespołu");
    expect(html.endsWith(`${CLAUSE}</p>`)).toBe(true);
    // Zwykła zmiana treści: okno zobaczy ją w „update” i utrwali autozapisem.
    expect(updates).toHaveBeenCalledTimes(1);
    expect(toast.showSuccess).toHaveBeenCalledWith("Przywrócono treść wersji 1. Cofniesz to jednym „Cofnij”.");
    expect(onApplied).toHaveBeenCalledTimes(1);

    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
    expect(editor.can().undo()).toBe(false);
  });

  it("dwa kliknięcia „Przywróć” nakładają treść raz", async () => {
    let release: (ok: boolean) => void = () => undefined;
    const ensureDraft = vi.fn(() => new Promise<boolean>((resolve) => (release = resolve)));
    const { editor } = setup({ ensureDraft });
    const before = editor.getHTML();
    await openPanel();
    await compare(1);
    const restore = within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" });
    fireEvent.click(restore);
    fireEvent.click(restore);
    // W trakcie zakładania szkicu przyciski są wyłączone.
    await waitFor(() => expect(restore).toBeDisabled());
    expect(within(panel()).getByRole("button", { name: "Wróć do listy" })).toBeDisabled();
    await act(async () => release(true));
    await within(panel()).findByText("Wersja 2");

    expect(ensureDraft).toHaveBeenCalledTimes(1);
    expect(toast.showSuccess).toHaveBeenCalledTimes(1);
    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
    expect(editor.can().undo()).toBe(false);
  });

  it("zatwierdzona wersja: wczytanie nowego szkicu nie gubi porównania, a „Cofnij” wraca dokładnie", async () => {
    const editor = openEditor();
    // Jak okno: nowy szkic wczytuje tę samą treść poza historią cofania.
    const ensureDraft = vi.fn(async () => {
      loadCvHtml(editor, editor.getHTML());
      return true;
    });
    setup({ editor, ensureDraft });
    const before = editor.getHTML();
    await openPanel();
    await compare(1);
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await within(panel()).findByText("Wersja 2");
    expect(editor.getHTML()).toContain("<p>Biegi górskie.</p>");
    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
  });

  it("edytor odrzucił zmianę — nie ma komunikatu o sukcesie, porównanie zostaje", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    await openPanel();
    await compare(1);
    refusal.on = true;
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Nie udało się wstawić tej treści do edytora — CV zostało bez zmian."),
    );
    expect(ensureDraft).toHaveBeenCalledTimes(1);
    expect(toast.showSuccess).not.toHaveBeenCalled();
    expect(editor.getHTML()).toBe(before);
    expect(await within(panel()).findByRole("button", { name: "Przywróć treść wersji 1" })).toBeEnabled();
  });

  it("klauzula bez znacznika (starsze CV) i akapit dopisany tuż przed nią: treść naprawdę się zmienia", async () => {
    const unmarked = `<p>${CLAUSE}</p>`;
    const old = "<h1>Dev – Anna Przykładowa</h1><p>Opis.</p>";
    const editor = openEditor(old + unmarked);
    const version = vi.fn<CvEditorHistoryApi["version"]>(async (_stage, number) => ({
      version: number,
      // „W…” jak „Wyrażam…”: najmniejsza zamiana zaczynałaby się w środku klauzuli.
      content_html: `${old}<p>Wolontariat w schronisku.</p>${unmarked}`,
      language: "pl",
      approved_at: null,
    }));
    setup({ editor, apiOverrides: { version } });
    const before = editor.getHTML();
    await openPanel();
    await compare(1);
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await within(panel()).findByText("Wersja 2");
    expect(editor.getHTML()).toBe(`${old}<p>Wolontariat w schronisku.</p>${unmarked}`);
    expect(toast.showSuccess).toHaveBeenCalledTimes(1);
    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
  });

  it("nieudane założenie szkicu niczego nie zmienia i zostawia porównanie do ponowienia", async () => {
    const ensureDraft = vi.fn(async () => false);
    const { editor } = setup({ ensureDraft });
    const before = editor.getHTML();
    await openPanel();
    await compare(1);
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await waitFor(() => expect(ensureDraft).toHaveBeenCalledTimes(1));
    expect(await within(panel()).findByRole("button", { name: "Przywróć treść wersji 1" })).toBeEnabled();
    expect(editor.getHTML()).toBe(before);
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("wersja z tą samą treścią: „Treść jest taka sama.” i nie ma czego przywracać", async () => {
    const { ensureDraft } = setup();
    await openPanel();
    await compare(2);
    expect(within(panel()).getByRole("status")).toHaveTextContent("Treść jest taka sama.");
    expect(within(panel()).queryByRole("button", { name: /Przywróć/ })).toBeNull();
    expect(panel()).not.toHaveTextContent("Klauzula zgody");
    fireEvent.click(within(panel()).getByRole("button", { name: "Wróć do listy" }));
    expect(within(panel()).getByText("Wersja 2")).toBeInTheDocument();
    expect(ensureDraft).not.toHaveBeenCalled();
  });

  it("różnice liczą się z treści, która jest w edytorze teraz", async () => {
    const { editor } = setup();
    await openPanel();
    await compare(1);
    expect(within(panel()).getByRole("status")).toHaveTextContent("3 różnice");
    // Rekruter sam dopisuje brakujący akapit — jedna różnica mniej.
    act(() => {
      const end = editor.state.doc.content.size - editor.state.doc.lastChild!.nodeSize;
      editor.commands.insertContentAt(end, "<p>Biegi górskie.</p>");
    });
    await waitFor(() => expect(within(panel()).getByRole("status")).toHaveTextContent("2 różnice"));
    expect(panel()).not.toHaveTextContent("Biegi górskie.");
  });

  it("po przywróceniu klawiatura wraca do kartki", async () => {
    const { editor } = setup();
    const focus = vi.spyOn(editor.view.dom, "focus").mockImplementation(() => undefined);
    await openPanel();
    await compare(1);
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await waitFor(() => expect(focus).toHaveBeenCalledWith({ preventScroll: true }));
  });

  it("kartka tylko do odczytu nie dostaje fokusu po przywróceniu", async () => {
    const { editor } = setup();
    editor.setEditable(false, false);
    const focus = vi.spyOn(editor.view.dom, "focus").mockImplementation(() => undefined);
    await openPanel();
    await compare(1);
    fireEvent.click(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" }));
    await within(panel()).findByText("Wersja 2");
    expect(focus).not.toHaveBeenCalled();
  });

  it("serwer nie oddał wersji — komunikat w panelu, lista zostaje", async () => {
    const version = vi.fn<CvEditorHistoryApi["version"]>(async () => {
      throw new Error("sieć");
    });
    const { editor } = setup({ apiOverrides: { version } });
    const before = editor.getHTML();
    await openPanel();
    fireEvent.click(within(row(1)).getByRole("button", { name: "Porównaj" }));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("Nie udało się wczytać tej wersji CV. Spróbuj ponownie.");
    expect(within(panel()).getByText("Wersja 1")).toBeInTheDocument();
    expect(editor.getHTML()).toBe(before);
  });

  it("wersja bez treści nie jest do przywrócenia", async () => {
    const version = vi.fn<CvEditorHistoryApi["version"]>(async (_stage, number) => ({
      version: number,
      content_html: CLAUSE_P,
      language: "pl",
      approved_at: null,
    }));
    setup({ apiOverrides: { version } });
    await openPanel();
    fireEvent.click(within(row(1)).getByRole("button", { name: "Porównaj" }));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("Ta wersja nie ma treści");
    expect(within(panel()).queryByRole("button", { name: /Przywróć/ })).toBeNull();
  });

  it("treść wersji to tekst — znaczniki wpisane w CV nie stają się elementami strony", async () => {
    const version = vi.fn<CvEditorHistoryApi["version"]>(async (_stage, number) => ({
      version: number,
      content_html: CV.replace(
        "Żeglarstwo, fotografia.",
        "&lt;img src=x onerror=alert(1)&gt; &lt;b&gt;pogrubione&lt;/b&gt; **Żeglarstwo**",
      ),
      language: "pl",
      approved_at: null,
    }));
    setup({ apiOverrides: { version } });
    await openPanel();
    await compare(1);
    const [changed] = items();
    expect(changed).toHaveTextContent("W wersji 1: <img src=x onerror=alert(1)> <b>pogrubione</b> Żeglarstwo");
    // Jedyny znacznik w wierszu to pogrubienie z zapisu `**x**`, złożone w React.
    expect(changed.querySelector("img, b, script")).toBeNull();
    expect(changed.querySelector("ins strong")).toHaveTextContent("Żeglarstwo");
  });

  it("długa lista różnic pokazuje pierwsze 60 i mówi, ile zostało", async () => {
    const bullets = Array.from({ length: 75 }, (_, index) => `<li><p>Dodatkowy punkt numer ${index + 1}.</p></li>`).join("");
    const version = vi.fn<CvEditorHistoryApi["version"]>(async (_stage, number) => ({
      version: number,
      content_html: CV.replace("</ul>", `${bullets}</ul>`),
      language: "pl",
      approved_at: null,
    }));
    setup({ apiOverrides: { version } });
    await openPanel();
    await compare(1);
    expect(within(panel()).getByRole("status")).toHaveTextContent("75 różnic");
    expect(items()).toHaveLength(60);
    expect(within(panel()).getByText("i jeszcze 15")).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Przywróć treść wersji 1" })).toBeEnabled();
  });

  it("treść za długa na listę różnic nie daje się wstawić na ślepo", async () => {
    const bullets = Array.from({ length: 610 }, (_, index) => `<li><p>Punkt ${index + 1}.</p></li>`).join("");
    const version = vi.fn<CvEditorHistoryApi["version"]>(async (_stage, number) => ({
      version: number,
      content_html: `<h1>CV</h1><ul>${bullets}</ul>`,
      language: "pl",
      approved_at: null,
    }));
    setup({ apiOverrides: { version } });
    await openPanel();
    await compare(1);
    expect(within(panel()).getByRole("status")).toHaveTextContent("Za dużo wierszy, żeby pokazać różnice (ponad 600)");
    expect(within(panel()).queryByRole("button", { name: /Przywróć/ })).toBeNull();
    expect(within(panel()).getByRole("button", { name: "Wróć do listy" })).toBeEnabled();
  });

  it("odpowiedź, która wróciła po zamknięciu panelu, nie otwiera porównania", async () => {
    let answer: (html: string) => void = () => undefined;
    const version = vi.fn<CvEditorHistoryApi["version"]>(
      (_stage, number) =>
        new Promise((resolve) => {
          answer = (html) => resolve({ version: number, content_html: html, language: "pl", approved_at: null });
        }),
    );
    setup({ apiOverrides: { version } });
    await openPanel();
    fireEvent.click(within(row(1)).getByRole("button", { name: "Porównaj" }));
    // W trakcie wczytywania drugie porównanie i wgranie pliku czekają.
    expect(within(row(2)).getByRole("button", { name: "Porównaj" })).toBeDisabled();
    expect(within(panel()).getByRole("button", { name: "Wgraj poprawiony plik Word" })).toBeDisabled();
    toggle();
    await act(async () => answer(VERSION_1));
    await openPanel();
    expect(within(panel()).queryByRole("heading", { name: /a bieżąca treść/ })).toBeNull();
    expect(within(row(1)).getByRole("button", { name: "Porównaj" })).toBeEnabled();
  });
});

describe("poprawiony plik Word", () => {
  it("wgrany plik pokazuje różnice; „Wstaw treść z pliku Word” zostawia klauzulę bieżącego CV", async () => {
    const { editor, api, ensureDraft } = setup();
    const before = editor.getHTML();
    await openPanel();
    expect(panel()).toHaveTextContent(
      "Jeśli ktoś poprawił CV w Wordzie, wgraj plik — zobaczysz różnice, zanim cokolwiek się zmieni.",
    );
    const file = wordFile();
    chooseFile(file);
    await within(panel()).findByRole("heading", { name: "Plik Word: CV Anna poprawione.docx a bieżąca treść" });

    expect(api.importPreview).toHaveBeenCalledWith(5, file);
    expect(within(panel()).getByRole("status")).toHaveTextContent("1 różnica");
    expect(items()[0]).toHaveTextContent("W pliku Word: Rozwój usług w Java 17 i Kotlinie.");
    // Sam upload niczego nie zmienia i nie zakłada szkicu.
    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();

    fireEvent.click(within(panel()).getByRole("button", { name: "Wstaw treść z pliku Word" }));
    await within(panel()).findByText("Wersja 2");
    expect(ensureDraft).toHaveBeenCalledTimes(1);
    const html = editor.getHTML();
    expect(html).toContain("<li><p>Rozwój usług w <strong>Java 17</strong> i Kotlinie.</p></li>");
    expect(html).not.toContain("Inną Firmę");
    expect(html.match(/Wyrażam zgodę/g)).toHaveLength(1);
    expect(html.endsWith(`${CLAUSE}</p>`)).toBe(true);
    expect(toast.showSuccess).toHaveBeenCalledWith("Wstawiono treść z pliku Word. Cofniesz to jednym „Cofnij”.");
    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
  });

  it("plik, który nie jest .docx, nie idzie na serwer", async () => {
    const { api } = setup();
    await openPanel();
    for (const name of ["CV Anna.pdf", "CV Anna.doc", "docx"]) {
      chooseFile(new File(["x"], name));
      expect(within(panel()).getByRole("alert")).toHaveTextContent("To nie jest plik Word w formacie .docx.");
    }
    expect(api.importPreview).not.toHaveBeenCalled();
    // Wielkie litery w rozszerzeniu to dalej ten sam format.
    chooseFile(wordFile("CV ANNA.DOCX"));
    await within(panel()).findByRole("heading", { name: /^Plik Word: CV ANNA\.DOCX/ });
    expect(api.importPreview).toHaveBeenCalledTimes(1);
  });

  it("plik ponad 10 MB nie idzie na serwer", async () => {
    const { api } = setup();
    await openPanel();
    const exact = wordFile("na-limicie.docx");
    Object.defineProperty(exact, "size", { value: CV_WORD_IMPORT_MAX_BYTES });
    const big = wordFile("za-duzy.docx");
    Object.defineProperty(big, "size", { value: CV_WORD_IMPORT_MAX_BYTES + 1 });
    chooseFile(big);
    expect(within(panel()).getByRole("alert")).toHaveTextContent("Ten plik jest za duży — limit to 10 MB.");
    expect(api.importPreview).not.toHaveBeenCalled();
    chooseFile(exact);
    await within(panel()).findByRole("heading", { name: /^Plik Word: na-limicie\.docx/ });
  });

  it("serwer odrzucił plik — jego komunikat w panelu, edytor bez zmian", async () => {
    const importPreview = vi
      .fn<CvEditorHistoryApi["importPreview"]>()
      .mockRejectedValueOnce(failure(422, "Nie udało się odczytać pliku — jest uszkodzony albo zabezpieczony hasłem."))
      .mockResolvedValue({ content_html: WORD, filename: "drugi.docx" });
    const { editor, ensureDraft } = setup({ apiOverrides: { importPreview } });
    const before = editor.getHTML();
    await openPanel();
    chooseFile(wordFile("uszkodzony.docx"));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent(
      "Nie udało się odczytać pliku — jest uszkodzony albo zabezpieczony hasłem.",
    );
    expect(within(panel()).getByText("Wersja 2")).toBeInTheDocument();
    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();
    // Kolejna próba czyści komunikat.
    chooseFile(wordFile("drugi.docx"));
    await within(panel()).findByRole("heading", { name: /^Plik Word: drugi\.docx/ });
    expect(within(panel()).queryByRole("alert")).toBeNull();
  });

  it("plik bez treści CV nie jest do wstawienia", async () => {
    const importPreview = vi.fn<CvEditorHistoryApi["importPreview"]>(async (_stage, file) => ({
      content_html: '<article class="cv"><p class="rodo">Wyrażam zgodę na przetwarzanie moich danych.</p></article>',
      filename: file.name,
    }));
    setup({ apiOverrides: { importPreview } });
    await openPanel();
    chooseFile(wordFile());
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("W tym pliku nie ma treści CV");
  });
});

describe("panel a okno edytora", () => {
  it("podgląd Word albo zapis zamyka panel; edytor wyniku generatora nie ma historii", async () => {
    const { rerender, api } = setup();
    await openPanel();
    await compare(1);
    rerender({ disabled: true });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Historia wersji" })).toBeNull());
    // Wyłączona historia się nie otwiera.
    toggle();
    expect(screen.queryByRole("region", { name: "Historia wersji" })).toBeNull();

    rerender({ disabled: false, noStage: true });
    toggle();
    expect(screen.queryByRole("region", { name: "Historia wersji" })).toBeNull();
    expect(api.versions).toHaveBeenCalledTimes(1);
  });

  it("Escape w panelu nie wychodzi poza niego, a fokus po zmianie widoku zostaje w panelu", async () => {
    setup();
    await openPanel();
    await compare(1);
    // Przycisk „Porównaj” zniknął razem z listą — fokus przejął panel.
    expect(document.activeElement).toBe(panel());
    const outside = vi.fn();
    document.addEventListener("keydown", outside);
    try {
      fireEvent.keyDown(within(panel()).getByRole("button", { name: "Wróć do listy" }), { key: "Escape" });
    } finally {
      document.removeEventListener("keydown", outside);
    }
    expect(outside).not.toHaveBeenCalled();
    expect(panel()).toHaveAttribute("data-cv-command");
  });

  it("„Zamknij historię” zamyka panel i porzuca porównanie", async () => {
    setup();
    await openPanel();
    fireEvent.click(within(panel()).getByRole("button", { name: "Zamknij historię" }));
    expect(screen.queryByRole("region", { name: "Historia wersji" })).toBeNull();
  });
});
