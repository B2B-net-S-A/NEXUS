import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CvRulePreviewTab } from "./CvRulePreviewTab";

const mocks = vi.hoisted(() => ({ enqueue: vi.fn(async () => ({id: 9})) }));
vi.mock("@/lib/cv-rules", () => ({cvRulesApi: {
  promptPreview: vi.fn(async () => ({block: "Presentation only", is_active: true})),
  enqueuePreview: mocks.enqueue,
  getPreview: vi.fn(),
}}));
vi.mock("@/lib/api", () => ({extractErrorMsg: String, default: {get: vi.fn(async (url: string) => {
  if (url.endsWith("/cv-sources")) return {data: [{id: 72, filename: "chosen.docx", is_primary: false, uploaded_at: null}]};
  if (url.endsWith("/recruitments")) return {data: [{stage_id: 3, job_id: 4, client_id: 26, job_title: "Synthetic job", ready: true, stage: "Nowy"}]};
  return {data: [{id: 2, full_name: "Synthetic Candidate"}]};
})}}));

describe("Rule preview source selection", () => {
  it("requires a source and sends its identity with the candidate and process", async () => {
    const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
    const onPreviewId = vi.fn();
    render(<QueryClientProvider client={queryClient}><CvRulePreviewTab clientId={26} dirty={false} previewId={null} onPreviewId={onPreviewId} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("Szukaj kandydata"), {target: {value: "Synthetic"}});
    fireEvent.click(await screen.findByRole("button", {name: "Synthetic Candidate"}));
    await screen.findByRole("option", {name: "Synthetic job · Nowy"});
    fireEvent.change(screen.getByLabelText("Rekrutacja u tego klienta"), {target: {value: "3"}});
    expect(screen.getByRole("button", {name: "Wygeneruj CV próbne"})).toBeDisabled();
    await screen.findByRole("option", {name: "chosen.docx"});
    fireEvent.change(screen.getByLabelText("Plik do generacji"), {target: {value: "72"}});
    fireEvent.click(screen.getByRole("button", {name: "Wygeneruj CV próbne"}));
    await waitFor(() => expect(mocks.enqueue).toHaveBeenCalledWith(26, {
      candidate_id: 2, stage_id: 3, cv_document_id: 72, language: "pl",
    }));
    await waitFor(() => expect(onPreviewId).toHaveBeenCalledWith(9));
  });
});
