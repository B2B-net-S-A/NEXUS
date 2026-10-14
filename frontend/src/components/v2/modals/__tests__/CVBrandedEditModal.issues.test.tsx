/**
 * Okno edytora CV a panel „Do poprawy” (Edytor CV 2, PR 2): kolumna obok
 * kartki, licznik i szkic zakładany przed poprawką na zatwierdzonej wersji.
 * Sam panel ma własny test (`cv-editor/__tests__/CvEditorIssues.test.tsx`).
 *
 * PR 5: to samo dla panelu „Historia” — gdzie staje i jak wyklucza się
 * z poleceniem. Sam panel: `cv-editor/__tests__/CvEditorHistory.test.tsx`.
 *
 * Edytor CV 3, PR 3: JEDNA kolumna obok kartki — „Do poprawy” albo oryginał
 * („Oryginał” w nagłówku); historia i plan zajmują ją na czas decyzji.
 * „Pogrub wymagania (N)” w pasku woła poprawkę panelu, „Więcej” ma polecenie,
 * historię, „Pobierz PDF” i „Drukuj”.
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
  count: { total: 3, blocking: 1, state: "ready" } as {
    total: number;
    blocking: number;
    state: "loading" | "ready" | "failed";
    qc?: { checks: Array<{ key: string; status: string; items: Array<{ fix?: string }> }> } | null;
  },
  drafted: [] as boolean[],
  issuesProps: [] as Array<Record<string, unknown>>,
  historyOptions: null as null | { stageId?: number; disabled: boolean; downloadVersion: (version: number) => Promise<void> },
  bolded: 0,
  // Prawdziwy `useCvHistory` jest wyłączony, dopóki nie ma edytora (Tiptap rysuje się po pierwszym renderze).
  historyReady: true,
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
// Pasek ma własny test; atrapa pokazuje pozycje „Więcej” z okna i „Pogrub wymagania”.
vi.mock("@/components/v2/cv-editor/CvEditorToolbar", () => ({
  CvEditorToolbar: (props: {
    moreGroups?: Array<Array<{ label: string; onSelect: () => void; disabled?: boolean }>>;
    boldRequirements?: { count: number | null; disabled: boolean; onRun: () => void };
  }) => (
    <div data-testid="toolbar">
      {props.boldRequirements ? (
        <button
          disabled={props.boldRequirements.disabled || !props.boldRequirements.count}
          onClick={props.boldRequirements.onRun}
        >
          {`Pogrub wymagania (${props.boldRequirements.count ?? "–"})`}
        </button>
      ) : null}
      {(props.moreGroups ?? []).flat().map((item) => (
        <button key={item.label} disabled={item.disabled} onClick={item.onSelect}>
          {item.label}
        </button>
      ))}
    </div>
  ),
}));
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
      const enabled = options.stageId != null && !options.disabled && state.historyReady;
      return {
        enabled,
        open,
        busy: false,
        // Jak prawdziwy hook: wyłączona historia ignoruje „pokaż”.
        show: () => {
          if (enabled) setOpen(true);
        },
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
  const { useEffect, useImperativeHandle } = await import("react");
  return {
    CvEditorIssues: (props: {
      onCount?: (count: typeof state.count) => void;
      ensureDraft: () => Promise<boolean>;
      onShowCv: () => void;
      ref?: import("react").Ref<{ boldRequirements: () => void }>;
    }) => {
      state.issuesProps.push(props as unknown as Record<string, unknown>);
      const { onCount } = props;
      useEffect(() => onCount?.(state.count), [onCount]);
      useImperativeHandle(props.ref, () => ({ boldRequirements: () => { state.bolded += 1; } }));
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
  fetchAuthenticatedDownload: vi.fn(),
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
  extra: { generatorWarnings?: string[]; initialPanel?: "issues" | "history" } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CVBrandedEditModal open onOpenChange={() => {}} candidateName="Osoba Testowa" {...target} {...extra} />
    </QueryClientProvider>,
  );
  await screen.findByTestId("paper");
}

// Po etykiecie, nie po roli: przełącznik kolumny na wąskim ekranie też nazywa się „Do poprawy (N)”.
const panel = () => screen.getByLabelText("Do poprawy", { selector: "aside" });
const sourcesShown = () => screen.queryByLabelText("Źródła CV", { selector: "aside" }) != null;
const original = () => screen.getByRole("button", { name: "Oryginał" });

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
    bolded: 0,
    historyReady: true,
  });
  toast.showError.mockClear();
});

afterEach(() => vi.restoreAllMocks());

it("laptop 1280: obok kartki jedna kolumna „Do poprawy”; „Oryginał” zamienia ją na źródła i z powrotem", async () => {
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(sourcesShown()).toBe(false);
  expect(original()).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(original());
  expect(sourcesShown()).toBe(true);
  expect(original()).toHaveAttribute("aria-pressed", "true");
  // Panel zostaje zamontowany (liczy znaczniki i licznik), tylko go nie widać.
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("issues")).toBeInTheDocument();

  fireEvent.click(original());
  expect(panel()).not.toHaveAttribute("hidden");
  expect(sourcesShown()).toBe(false);
});

it.each([
  ["bez uwag", { total: 0, blocking: 0, state: "ready" }],
  ["QC nie odpowiada", { total: 0, blocking: 0, state: "failed" }],
  ["QC jeszcze się liczy", { total: 0, blocking: 0, state: "loading" }],
] as const)("%s: kolumna i tak pokazuje „Do poprawy” — awaria nie chowa się za źródłami", async (_label, count) => {
  state.count = { ...count };
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(sourcesShown()).toBe(false);
});

it("„Sprawdź i popraw” z karty: „Do poprawy” od razu, także zanim QC się policzy", async () => {
  state.count = { total: 0, blocking: 0, state: "loading" };
  await open({ stageId: 5 }, { initialPanel: "issues" });
  expect(panel()).not.toHaveAttribute("hidden");
  expect(sourcesShown()).toBe(false);
});

it("wąski ekran z „Sprawdź i popraw”: kolumna „Do poprawy” zamiast kartki", async () => {
  state.width = 768;
  await open({ stageId: 5 }, { initialPanel: "issues" });
  expect(panel()).not.toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).toHaveAttribute("hidden");
});

it("szeroki ekran (1600): nadal jedna kolumna obok kartki", async () => {
  state.width = 1600;
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  expect(sourcesShown()).toBe(false);
});

it("wąski ekran: przełącznik kolumny, a „pokaż kartkę” wraca do CV", async () => {
  state.width = 768;
  await open();
  const columns = await screen.findByRole("group", { name: "Kolumna" });
  const toggle = within(columns).getByRole("button", { name: "Do poprawy (3)" });
  expect(panel()).toHaveAttribute("hidden");
  // Na wąskim ekranie „Oryginał” jest przełącznikiem kolumny, nie przyciskiem w nagłówku.
  expect(within(columns).getByRole("button", { name: "Oryginał" })).toBeInTheDocument();
  fireEvent.click(toggle);
  expect(panel()).not.toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).toHaveAttribute("hidden");

  fireEvent.click(screen.getByRole("button", { name: "pokaż kartkę" }));
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");
});

it("„Pogrub wymagania (N)”: liczba z QC (must i nice), klik woła poprawkę panelu", async () => {
  state.count = {
    total: 2,
    blocking: 0,
    state: "ready",
    qc: {
      checks: [
        { key: "must_bolded", status: "fail", items: [{ fix: "bold_all" }, { fix: "bold_all" }] },
        { key: "nice_bolded", status: "fail", items: [{ fix: "bold_all" }] },
        { key: "spelling", status: "fail", items: [{ fix: "spelling" }] },
      ],
    },
  };
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Pogrub wymagania (3)" }));
  expect(state.bolded).toBe(1);
});

it("„Pogrub wymagania” bez wyniku QC nie ma liczby i nie działa", async () => {
  state.count = { total: 0, blocking: 0, state: "loading" };
  await open();
  expect(await screen.findByRole("button", { name: "Pogrub wymagania (–)" })).toBeDisabled();
});

it("„Pobierz PDF” z „Więcej”: PDF szkicu z bieżącej treści z intencją pobrania", async () => {
  const files = await import("@/lib/authenticated-files");
  vi.mocked(files.postAuthenticatedDownload).mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "SZKIC_CV.pdf" });
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Pobierz PDF" }));
  await waitFor(() =>
    expect(files.postAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/5/cv/branded/preview-pdf?intent=download&surface=editor",
      { content_html: "<p>Treść CV</p>", expected_revision: 4 },
    ),
  );
  await waitFor(() => expect(files.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "SZKIC_CV.pdf"));
});

it("„Pobierz PDF” na zatwierdzonej wersji bierze PDF tej wersji", async () => {
  const files = await import("@/lib/authenticated-files");
  vi.mocked(files.fetchAuthenticatedDownload).mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "CV.pdf" });
  state.status = "finalized";
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Pobierz PDF" }));
  await waitFor(() =>
    expect(files.fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/5/cv/branded/versions/2/pdf?intent=download&surface=editor",
    ),
  );
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

it("wynik generatora otwarty bez uwag z listy (np. z okna QC): kolumnę zajmuje oryginał", async () => {
  await open({ generatedId: 9 });
  expect(screen.queryByTestId("issues")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Do poprawy/ })).not.toBeInTheDocument();
  expect(sourcesShown()).toBe(true);
  // „Oryginał” chowa kolumnę — kartka zostaje sama.
  fireEvent.click(original());
  expect(sourcesShown()).toBe(false);
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

const historyButton = () => screen.getByRole("button", { name: "Historia wersji" });
const closeHistory = () => screen.getByRole("button", { name: "Zamknij historię wersji" });
const historyShown = () => screen.queryByTestId("history") != null;

it("laptop 1280: historia zajmuje kolumnę zamiast „Do poprawy”; zamknięcie przywraca uwagi", async () => {
  await open();
  await waitFor(() => expect(panel()).not.toHaveAttribute("hidden"));
  fireEvent.click(historyButton());
  expect(historyShown()).toBe(true);
  // Jedna kolumna: „Do poprawy” zostaje zamontowany, ale ukryty.
  expect(panel()).toHaveAttribute("hidden");
  expect(screen.getByTestId("issues")).toBeInTheDocument();
  expect(sourcesShown()).toBe(false);
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");

  fireEvent.click(closeHistory());
  expect(historyShown()).toBe(false);
  expect(panel()).not.toHaveAttribute("hidden");
});

it("przy otwartej historii „Oryginał” zamyka ją i pokazuje oryginał", async () => {
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Historia wersji" }));
  expect(original()).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(original());
  expect(historyShown()).toBe(false);
  expect(sourcesShown()).toBe(true);
  expect(original()).toHaveAttribute("aria-pressed", "true");
});

it("„Historia wersji” z menu karty otwiera edytor od razu na historii", async () => {
  await open({ stageId: 5 }, { initialPanel: "history" });
  await waitFor(() => expect(historyShown()).toBe(true));
  expect(panel()).toHaveAttribute("hidden");
});

it("„Historia wersji” z karty czeka, aż historia będzie gotowa (CV z pamięci karty, edytor jeszcze się rysuje)", async () => {
  state.historyReady = false;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Nowy element przy każdym renderze — ten sam obiekt React pominąłby.
  const view = () => (
    <QueryClientProvider client={client}>
      <CVBrandedEditModal open onOpenChange={() => {}} candidateName="Osoba Testowa" stageId={5} initialPanel="history" />
    </QueryClientProvider>
  );
  const { rerender } = render(view());
  await screen.findByTestId("paper");
  expect(historyShown()).toBe(false);
  state.historyReady = true;
  rerender(view());
  await waitFor(() => expect(historyShown()).toBe(true));
});

it("wąski ekran: kolumna „Historia” wybiera się sama, a po zamknięciu wraca kartka", async () => {
  state.width = 768;
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Historia wersji" }));
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

  fireEvent.click(closeHistory());
  expect(historyShown()).toBe(false);
  expect(within(columns).queryByRole("button", { name: "Historia" })).toBeNull();
  expect(screen.getByTestId("paper").closest(".cv-paper")).not.toHaveAttribute("hidden");
});

it("historia i polecenie wykluczają się: otwarcie jednego zamyka drugie", async () => {
  await open();
  fireEvent.click(await screen.findByRole("button", { name: "Polecenie dla całego CV" }));
  expect(screen.getByRole("form", { name: "Polecenie dla całego CV" })).toBeInTheDocument();

  fireEvent.click(historyButton());
  expect(historyShown()).toBe(true);
  expect(screen.queryByRole("form", { name: "Polecenie dla całego CV" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Polecenie dla całego CV" }));
  expect(screen.getByRole("form", { name: "Polecenie dla całego CV" })).toBeInTheDocument();
  expect(historyShown()).toBe(false);
});

it("historia jest tylko dla CV etapu; pobranie starszej wersji niesie jej numer w nazwie pliku", async () => {
  const { downloadAuthenticatedFile } = await import("@/lib/authenticated-files");
  await open();
  await screen.findByRole("button", { name: "Historia wersji" });
  expect(state.historyOptions).toMatchObject({ stageId: 5, disabled: false });
  // Wersja, którą etap pokazuje teraz (2), ma nazwę jak przycisk w nagłówku.
  await state.historyOptions!.downloadVersion(2);
  await state.historyOptions!.downloadVersion(1);
  expect(vi.mocked(downloadAuthenticatedFile).mock.calls.map(([path, name]) => [path.split("?")[0], name])).toEqual([
    ["/api/candidates/stages/5/cv/branded/versions/2/docx", "CV.docx"],
    ["/api/candidates/stages/5/cv/branded/versions/1/docx", "CV_v1.docx"],
  ]);
});

it("wynik generatora nie ma „Historia wersji” ani „Pogrub wymagania”", async () => {
  await open({ generatedId: 9 }, { generatorWarnings: ["MUST-HAVE: brak."] });
  await waitFor(() => expect(state.issuesProps.length).toBeGreaterThan(0));
  expect(screen.queryByRole("button", { name: "Historia wersji" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Pogrub wymagania/ })).toBeNull();
  expect(state.historyOptions).toMatchObject({ stageId: undefined });
});
