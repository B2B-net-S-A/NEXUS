/**
 * Okno edytora CV a panel „Do poprawy” (Edytor CV 2, PR 2): który panel stoi
 * obok kartki przy danej szerokości, licznik w pasku i szkic zakładany przed
 * poprawką na zatwierdzonej wersji. Sam panel ma własny test
 * (`cv-editor/__tests__/CvEditorIssues.test.tsx`).
 *
 * PR 5: to samo dla panelu „Historia” — gdzie staje, czemu ustępuje i jak
 * wyklucza się z poleceniem. Sam panel: `cv-editor/__tests__/CvEditorHistory.test.tsx`.
 */

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({
  width: 1280,
  status: "draft",
  revision: 4,
  html: "<p>Treść CV</p>",
  onUpdate: null as null | (() => void),
  newDrafts: 0,
  failNewDraft: false,
  count: { total: 3, blocking: 1, state: "ready" } as { total: number; blocking: number; state: "loading" | "ready" | "failed" },
  drafted: [] as boolean[],
  issuesProps: [] as Array<Record<string, unknown>>,
  historyOptions: null as null | { stageId?: number; disabled: boolean; downloadVersion: (version: number) => Promise<void> },
}));

vi.mock("@/lib/use-element-width", () => ({ useElementWidth: () => state.width }));
vi.mock("@tiptap/react", () => {
  const editor = {
    commands: { setContent: (html: string) => { state.html = html; } },
    setEditable: vi.fn(),
    getHTML: () => state.html,
    isDestroyed: false,
    on: (_event: string, callback: () => void) => { state.onUpdate = callback; },
    off: () => { state.onUpdate = null; },
  };
  return { useEditor: () => editor, EditorContent: () => <div data-testid="paper" /> };
});
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));
vi.mock("@/lib/cv-editor-structure", () => ({
  cvEditorExtensions: () => [],
  loadCvHtml: (editor: { commands: { setContent: (html: string) => void } }, html: string) =>
    editor.commands.setContent(html),
}));
vi.mock("@/components/v2/cv-editor/CvEditorToolbar", () => ({ CvEditorToolbar: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorSources", () => ({
  CvEditorSources: () => <div data-testid="sources" />,
}));
vi.mock("@/components/v2/cv-editor/CvEditorSelectionAi", () => ({ CvEditorSelectionAi: () => null }));
// Polecenie dla całego CV pracuje na prawdziwym edytorze (jak AI na zaznaczeniu) —
// ma własne testy; atrapa edytora tego okna nie ma widoku ProseMirror.
vi.mock("@/components/v2/cv-editor/useCvCommandPlan", () => ({
  useCvCommandPlan: () => ({ enabled: false, phase: "idle", locked: false, discard: () => undefined }),
}));
vi.mock("@/components/v2/cv-editor/useCvSelectionAi", () => ({
  useCvSelectionAi: () => ({ enabled: false, selection: { ok: false, reason: null, hidden: true }, phase: "idle" }),
}));
// Historia wersji porównuje dokument prawdziwego edytora — ma własne testy.
// Tutaj atrapa trzyma samo „otwarte / zamknięte”, żeby sprawdzić układ okna.
vi.mock("@/components/v2/cv-editor/useCvHistory", async () => {
  const { useState } = await import("react");
  return {
    useCvHistory: (options: NonNullable<typeof state.historyOptions>) => {
      const [open, setOpen] = useState(false);
      state.historyOptions = options;
      return {
        enabled: options.stageId != null && !options.disabled,
        open,
        busy: false,
        show: () => setOpen(true),
        close: () => setOpen(false),
      };
    },
  };
});
vi.mock("@/components/v2/cv-editor/CvEditorHistory", () => ({
  CvEditorHistory: () => <div data-testid="history" />,
}));
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({ CvPagesPreview: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorIssues", async () => {
  const { useEffect } = await import("react");
  return {
    CvEditorIssues: (props: {
      onCount?: (count: typeof state.count) => void;
      ensureDraft: () => Promise<boolean>;
      onShowCv: () => void;
    }) => {
      state.issuesProps.push(props as unknown as Record<string, unknown>);
      const { onCount } = props;
      useEffect(() => onCount?.(state.count), [onCount]);
      return (
        <div data-testid="issues">
          <button onClick={() => void props.ensureDraft().then((ok) => state.drafted.push(ok))}>załóż szkic</button>
          <button onClick={props.onShowCv}>pokaż kartkę</button>
        </div>
      );
    },
  };
});
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/authenticated-files", () => ({
  openAuthenticatedFile: vi.fn(),
  downloadAuthenticatedFile: vi.fn(),
  fetchAuthenticatedBlob: vi.fn(),
  postAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
}));
vi.mock("@/lib/api", () => {
  const body = () => ({
    status: state.status,
    content_html: state.html,
    edit_revision: state.revision,
    version: 2,
    template: "standard",
    language: "pl",
    docx_available: state.status === "finalized",
    updated_at: "2026-10-12T07:00:00Z",
  });
  const adapter = {
    get: async () => ({ data: body() }),
    update: async () => {
      state.revision += 1;
      return { data: body() };
    },
    newDraft: async () => {
      if (state.failNewDraft) throw new Error("serwer odmówił");
      state.newDrafts += 1;
      state.status = "draft";
      state.revision += 1;
      return { data: body() };
    },
    finalize: async () => ({ data: { edit_revision: state.revision } }),
  };
  return { candidateStageCvApi: { branded: adapter }, cvGeneratedEditorApi: adapter };
});

