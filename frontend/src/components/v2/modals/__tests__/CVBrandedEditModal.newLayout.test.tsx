import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AxiosResponse } from "axios";

// Zakładki nowego CV (22.11.2026): okno decyduje, co widać i jakie dane
// dostaje formularz; formularze i podgląd mają własne testy na prawdziwym edytorze.
vi.mock("@tiptap/react", () => {
  const editor = {
    commands: { setContent: () => undefined },
    setEditable: vi.fn(),
    getHTML: () => "<p>CV</p>",
    on: () => undefined,
    off: () => undefined,
    isDestroyed: false,
  };
  return { useEditor: () => editor, EditorContent: () => <div aria-label="kartka CV" /> };
});
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));
vi.mock("@/lib/cv-editor-structure", () => ({ cvEditorExtensions: () => [], loadCvHtml: () => undefined }));
vi.mock("@/components/v2/cv-editor/CvEditorToolbar", () => ({
  CvEditorToolbar: ({ historyOnly }: { historyOnly?: boolean }) => (
    <div data-testid="toolbar" data-history-only={historyOnly ? "tak" : "nie"} />
  ),
}));
vi.mock("@/components/v2/cv-editor/CvEditorSources", () => ({ CvEditorSources: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorIssues", () => ({ CvEditorIssues: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorAssistant", () => ({ CvEditorAssistant: () => null }));
vi.mock("@/components/v2/cv-editor/useCvAssistant", () => ({
  useCvAssistant: () => ({ enabled: false, messages: [], busy: false, locked: false, send: () => undefined }),
}));
vi.mock("@/components/v2/cv-editor/useCvHistory", () => ({
  useCvHistory: () => ({ enabled: false, open: false, busy: false, show: () => undefined, close: () => undefined }),
}));
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({ CvPagesPreview: () => <div data-testid="pages" /> }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));
vi.mock("@/components/v2/cv-editor/CvNewLayoutWorkspace", () => ({
  CvNewLayoutWorkspace: ({
    tab,
    active,
    extras,
    onSaveResult,
    onRefreshWhy,
  }: {
    tab: string;
    active: boolean;
    extras: unknown;
    onSaveResult?: (patch: { result_text: string }) => Promise<void>;
    onRefreshWhy?: () => Promise<void>;
  }) => (
    <div data-testid="workspace" data-tab={tab} data-active={active ? "tak" : "nie"}>
      {JSON.stringify(extras)}
      <button type="button" onClick={() => void onSaveResult?.({ result_text: "Nowy wynik." })}>
        zapisz wynik
      </button>
      <button type="button" onClick={() => void onRefreshWhy?.()}>
        ułóż zdania
      </button>
    </div>
  ),
}));

import type { CVBrandedState } from "@/lib/api";
import { CVBrandedEditModal, type CvEditorApi } from "../CVBrandedEditModal";

afterEach(() => vi.restoreAllMocks());

function respond<T>(data: T): Promise<AxiosResponse<T>> {
  return Promise.resolve({ data } as AxiosResponse<T>);
}

function state(overrides: Partial<CVBrandedState> = {}): CVBrandedState {
  return {
    status: "draft",
    content_html: "<p>CV</p>",
    edit_revision: 1,
    version: 1,
    template: "standard",
    language: "pl",
    docx_available: false,
    new_layout_enabled: true,
    cv_layout: "new",
    page1_extras: { result_index: 0, results: [{ text: "Wynik.", verified: true }] },
    ...overrides,
  } as CVBrandedState;
}

function api(initial: CVBrandedState) {
  let current = initial;
  const setPage1 = vi.fn((_id: number, patch: { result_text?: string | null }) => {
    current = { ...current, page1_extras: { ...current.page1_extras, result_text: patch.result_text ?? null } };
    return respond(current);
  });
  const refreshPage1 = vi.fn(() => {
    const extras = { ...current.page1_extras, why: ["Zdanie z generatora.", "", ""] };
    current = { ...current, page1_extras: extras };
    return respond(extras);
  });
  const editorApi: CvEditorApi = {
    get: () => respond(current),
    update: () => respond(current),
    newDraft: () => respond(current),
    finalize: () => respond({} as never),
    setLayout: (_id, cv_layout) => {
      current = { ...current, cv_layout };
      return respond(current);
    },
    setPage1,
    refreshPage1,
  };
  return { editorApi, setPage1, refreshPage1 };
}

function renderModal(initial: CVBrandedState) {
  const backend = api(initial);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CVBrandedEditModal open onOpenChange={() => undefined} stageId={11} candidateName="Anna Przykładowa" editorApi={backend.editorApi} />
    </QueryClientProvider>,
  );
  return backend;
}

