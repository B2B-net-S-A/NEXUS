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
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));
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
    cancelReview: async () => ({data: {review_id: 9, status: "cancelled", error_code: null}}),
    finalize: async (_id: number, body: {content_html: string; expected_revision: number}) => {
      expect(body.expected_revision).toBe(state.revision);
      state.snapshot = state.stored = body.content_html;
      state.status = "finalized";
      state.revision += 1;
      return {data: { edit_revision: state.revision }};
    },
  };
  return { candidateStageCvApi: { branded: adapter }, cvGeneratedEditorApi: adapter };
});

import { cvGeneratedEditorApi } from "@/lib/api";
import { CVBrandedEditModal } from "../CVBrandedEditModal";
import { downloadAuthenticatedFile, postAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it.each(["pipeline", "standalone"])("%s keeps legacy recovery visible and saves edits before closing", async (mode) => {
  state.html = state.stored = "<p>Old text</p>";
  state.status = "draft"; state.revision = 1;
  const finalize = vi.spyOn(cvGeneratedEditorApi, "finalize").mockRejectedValueOnce({
    response: {data: {detail: {code: "cv_source_regeneration_required", message: "Brak zamrożonych źródeł."}}},
  });
  const close = vi.fn();
  const regenerate = mode === "pipeline" ? vi.fn(() => {
    expect(state.stored).toBe("<p>Preserve my changes</p>");
    expect(close).toHaveBeenCalledWith(false);
  }) : undefined;
  const target = mode === "pipeline" ? {stageId: 21} : {generatedId: 7};
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={close}
    candidateName="Synthetic" onRegenerate={regenerate} {...target} /></QueryClientProvider>);
  await screen.findByLabelText("audit editor");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>Before review</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz i zatwierdź"}));
  fireEvent.click(await screen.findByRole("button", {name: "Sfinalizuj"}));
  await screen.findByText("Brak zamrożonych źródeł.");
  expect(screen.getByText(/Wybierz oryginalny plik CV/)).toBeTruthy();
  expect(state.status).toBe("draft");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>Preserve my changes</p>"}});
  vi.spyOn(cvGeneratedEditorApi, "update").mockRejectedValueOnce(new Error("Save unavailable"));
  fireEvent.click(screen.getByRole("button", {name: regenerate ? "Zapisz szkic i przejdź do generatora" : "Zapisz szkic i zamknij"}));
  await screen.findByText("Błąd zapisu — poprawki pozostają w edytorze");
  expect(close).not.toHaveBeenCalled();
  if (regenerate) expect(regenerate).not.toHaveBeenCalled();
  expect(state.stored).toBe("<p>Before review</p>");
  fireEvent.click(screen.getByRole("button", {name: regenerate ? "Zapisz szkic i przejdź do generatora" : "Zapisz szkic i zamknij"}));
  await waitFor(() => expect(close).toHaveBeenCalledWith(false));
  expect(state.stored).toBe("<p>Preserve my changes</p>");
  if (regenerate) expect(regenerate).toHaveBeenCalledOnce();
  finalize.mockRestore();
});

it.each(["pipeline", "standalone"])("%s finalize before autosave includes the last edit", async (mode) => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  vi.clearAllMocks();
  const target = mode === "pipeline" ? {stageId: 21} : {generatedId: 7};
  const base = mode === "pipeline" ? "/api/candidates/stages/21/cv/branded" : "/api/cv-generator/generated/7/editor";
  vi.useFakeTimers({toFake: ["setInterval", "clearInterval"]});
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={()=>{}}
    {...target} candidateName="Synthetic person" jobTitle="Synthetic job" /></QueryClientProvider>);
  await screen.findByText("Szkic v1");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>New verified text</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Pobierz szkic DOCX"}));
  await waitFor(() => expect(postAuthenticatedDownload).toHaveBeenCalledWith(
    `${base}/preview-docx`,
    {content_html: "<p>New verified text</p>", expected_revision: 1},
  ));
  await waitFor(() => expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "SZKIC_Reviewed.docx"));
  expect(state.status).toBe("draft");
  expect(state.stored).toBe("<p>Old text</p>");
  fireEvent.click(screen.getByRole("button", {name: "Zapisz i zatwierdź"}));
  await screen.findByText("Sfinalizować brandowane CV?");
  fireEvent.click(screen.getByRole("button", {name: "Sfinalizuj"}));
  await waitFor(() => expect(state.status).toBe("finalized"));
  expect(state.snapshot).toBe("<p>New verified text</p>");
  fireEvent.click(await screen.findByRole("button", {name: "Pobierz zatwierdzony DOCX v1"}));
  await waitFor(() => expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
    `${base}/versions/1/docx`, "Reviewed.docx",
  ));
});


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


it.each(["pipeline", "standalone"])("%s cancellation keeps the saved draft and reports a failed request honestly", async mode => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  vi.spyOn(cvGeneratedEditorApi, "finalize").mockImplementation(async (_id, _body, signal, onReview) => {
    onReview?.({review_id: 9, status: "running", error_code: null});
    return new Promise((_resolve, reject) => signal?.addEventListener("abort", () => reject(new Error("Stopped waiting")), {once: true}));
  });
  const cancel = vi.spyOn(cvGeneratedEditorApi, "cancelReview").mockRejectedValueOnce(new Error("offline"));
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const target = mode === "pipeline" ? {stageId: 21} : {generatedId: 7};
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={vi.fn()} candidateName="Synthetic" {...target} /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p>Saved before review</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz i zatwierdź"}));
  fireEvent.click(await screen.findByRole("button", {name: "Sfinalizuj"}));
  fireEvent.click(await screen.findByRole("button", {name: "Anuluj kontrolę"}));
  await screen.findByText("Nie udało się potwierdzić anulowania: offline");
  expect(state.status).toBe("draft");
  expect(state.snapshot).toBe("");
  expect(state.stored).toBe("<p>Saved before review</p>");
  expect(cancel).toHaveBeenCalledWith(mode === "pipeline" ? 21 : 7, 9, {
    content_html: "<p>Saved before review</p>", expected_revision: 2,
  });
  fireEvent.click(screen.getByRole("button", {name: "Anuluj kontrolę"}));
  await waitFor(() => expect(screen.queryByRole("button", {name: "Anuluj kontrolę"})).not.toBeInTheDocument());
  expect(cancel).toHaveBeenCalledTimes(2);
  expect(state.status).toBe("draft");
  expect(state.snapshot).toBe("");
});

it("cancelling after a polling timeout preserves edits made while the review was still running", async () => {
  state.html = state.stored = "<p>Old text</p>";
  state.snapshot = ""; state.status = "draft"; state.revision = 1;
  vi.spyOn(cvGeneratedEditorApi, "finalize").mockImplementation(async (_id, _body, _signal, onReview) => {
    onReview?.({review_id: 9, status: "running", error_code: null});
    throw new Error("Review timeout");
  });
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open generatedId={7} onOpenChange={vi.fn()} candidateName="Synthetic" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("audit editor"), {target: {value: "<p>Reviewed version</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz i zatwierdź"}));
  fireEvent.click(await screen.findByRole("button", {name: "Sfinalizuj"}));
  await screen.findByText("Review timeout");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>New edits after timeout</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Anuluj kontrolę"}));
  await waitFor(() => expect(screen.queryByRole("button", {name: "Anuluj kontrolę"})).not.toBeInTheDocument());
  expect(state.stored).toBe("<p>New edits after timeout</p>");
  expect(state.html).toBe("<p>New edits after timeout</p>");
  expect(state.snapshot).toBe("");
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