import { CVBrandedEditModal } from "../CVBrandedEditModal";

type Target = { stageId: number } | { generatedId: number };

async function open(
  target: Target = { stageId: 5 },
  extra: { generatorWarnings?: string[]; initialPanel?: "issues" } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CVBrandedEditModal open onOpenChange={() => {}} candidateName="Osoba Testowa" {...target} {...extra} />
    </QueryClientProvider>,
  );
  await screen.findByTestId("paper");
}

// Po etykiecie, nie po roli: przycisk w pasku też nazywa się „Do poprawy (N)”.
const panel = () => screen.getByLabelText("Do poprawy", { selector: "aside" });
const sourcesShown = () => screen.queryByLabelText("Źródła CV", { selector: "aside" }) != null;

beforeEach(() => {
  Object.assign(state, {
    width: 1280,
    status: "draft",
    revision: 4,
    html: "<p>Treść CV</p>",
    newDrafts: 0,
    failNewDraft: false,
    count: { total: 3, blocking: 1, state: "ready" },
    drafted: [],
    issuesProps: [],
    historyOptions: null,
  });
  toast.showError.mockClear();
});

afterEach(() => vi.restoreAllMocks());

it("laptop 1280: są uwagi — obok kartki staje „Do poprawy”, źródła ustępują; przełącznik zamienia je miejscami", async () => {
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(sourcesShown()).toBe(false);
  expect(screen.getByRole("button", { name: "Do poprawy (3)" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "Pokaż źródła" }));
  expect(sourcesShown()).toBe(true);
  // Panel zostaje zamontowany (liczy znaczniki i licznik), tylko go nie widać.
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("issues")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Do poprawy (3)" }));
  expect(panel()).not.toHaveAttribute("hidden");
  expect(sourcesShown()).toBe(false);

  // Zamknięcie panelu przywraca źródła — nie zostaje sama kartka z dwoma zamkniętymi panelami.
  fireEvent.click(screen.getByRole("button", { name: "Do poprawy (3)" }));
  expect(panel()).toHaveAttribute("hidden");
  expect(sourcesShown()).toBe(true);
});

it("bez uwag źródła zostają otwarte, a licznik w pasku pokazuje zero", async () => {
  state.count = { total: 0, blocking: 0, state: "ready" };
  await open();
  expect(await screen.findByRole("button", { name: "Do poprawy (0)" })).toHaveAttribute("aria-pressed", "false");
  expect(sourcesShown()).toBe(true);
  expect(panel()).toHaveAttribute("hidden");
});

it("QC nie odpowiada: panel otwiera się sam, a licznik pokazuje „?”, nie zero", async () => {
  state.count = { total: 0, blocking: 0, state: "failed" };
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(screen.getByRole("button", { name: "Do poprawy (?)" })).toHaveAttribute("aria-pressed", "true");
});

it("QC jeszcze się liczy: przycisk bez liczby, źródła zostają", async () => {
  state.count = { total: 0, blocking: 0, state: "loading" };
  await open();
  expect(await screen.findByRole("button", { name: "Do poprawy" })).toHaveAttribute("aria-pressed", "false");
  expect(sourcesShown()).toBe(true);
});