it("nowe CV: zakładki Strona 1 · Stanowiska · Cały tekst · Jak u klienta, start na Stronie 1", async () => {
  renderModal(state());
  const workspace = await screen.findByTestId("workspace");
  await waitFor(() => expect(workspace).toHaveAttribute("data-tab", "page1"));
  expect(workspace).toHaveAttribute("data-active", "tak");
  expect(screen.getByRole("button", { name: "Strona 1" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Stanowiska" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Cały tekst" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Jak u klienta" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Edycja" })).not.toBeInTheDocument();
  // Kartka zostaje zamontowana pod formularzem — w „Cały tekst” jest ten sam dokument.
  expect(screen.getByLabelText("kartka CV")).toBeInTheDocument();
  expect(screen.getByTestId("toolbar")).toHaveAttribute("data-history-only", "tak");
});

it("Stanowiska i Cały tekst przełączają formularz i kartkę bez odmontowania podglądu", async () => {
  renderModal(state());
  await waitFor(() => expect(screen.getByTestId("workspace")).toHaveAttribute("data-tab", "page1"));
  fireEvent.click(screen.getByRole("button", { name: "Stanowiska" }));
  expect(screen.getByTestId("workspace")).toHaveAttribute("data-tab", "positions");
  fireEvent.click(screen.getByRole("button", { name: "Cały tekst" }));
  const workspace = screen.getByTestId("workspace");
  expect(workspace).toHaveAttribute("data-active", "nie");
  expect(workspace.parentElement).not.toBeVisible();
  expect(screen.getByTestId("toolbar")).toHaveAttribute("data-history-only", "nie");
});

it("klasyczne CV ma edytor jak dotąd: Edycja · Jak u klienta, bez formularzy", async () => {
  renderModal(state({ cv_layout: "classic" }));
  expect(await screen.findByRole("button", { name: "Edycja" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: "Strona 1" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
});

it("wyłączona flaga = bez formularzy, nawet przy układzie „new”", async () => {
  renderModal(state({ new_layout_enabled: false }));
  expect(await screen.findByRole("button", { name: "Edycja" })).toBeInTheDocument();
  expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
});

it("„Najmocniejszy wynik” idzie do dodatków strony 1, a odpowiedź trafia do formularza", async () => {
  const { setPage1 } = renderModal(state());
  await screen.findByTestId("workspace");
  fireEvent.click(screen.getByRole("button", { name: "zapisz wynik" }));
  await waitFor(() => expect(setPage1).toHaveBeenCalledWith(11, { result_text: "Nowy wynik." }));
  await waitFor(() => expect(screen.getByTestId("workspace")).toHaveTextContent("Nowy wynik."));
});

it("„Ułóż zdania od nowa” liczy zdania strony 1 i wkłada je do formularza", async () => {
  const { refreshPage1 } = renderModal(state());
  await screen.findByTestId("workspace");
  fireEvent.click(screen.getByRole("button", { name: "ułóż zdania" }));
  await waitFor(() => expect(refreshPage1).toHaveBeenCalledWith(11));
  await waitFor(() => expect(screen.getByTestId("workspace")).toHaveTextContent("Zdanie z generatora."));
});
