/**
 * Edytor CV: przekazanie Delivery Leadowi ze stopki (D6, 14.10.2026).
 *
 * Z propem `handoff` stopka ma „Uwaga dla Delivery Leada”, stan QC, „Zapisz”
 * i „Zapisz i przekaż do DL →”. Zapis jest ten sam co „Zapisz”, ruch karty
 * robi wołający, a zatwierdzenie w tle rusza dopiero po udanym ruchu. Blokady
 * QC zamieniają przycisk w „Przekaż mimo uwag…” (okno obejścia QC). Panel
 * „Do poprawy” jest atrapą — jego licznik (z wynikiem QC) podaje test.
 */

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { QcCheck, QcResult } from "@/lib/api/cvQc";

const state = vi.hoisted(() => ({
  status: "draft",
  revision: 4,
  html: "<p>Treść CV</p>",
  onUpdate: null as null | (() => void),
  count: { total: 3, blocking: 0, state: "ready" } as {
    total: number;
    blocking: number;
    state: "loading" | "ready" | "failed";
    qc?: unknown;
  },
  calls: [] as string[],
  updates: [] as string[],
  overridePosts: [] as Array<[string, unknown]>,
}));

vi.mock("@/lib/use-element-width", () => ({ useElementWidth: () => 1280 }));
vi.mock("@tiptap/react", () => {
  const editor = {
    commands: { setContent: (html: string) => { state.html = html; } },
    setEditable: vi.fn(),
    getHTML: () => state.html,
    isDestroyed: false,
    on: (_event: string, callback: () => void) => { state.onUpdate = callback; },
    off: () => { state.onUpdate = null; },
  };
  return {
    useEditor: () => editor,
    EditorContent: () => (
      <textarea
        aria-label="treść"
        onChange={(event) => {
          state.html = event.target.value;
          state.onUpdate?.();
        }}
      />
    ),
  };
});
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));
vi.mock("@/lib/cv-editor-structure", () => ({
  cvEditorExtensions: () => [],
  loadCvHtml: (editor: { commands: { setContent: (html: string) => void } }, html: string) =>
    editor.commands.setContent(html),
}));
vi.mock("@/components/v2/cv-editor/CvEditorToolbar", () => ({ CvEditorToolbar: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorSources", () => ({ CvEditorSources: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorSelectionAi", () => ({ CvEditorSelectionAi: () => null }));
vi.mock("@/components/v2/cv-editor/useCvCommandPlan", () => ({
  useCvCommandPlan: () => ({ enabled: false, phase: "idle", locked: false, discard: () => undefined }),
}));
vi.mock("@/components/v2/cv-editor/useCvSelectionAi", () => ({
  useCvSelectionAi: () => ({ enabled: false, selection: { ok: false, reason: null, hidden: true }, phase: "idle" }),
}));
vi.mock("@/components/v2/cv-editor/useCvHistory", () => ({
  useCvHistory: () => ({ enabled: false, open: false, busy: false, show: () => undefined, close: () => undefined }),
}));
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({ CvPagesPreview: () => null }));
vi.mock("@/components/v2/cv-editor/CvEditorIssues", async () => {
  const { useEffect } = await import("react");
  return {
    CvEditorIssues: ({ onCount }: { onCount?: (count: typeof state.count) => void }) => {
      useEffect(() => onCount?.(state.count), [onCount]);
      return <div data-testid="issues" />;
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
    updated_at: "2026-10-14T07:00:00Z",
  });
  const adapter = {
    get: async () => ({ data: body() }),
    update: async (_id: number, payload: { content_html: string }) => {
      state.calls.push("save");
      state.updates.push(payload.content_html);
      state.revision += 1;
      return { data: body() };
    },
    newDraft: async () => ({ data: body() }),
    finalize: async () => {
      state.calls.push("approve");
      return { data: { edit_revision: state.revision, content_review_findings: 0, content_review_status: "verified" } };
    },
  };
  return {
    __esModule: true,
    // Okno obejścia QC (`useQcOverride`) pisze przez domyślny klient API.
    default: {
      post: async (url: string, payload: unknown) => {
        state.calls.push("override");
        state.overridePosts.push([url, payload]);
        return { data: { ...(state.count.qc as object), override: { reason: "Klient prosił o krótsze CV" } } };
      },
    },
    candidateStageCvApi: { branded: adapter },
    cvGeneratedEditorApi: adapter,
  };
});

import { CVBrandedEditModal } from "../CVBrandedEditModal";
import type { CvEditorHandoff } from "@/lib/cv-editor-handoff";

function qc(over: Partial<QcResult> = {}): QcResult {
  const blockingCheck: QcCheck = {
    key: "no_unsupported",
    label: "Zgodność z oryginałem",
    severity: "blocking",
    status: "fail",
    summary: null,
    items: [{ term: "Jenkins", fix: "remove_term", detail: "Nie ma tego w oryginale." }],
  };
  return {
    stage_id: 5,
    candidate_id: 11,
    candidate_name: "Anna Przykładowa",
    job_id: 21,
    job_title: "Senior Java Developer",
    client_name: null,
    passed: false,
    blocking_failed: 1,
    warnings_count: 2,
    override: null,
    advisory: true,
    can_override: true,
    run_id: null,
    computed_at: null,
    cv: null,
    original_cv: { source: null, filename: null, text: null },
    client_request: { must: [], nice: [], critical: [], critical_source: "none" },
    checks: [blockingCheck],
    ...over,
  };
}

function setup(handoff?: Partial<CvEditorHandoff> | null) {
  const onOpenChange = vi.fn();
  const onSaveAndHandOff = vi.fn(async (_remark: string) => {
    state.calls.push("move");
    return true;
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CVBrandedEditModal
        open
        onOpenChange={onOpenChange}
        stageId={5}
        candidateName="Anna Przykładowa"
        handoff={handoff === null ? undefined : { onSaveAndHandOff, ...handoff }}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange, onSaveAndHandOff };
}

const bar = () => screen.getByRole("group", { name: "Przekazanie Delivery Leadowi" });

beforeEach(() => {
  Object.assign(state, {
    status: "draft",
    revision: 4,
    html: "<p>Treść CV</p>",
    count: { total: 3, blocking: 0, state: "ready", qc: qc({ passed: true, blocking_failed: 0, checks: [] }) },
    calls: [],
    updates: [],
    overridePosts: [],
  });
  toast.showSuccess.mockClear();
  toast.showError.mockClear();
});

afterEach(() => vi.restoreAllMocks());

it("bez `handoff` edytor jest jak dotąd: „Zapisz” w pasku, bez stopki przekazania", async () => {
  setup(null);
  await screen.findByLabelText("treść");
  expect(screen.queryByRole("group", { name: "Przekazanie Delivery Leadowi" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Zapisz" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Zapisz i przekaż do DL/ })).not.toBeInTheDocument();
});

it("nic nie blokuje: zapis jak „Zapisz”, ruch z uwagą, zamknięcie, zatwierdzenie w tle po ruchu", async () => {
  const { onOpenChange, onSaveAndHandOff } = setup();
  fireEvent.change(await screen.findByLabelText("treść"), { target: { value: "<p>Poprawione CV</p>" } });
  expect(within(bar()).getByRole("status")).toHaveTextContent("3 rzeczy do decyzji · nic nie blokuje wysyłki");
  // „Zapisz” jest w stopce — nie drugi raz w pasku.
  expect(screen.getAllByRole("button", { name: "Zapisz" })).toHaveLength(1);
  fireEvent.change(within(bar()).getByRole("textbox", { name: "Uwaga dla Delivery Leada (opcjonalnie)" }), {
    target: { value: "  Kandydat dostępny od listopada.  " },
  });
  fireEvent.click(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ }));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(onSaveAndHandOff).toHaveBeenCalledWith("Kandydat dostępny od listopada.");
  expect(state.updates.at(-1)).toBe("<p>Poprawione CV</p>");
  await waitFor(() => expect(state.calls).toEqual(["save", "move", "approve"]));
  expect(toast.showSuccess).toHaveBeenCalledWith("Anna — przekazano Delivery Leadowi. Sprawdzamy treść CV w tle.");
});

it("odmowa ruchu: edytor zostaje otwarty z komunikatem, CV zapisane, bez zatwierdzenia", async () => {
  const { onOpenChange } = setup({
    onSaveAndHandOff: vi.fn(async () => {
      state.calls.push("move");
      return false;
    }),
  });
  fireEvent.change(await screen.findByLabelText("treść"), { target: { value: "<p>Poprawione CV</p>" } });
  fireEvent.change(within(bar()).getByRole("textbox", { name: "Uwaga dla Delivery Leada (opcjonalnie)" }), {
    target: { value: "Pilne" },
  });
  fireEvent.click(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ }));
  expect(await within(bar()).findByRole("alert")).toHaveTextContent("Karta nie przeszła do Delivery Leada. CV jest zapisane");
  expect(state.calls).toEqual(["save", "move"]);
  expect(onOpenChange).not.toHaveBeenCalledWith(false);
  // Uwaga zostaje w polu, dopóki edytor jest otwarty.
  expect(within(bar()).getByRole("textbox", { name: "Uwaga dla Delivery Leada (opcjonalnie)" })).toHaveValue("Pilne");
});

it("błąd sieci przy ruchu mówi, co się stało, i nie zamyka edytora", async () => {
  const { onOpenChange } = setup({
    onSaveAndHandOff: vi.fn(async () => {
      throw { response: { status: 500, data: { detail: "Serwer chwilowo niedostępny." } } };
    }),
  });
  await screen.findByLabelText("treść");
  fireEvent.click(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ }));
  expect(await within(bar()).findByRole("alert")).toHaveTextContent("Serwer chwilowo niedostępny. CV jest zapisane");
  expect(onOpenChange).not.toHaveBeenCalledWith(false);
});

