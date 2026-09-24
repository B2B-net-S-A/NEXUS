import { afterEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({
  html: "<p>Old text</p>",
  stored: "<p>Old text</p>",
  snapshot: "",
  status: "draft",
  revision: 1,
  onUpdate: null as null | (() => void),
  // Werdykt niezależnej kontroli AI (0327) odsyłany przez /finalize.
  reviewStatus: null as null | string,
  reviewFindings: null as null | number,
}));

vi.mock("@tiptap/react", () => {
  const editor = {
    commands: { setContent: (html: string) => { state.html = html; } },
    setEditable: vi.fn(),
    getHTML: () => state.html,
    on: (_event: string, callback: () => void) => { state.onUpdate = callback; },
    off: () => { state.onUpdate = null; },
  };
  return {
    useEditor: () => editor,
    EditorContent: () => <textarea aria-label="audit editor" onChange={e => {
      state.html = e.target.value;
      state.onUpdate?.();
    }} />,
  };
});
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/authenticated-files", () => ({ openAuthenticatedFile: vi.fn(), downloadAuthenticatedFile: vi.fn(),
  postAuthenticatedDownload: vi.fn(async () => ({blob: new Blob(["synthetic docx"]), filename: "SZKIC_Reviewed.docx"})),
  downloadBlob: vi.fn(),
}));
vi.mock("@/lib/api", () => {
  const adapter = {
    get: async () => ({ data: { status: state.status, content_html: state.stored,
      edit_revision: state.revision, version: 1, template: "standard", language: "pl",
      docx_available: state.status === "finalized", docx_filename: "Reviewed.docx",
      updated_at: "2026-09-09T07:00:00Z" } }),
    update: async (_id: number, body: {content_html: string}) => {
      state.stored = body.content_html;
      state.revision += 1;
      return {data: { edit_revision: state.revision }};
    },
    newDraft: async (_id: number, expected: number) => {
      expect(expected).toBe(state.revision);
      state.status = "draft";
      state.revision += 1;
      return { data: { status: "draft", content_html: state.stored, edit_revision: state.revision,
        version: 2, template: "standard", language: "pl", updated_at: "2026-09-09T07:00:00Z" } };
    },
    finalize: async (_id: number, body: {content_html: string; expected_revision: number}) => {
      expect(body.expected_revision).toBe(state.revision);
      state.snapshot = state.stored = body.content_html;
      state.status = "finalized";
      state.revision += 1;
      return {data: {
        edit_revision: state.revision,
        content_review_status: state.reviewStatus,
        content_review_findings: state.reviewFindings,
      }};
    },
  };
  return { candidateStageCvApi: { branded: adapter }, cvGeneratedEditorApi: adapter };
});

import { cvGeneratedEditorApi } from "@/lib/api";
import { CVBrandedEditModal } from "../CVBrandedEditModal";
import { downloadAuthenticatedFile, postAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("shows the source recovery error and retries loading instead of a blank editor", async () => {
  const get = vi.spyOn(cvGeneratedEditorApi, "get").mockRejectedValueOnce({
    response: { data: { detail: "Brak źródeł. Wybierz oryginalne CV i wygeneruj ponownie." } },
  });
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={()=>{}}
    generatedId={999} candidateName="Synthetic person" /></QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Wybierz oryginalne CV");
  expect(screen.queryByLabelText("audit editor")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Ponów wczytanie"}));
  await screen.findByLabelText("audit editor");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(get).toHaveBeenCalledTimes(2);
  get.mockRestore();
});


it("offers regeneration for missing assets before editor load without saving empty content", async () => {
  const get = vi.spyOn(cvGeneratedEditorApi, "get").mockRejectedValue({
    response: {data: {detail: {code: "cv_editor_assets_unavailable", message: "Brak szablonu."}}},
  });
  const update = vi.spyOn(cvGeneratedEditorApi, "update");
  const close = vi.fn();
  const regenerate = vi.fn();
  const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={queryClient}><CVBrandedEditModal open onOpenChange={close}
    generatedId={12} candidateName="Synthetic" onRegenerate={regenerate} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", {name: "Przejdź do generatora"}));
  expect(close).toHaveBeenCalledOnce();
  expect(regenerate).toHaveBeenCalledOnce();
  expect(update).not.toHaveBeenCalled();
  expect(get).toHaveBeenCalledOnce();
});

it("a persistent save error does not trap the editor: close without saving after confirmation", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.status = "draft"; state.revision = 1;
  const update = vi.spyOn(cvGeneratedEditorApi, "update").mockRejectedValue({
    response: {status: 422, data: {detail: "CV nie może być puste."}},
  });
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open generatedId={7} onOpenChange={close} candidateName="Synthetic" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p></p>"}});
  fireEvent.click(footerClose());
  expect(await screen.findByText("Nie udało się zapisać CV: CV nie może być puste.")).toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", {name: "Wczytaj aktualną wersję"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Zamknij bez zapisu"}));
  expect(await screen.findByText("Zamknąć bez zapisu?")).toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  const buttons = screen.getAllByRole("button", {name: "Zamknij bez zapisu"});
  fireEvent.click(buttons[buttons.length - 1]);
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  expect(state.stored).toBe("<p>Old text</p>");
  update.mockRestore();
});

