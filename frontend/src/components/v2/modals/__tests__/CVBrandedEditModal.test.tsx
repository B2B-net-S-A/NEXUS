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
vi.mock("@/lib/authenticated-files", () => ({ openAuthenticatedFile: vi.fn() }));
vi.mock("@/lib/api", () => ({
  candidateStageCvApi: { branded: {
    get: async () => ({ data: { status: state.status, content_html: state.stored,
      edit_revision: state.revision, version: 1, template: "standard", language: "pl", updated_at: "2026-09-09T07:00:00Z" } }),
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
  } },
}));

import { CVBrandedEditModal } from "../CVBrandedEditModal";

afterEach(() => vi.useRealTimers());

it("finalize before the autosave interval must include the last edit", async () => {
  vi.useFakeTimers({toFake: ["setInterval", "clearInterval"]});
  const qc = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={qc}><CVBrandedEditModal open onOpenChange={()=>{}}
    stageId={21} candidateName="Synthetic person" jobTitle="Synthetic job" /></QueryClientProvider>);
  await screen.findByText("Szkic v1");
  fireEvent.change(screen.getByLabelText("audit editor"), {target: {value: "<p>New verified text</p>"}});
  fireEvent.click(screen.getByRole("button", {name: "Zapisz i zatwierdź", exact:true}));
  await screen.findByText("Sfinalizować brandowane CV?");
  fireEvent.click(screen.getByRole("button", {name: "Sfinalizuj", exact:true}));
  await waitFor(() => expect(state.status).toBe("finalized"));
  expect(state.snapshot).toBe("<p>New verified text</p>");
});