it("pola w nawiasach zatrzymują przekazanie — karta się nie rusza", async () => {
  const { onSaveAndHandOff, onOpenChange } = setup();
  fireEvent.change(await screen.findByLabelText("treść"), { target: { value: "<p>[Stanowisko]</p>" } });
  fireEvent.click(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ }));
  expect(await screen.findByText(/Uzupełnij albo usuń pola w nawiasach/)).toBeInTheDocument();
  expect(onSaveAndHandOff).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalledWith(false);
});

it("blokady QC: „Przekaż mimo uwag…” → powód obejścia → zapis i ruch", async () => {
  state.count = { total: 2, blocking: 1, state: "ready", qc: qc() };
  const { onOpenChange, onSaveAndHandOff } = setup();
  fireEvent.change(await screen.findByLabelText("treść"), { target: { value: "<p>Poprawione CV</p>" } });
  expect(within(bar()).getByRole("status")).toHaveTextContent("2 rzeczy do decyzji · 1 blokuje wysyłkę");
  expect(within(bar()).queryByRole("button", { name: /Zapisz i przekaż do DL/ })).not.toBeInTheDocument();
  fireEvent.click(within(bar()).getByRole("button", { name: "Przekaż mimo uwag…" }));

  const form = await screen.findByRole("dialog", { name: "Przesuń mimo uwag QC" });
  expect(form).toHaveTextContent("Jenkins — jest w CV, a nie ma tego w oryginale");
  fireEvent.click(within(form).getByRole("radio", { name: "Klient prosił o krótsze CV" }));
  fireEvent.click(within(form).getByRole("button", { name: "Przesuń mimo uwag" }));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(state.overridePosts).toEqual([["/api/pipeline/stages/5/qc/override", { reason_code: "client_short_cv" }]]);
  expect(onSaveAndHandOff).toHaveBeenCalledWith("");
  await waitFor(() => expect(state.calls).toEqual(["override", "save", "move", "approve"]));
});