it("after a revision conflict the recruiter can load the current version", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.status = "draft"; state.revision = 1;
  const update = vi.spyOn(cvGeneratedEditorApi, "update").mockImplementationOnce(async () => {
    // Ktoś inny zapisał w międzyczasie.
    state.stored = "<p>Colleague version</p>";
    state.revision = 5;
    throw {response: {status: 409, data: {detail: "CV zostało zmienione w innym oknie."}}};
  });
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open generatedId={7} onOpenChange={close} candidateName="Synthetic" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p>My stale edit</p>"}});
  fireEvent.click(footerClose());
  expect(await screen.findByText(/Ktoś zapisał nowszą wersję/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Wczytaj aktualną wersję"}));
  await waitFor(() => expect(state.html).toBe("<p>Colleague version</p>"));
  await waitFor(() => expect(screen.queryByText(/Ktoś zapisał nowszą wersję/)).not.toBeInTheDocument());
  expect(await screen.findByText("Zapisano")).toBeInTheDocument();
  fireEvent.click(footerClose());
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  expect(state.stored).toBe("<p>Colleague version</p>");
  update.mockRestore();
});

/** Stopka ma przycisk „Zamknij" z tekstem; krzyżyk okna ma tylko etykietę. */
function footerClose(): HTMLElement {
  const button = screen.getAllByRole("button", {name: "Zamknij"}).find(b => b.textContent?.trim() === "Zamknij");
  if (!button) throw new Error("footer close button not found");
  return button;
}


it.each(["pipeline", "standalone"])("%s „Zapisz” zapisuje ostatnią zmianę, zamyka okno i zatwierdza w tle", async (mode) => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  state.reviewStatus = "verified"; state.reviewFindings = 0;
  vi.clearAllMocks();
  const finalize = vi.spyOn(cvGeneratedEditorApi, "finalize");
  const close = vi.fn();
  const target = mode === "pipeline" ? {stageId: 21} : {generatedId: 7};
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    {...target} candidateName="Synthetic person" /></QueryClientProvider>);
  await screen.findByText("Szkic v1");
  // Jeden przycisk — bez „Zapisz i zatwierdź”, okna „Sfinalizować?” i plakietki.
  expect(screen.queryByRole("button", {name: "Zapisz i zatwierdź"})).toBeNull();
  expect(screen.queryByText("Sfinalizowane")).toBeNull();
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>New verified text</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz"}));
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  expect(screen.queryByText(/Sfinalizować/)).toBeNull();
  expect(toast.showSuccess).toHaveBeenCalledWith("Zapisano. Sprawdzamy treść w tle.");
  // Zatwierdzenie idzie PO zamknięciu okna — z ostatnią treścią i rewizją po zapisie.
  await waitFor(() => expect(state.status).toBe("finalized"));
  expect(state.snapshot).toBe("<p>New verified text</p>");
  expect(finalize).toHaveBeenCalledWith(mode === "pipeline" ? 21 : 7,
    {content_html: "<p>New verified text</p>", expected_revision: 2});
  // Bez sygnału przerwania — zamknięcie okna nie może przerwać zatwierdzenia.
  expect(finalize.mock.calls[0]).toHaveLength(2);
  await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith(
    "CV zatwierdzone (Synthetic person). Kontrola treści bez uwag."));
  finalize.mockRestore();
  state.reviewStatus = null; state.reviewFindings = null;
});

it("uwagi kontroli AI wracają toastem z liczbą — zatwierdzenie i tak przechodzi", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  state.reviewStatus = "reviewed"; state.reviewFindings = 2;
  vi.clearAllMocks();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={() => {}}
    stageId={21} candidateName="Synthetic person" /></QueryClientProvider>);
  await screen.findByText("Szkic v1");
  fireEvent.click(screen.getByRole("button", {name: "Zapisz"}));
  await waitFor(() => expect(state.status).toBe("finalized"));
  await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith(
    "CV zatwierdzone (Synthetic person). Kontrola treści zgłosiła 2 uwagi — sprawdź przed wysyłką."));
  state.reviewStatus = null; state.reviewFindings = null;
});