it("„Sprawdź i popraw” z karty: „Do poprawy” od razu, także bez uwag i zanim QC się policzy", async () => {
  state.count = { total: 0, blocking: 0, state: "loading" };
  await open({ stageId: 5 }, { initialPanel: "issues" });
  expect(panel()).not.toHaveAttribute("hidden");
  expect(sourcesShown()).toBe(false);
  expect(screen.getByRole("button", { name: "Do poprawy" })).toHaveAttribute("aria-pressed", "true");
});

it("wąski ekran z „Sprawdź i popraw”: kolumna „Do poprawy” zamiast kartki", async () => {
  state.width = 768;
  await open({ stageId: 5 }, { initialPanel: "issues" });
  expect(panel()).not.toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).toHaveAttribute("hidden");
});

it("szeroki ekran (1540+) mieści oba panele naraz", async () => {
  state.width = 1600;
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(sourcesShown()).toBe(true);
});

it("wąski ekran: trzeci przełącznik kolumny, a „pokaż kartkę” wraca do CV", async () => {
  state.width = 768;
  await open();
  const toggle = await screen.findByRole("button", { name: "Do poprawy (3)" });
  expect(panel()).toHaveAttribute("hidden");
  fireEvent.click(toggle);
  expect(panel()).not.toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).toHaveAttribute("hidden");

  fireEvent.click(screen.getByRole("button", { name: "pokaż kartkę" }));
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");
});

it("panel dostaje wersję zapisaną na serwerze i wie, czy są niezapisane zmiany", async () => {
  await open();
  await waitFor(() => expect(state.issuesProps.length).toBeGreaterThan(0));
  expect(state.issuesProps.at(-1)).toMatchObject({ stageId: 5, savedRevision: 4, unsaved: false, readOnly: false });
  state.html = "<p>Treść CV po zmianie</p>";
  act(() => state.onUpdate?.());
  await waitFor(() => expect(state.issuesProps.at(-1)).toMatchObject({ unsaved: true }));
});

it("wynik generatora: panel tylko z uwagami z listy; bez nich nie ma panelu ani przycisku", async () => {
  await open({ generatedId: 9 }, { generatorWarnings: ["MUST-HAVE: brak."] });
  await waitFor(() => expect(state.issuesProps.length).toBeGreaterThan(0));
  expect(state.issuesProps.at(-1)).toMatchObject({ stageId: undefined, generatorWarnings: ["MUST-HAVE: brak."] });
});

it("wynik generatora otwarty bez uwag z listy (np. z okna QC) nie ma panelu", async () => {
  await open({ generatedId: 9 });
  expect(screen.queryByTestId("issues")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Do poprawy/ })).not.toBeInTheDocument();
});

it("poprawka na zatwierdzonej wersji: najpierw nowy szkic, dopiero potem zgoda na zmianę", async () => {
  state.status = "finalized";
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "załóż szkic" }));
  await waitFor(() => expect(state.drafted).toEqual([true]));
  expect(state.newDrafts).toBe(1);
  // Szkic już jest — kolejna poprawka nie zakłada następnego.
  fireEvent.click(screen.getByRole("button", { name: "załóż szkic" }));
  await waitFor(() => expect(state.drafted).toEqual([true, true]));
  expect(state.newDrafts).toBe(1);
});

it("nie udało się założyć szkicu — poprawka nie rusza zatwierdzonej treści", async () => {
  state.status = "finalized";
  state.failNewDraft = true;
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "załóż szkic" }));
  await waitFor(() => expect(state.drafted).toEqual([false]));
  expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("Nie udało się utworzyć nowej wersji"));
});

// ── Panel „Historia” (PR 5) ──────────────────────────────────────────────────

const historyButton = () => screen.getByRole("button", { name: "Historia", pressed: false });
const historyShown = () => screen.queryByTestId("history") != null;

it("laptop 1280: „Historia” staje po prawej zamiast „Do poprawy” i źródeł; zamknięcie przywraca układ", async () => {
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  fireEvent.click(historyButton());
  expect(historyShown()).toBe(true);
  // Jeden panel naraz: „Do poprawy” zostaje zamontowany, ale ukryty; źródła ustępują.
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("issues")).toBeInTheDocument();
  expect(sourcesShown()).toBe(false);
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");

  fireEvent.click(screen.getByRole("button", { name: "Historia", pressed: true }));
  expect(historyShown()).toBe(false);
  expect(panel()).not.toHaveAttribute("hidden");
});