it("blokady QC poza trybem doradczym, bez prawa obejścia: przekazanie wyłączone z powodem", async () => {
  state.count = { total: 1, blocking: 1, state: "ready", qc: qc({ advisory: false, can_override: false }) };
  setup();
  await screen.findByLabelText("treść");
  const primary = within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ });
  expect(primary).toBeDisabled();
  expect(bar()).toHaveTextContent("Najpierw popraw rzeczy, które blokują wysyłkę");
  // „Zapisz” dalej działa.
  expect(within(bar()).getByRole("button", { name: "Zapisz" })).toBeEnabled();
});

it("QC przepuszczone wcześniej: zwykłe przekazanie, stan mówi o obejściu", async () => {
  state.count = {
    total: 1,
    blocking: 1,
    state: "ready",
    qc: qc({ override: { reason: "Klient prosił o krótsze CV", by_name: "Rekruter", at: "2026-10-14T08:00:00Z" } }),
  };
  setup();
  await screen.findByLabelText("treść");
  expect(within(bar()).getByRole("status")).toHaveTextContent("1 rzecz do decyzji · przepuszczone mimo uwag");
  expect(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ })).toBeEnabled();
});

it("QC się liczy: przekazanie czeka na wynik", async () => {
  state.count = { total: 0, blocking: 0, state: "loading", qc: null };
  setup();
  await screen.findByLabelText("treść");
  expect(within(bar()).getByRole("status")).toHaveTextContent("Sprawdzam CV…");
  expect(within(bar()).getByRole("button", { name: /Zapisz i przekaż do DL/ })).toBeDisabled();
});

it("wynik generatora (bez etapu) nie ma stopki nawet z `handoff`", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CVBrandedEditModal
        open
        onOpenChange={() => undefined}
        generatedId={9}
        candidateName="Anna Przykładowa"
        handoff={{ onSaveAndHandOff: async () => true }}
      />
    </QueryClientProvider>,
  );
  await screen.findByLabelText("treść");
  expect(screen.queryByRole("group", { name: "Przekazanie Delivery Leadowi" })).not.toBeInTheDocument();
});