it("porażka zatwierdzenia w tle to toast z prośbą o ponowny zapis, szkic zostaje", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  vi.clearAllMocks();
  const finalize = vi.spyOn(cvGeneratedEditorApi, "finalize").mockRejectedValueOnce({
    response: {status: 409, data: {detail: {code: "cv_source_regeneration_required", message: "Brak zamrożonych źródeł."}}},
  });
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    generatedId={7} candidateName="Synthetic" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p>Keep me</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz"}));
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  await waitFor(() => expect(toast.showError).toHaveBeenCalledWith(
    "Nie udało się zatwierdzić — otwórz CV i zapisz ponownie. (Brak zamrożonych źródeł.)"));
  expect(state.stored).toBe("<p>Keep me</p>");
  expect(state.status).toBe("draft");
  finalize.mockRestore();
});

it("nieudany zapis NIE zamyka okna i nie zleca zatwierdzenia", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.status = "draft"; state.revision = 1;
  vi.clearAllMocks();
  const update = vi.spyOn(cvGeneratedEditorApi, "update").mockRejectedValueOnce(new Error("Save unavailable"));
  const finalize = vi.spyOn(cvGeneratedEditorApi, "finalize");
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    generatedId={7} candidateName="Synthetic" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p>Unsaved</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz"}));
  expect(await screen.findByText("Nie udało się zapisać CV: Save unavailable")).toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  expect(finalize).not.toHaveBeenCalled();
  update.mockRestore();
  finalize.mockRestore();
});

it("zatwierdzona wersja jest edytowalna: pierwsza zmiana zakłada nowy szkic i zachowuje wpisany tekst", async () => {
  state.html = state.stored = "<p>Approved</p>";
  state.snapshot = "<p>Approved</p>"; state.status = "finalized"; state.revision = 3;
  vi.clearAllMocks();
  const newDraft = vi.spyOn(cvGeneratedEditorApi, "newDraft");
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    stageId={21} candidateName="Synthetic" /></QueryClientProvider>);
  await screen.findByText(/Zatwierdzona wersja 1 — zmiana utworzy nowy szkic/);
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>Approved + fix</p>"}});
  await waitFor(() => expect(newDraft).toHaveBeenCalledWith(21, 3));
  await screen.findByText("Szkic v2");
  // Wpisany tekst przeszedł do nowego szkicu i zapisuje się razem z nim.
  expect(state.html).toBe("<p>Approved + fix</p>");
  fireEvent.click(screen.getByRole("button", {name: "Zapisz"}));
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  await waitFor(() => expect(state.snapshot).toBe("<p>Approved + fix</p>"));
  newDraft.mockRestore();
});

it("etap bez CV: „Najpierw wygeneruj CV” zamiast pustego edytora i przejście do generatora", async () => {
  state.status = "none"; state.stored = ""; state.revision = 0;
  vi.clearAllMocks();
  const regenerate = vi.fn();
  const close = vi.fn();
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    stageId={21} candidateName="Synthetic" onRegenerate={regenerate} /></QueryClientProvider>);
  expect(await screen.findByText("Najpierw wygeneruj CV")).toBeInTheDocument();
  expect(screen.queryByLabelText("audit editor")).toBeNull();
  expect(screen.getByRole("button", {name: "Zapisz"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: /Wygeneruj CV/}));
  expect(close).toHaveBeenCalledWith(false);
  expect(regenerate).toHaveBeenCalledOnce();
  state.status = "draft";
});

it.each(["pipeline", "standalone"])("%s pobiera szkic DOCX z bieżącą treścią i zatwierdzony DOCX wersji", async (mode) => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  vi.clearAllMocks();
  const target = mode === "pipeline" ? {stageId: 21} : {generatedId: 7};
  const base = mode === "pipeline" ? "/api/candidates/stages/21/cv/branded" : "/api/cv-generator/generated/7/editor";
  vi.useFakeTimers({toFake: ["setInterval", "clearInterval"]});
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const view = render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={()=>{}}
    {...target} candidateName="Synthetic person" jobTitle="Synthetic job" /></QueryClientProvider>);
  await screen.findByText("Szkic v1");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>New verified text</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Pobierz szkic DOCX"}));
  await waitFor(() => expect(postAuthenticatedDownload).toHaveBeenCalledWith(
    `${base}/preview-docx`,
    {content_html: "<p>New verified text</p>", expected_revision: 1},
  ));
  await waitFor(() => expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "SZKIC_Reviewed.docx"));
  expect(state.stored).toBe("<p>Old text</p>");
  view.unmount();

  state.status = "finalized";
  const qc2 = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc2}><CVBrandedEditModal open onOpenChange={()=>{}}
    {...target} candidateName="Synthetic person" /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", {name: "Pobierz zatwierdzony DOCX v1"}));
  await waitFor(() => expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
    `${base}/versions/1/docx`, "Reviewed.docx",
  ));
  state.status = "draft";
});
