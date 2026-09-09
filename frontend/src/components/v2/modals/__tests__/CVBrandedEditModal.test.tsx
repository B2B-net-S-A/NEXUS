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

import { CVBrandedEditModal } from "../CVBrandedEditModal";
import { downloadAuthenticatedFile, postAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

afterEach(() => vi.useRealTimers());

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
