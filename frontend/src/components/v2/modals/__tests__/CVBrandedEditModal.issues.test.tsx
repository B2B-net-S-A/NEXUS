/**
 * Okno edytora CV a panel „Do poprawy” (Edytor CV 2, PR 2): który panel stoi
 * obok kartki przy danej szerokości, licznik w pasku i szkic zakładany przed
 * poprawką na zatwierdzonej wersji. Sam panel ma własny test
 * (`cv-editor/__tests__/CvEditorIssues.test.tsx`).
 */

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("@/components/v2/cv-editor/CvEditorWordPreview", () => ({ CvEditorWordPreview: () => null }));
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

async function open(target: Target = { stageId: 5 }, extra: { generatorWarnings?: string[] } = {}) {
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