it("przy otwartej historii „Do poprawy” nie udaje aktywnego; klik w nie zamyka historię i pokazuje uwagi", async () => {
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  const issuesButton = () => screen.getByRole("button", { name: /^Do poprawy/ });
  expect(issuesButton()).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(historyButton());
  // Panel „Do poprawy” jest schowany, więc jego przycisk nie wygląda na włączony.
  expect(issuesButton()).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(issuesButton());
  expect(historyShown()).toBe(false);
  expect(panel()).not.toHaveAttribute("hidden");
  expect(issuesButton()).toHaveAttribute("aria-pressed", "true");
});

it("szeroki ekran (1540+): źródła zostają obok historii", async () => {
  state.width = 1600;
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Historia" }));
  expect(historyShown()).toBe(true);
  expect(sourcesShown()).toBe(true);
  expect(panel()).toHaveAttribute("hidden");
});

it("wąski ekran: kolumna „Historia” wybiera się sama, a po zamknięciu wraca kartka", async () => {
  state.width = 768;
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Historia" }));
  const columns = screen.getByRole("group", { name: "Kolumna" });
  expect(within(columns).getByRole("button", { name: "Historia" })).toHaveAttribute("aria-pressed", "true");
  expect(historyShown()).toBe(true);
  expect(screen.getByTestId("paper").closest(".cv-paper")).toHaveAttribute("hidden");
  // „Do poprawy” nie ma wtedy własnej kolumny — jak przy planie zmian.
  expect(within(columns).queryByRole("button", { name: /Do poprawy/ })).toBeNull();

  // Kartkę można obejrzeć bez zamykania historii.
  fireEvent.click(within(columns).getByRole("button", { name: "CV" }));
  expect(historyShown()).toBe(false);
  expect(within(columns).getByRole("button", { name: "Historia" })).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(within(columns).getByRole("button", { name: "Historia" }));
  expect(historyShown()).toBe(true);

  fireEvent.click(screen.getAllByRole("button", { name: "Historia", pressed: true })[0]);
  expect(historyShown()).toBe(false);
  expect(within(columns).queryByRole("button", { name: "Historia" })).toBeNull();
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");
});

it("historia i polecenie wykluczają się: otwarcie jednego zamyka drugie", async () => {
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Polecenie" }));
  expect(screen.getByRole("form", { name: "Polecenie dla całego CV" })).toBeInTheDocument();

  fireEvent.click(historyButton());
  expect(historyShown()).toBe(true);
  expect(screen.queryByRole("form", { name: "Polecenie dla całego CV" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Polecenie" }));
  expect(screen.getByRole("form", { name: "Polecenie dla całego CV" })).toBeInTheDocument();
  expect(historyShown()).toBe(false);
});

it("historia jest tylko dla CV etapu; pobranie starszej wersji niesie jej numer w nazwie pliku", async () => {
  const { downloadAuthenticatedFile } = await import("@/lib/authenticated-files");
  await open();
  await screen.findByRole("button", { name: "Historia" });
  expect(state.historyOptions).toMatchObject({ stageId: 5, disabled: false });
  // Wersja, którą etap pokazuje teraz (2), ma nazwę jak przycisk w nagłówku.
  await state.historyOptions!.downloadVersion(2);
  await state.historyOptions!.downloadVersion(1);
  expect(vi.mocked(downloadAuthenticatedFile).mock.calls.map(([path, name]) => [path.split("?")[0], name])).toEqual([
    ["/api/candidates/stages/5/cv/branded/versions/2/docx", "CV.docx"],
    ["/api/candidates/stages/5/cv/branded/versions/1/docx", "CV_v1.docx"],
  ]);
});

it("wynik generatora nie ma przycisku „Historia”", async () => {
  await open({ generatedId: 9 }, { generatorWarnings: ["MUST-HAVE: brak."] });
  await waitFor(() => expect(state.issuesProps.length).toBeGreaterThan(0));
  expect(screen.queryByRole("button", { name: "Historia" })).toBeNull();
  expect(state.historyOptions).toMatchObject({ stageId: undefined });
});
