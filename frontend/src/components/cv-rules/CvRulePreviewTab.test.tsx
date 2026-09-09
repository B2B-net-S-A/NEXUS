import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CvRulePreviewTab } from "./CvRulePreviewTab";

const mocks = vi.hoisted(() => ({ enqueue: vi.fn(async () => ({id: 9})), preview: vi.fn(), download: vi.fn(), blob: new Blob(["exact-artifact"]) }));
vi.mock("@/lib/cv-generator", async (original) => ({...await original<typeof import("@/lib/cv-generator")>(), downloadBlob: mocks.download}));
vi.mock("@/lib/cv-rules", () => ({cvRulesApi: {
  promptPreview: vi.fn(async () => ({block: "Presentation only", is_active: true})),
  enqueuePreview: mocks.enqueue,
  getPreview: mocks.preview,
}}));
vi.mock("@/lib/api", () => ({extractErrorMsg: String, default: {get: vi.fn(async (url: string) => {
  if (url.includes("/docx/")) return {data: mocks.blob};
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


describe("Rule preview artifact download", () => {
  it("downloads the selected variant from its authenticated endpoint", async () => {
    const variant = {payload: {name: "Synthetic"}, filename: "with-rule.docx", warnings: [], can_download: true};
    mocks.preview.mockResolvedValue({id: 9, status: "ready", with_rule: variant, without_rule: {...variant, filename: "without-rule.docx"}});
    const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
    render(<QueryClientProvider client={queryClient}><CvRulePreviewTab clientId={26} dirty={false} previewId={9} onPreviewId={vi.fn()} /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", {name: "Pobierz DOCX — bez reguły"}));
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(mocks.blob, "without-rule.docx"));
    const {default: api} = await import("@/lib/api");
    expect(api.get).toHaveBeenCalledWith("/api/clients/26/cv-rule/preview/9/docx/without_rule", {responseType: "blob"});
  });
});

describe("Rule preview feedback", () => {
  it("shows a failed limit and leaves descriptive instructions for human review", async () => {
    mocks.preview.mockResolvedValue({id: 10, status: "ready", with_rule: {
      payload: {name: "Synthetic"}, filename: "cv.docx", warnings: [],
      rule_feedback: [
        {field: "max_roles", label: "Limit stanowisk", status: "conflict"},
        {field: "instructions", label: "Instrukcje opisowe", status: "needs_review"},
        {field: "max_bullet_chars", label: "Długość punktów", status: "not_applicable"},
      ],
    }, without_rule: {payload: {name: "Synthetic"}, warnings: []}});
    const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}}});
    render(<QueryClientProvider client={queryClient}><CvRulePreviewTab clientId={26} dirty={false} previewId={10} onPreviewId={vi.fn()} /></QueryClientProvider>);
    expect(await screen.findByText("Limit stanowisk: niezgodność — sprawdź")).toBeInTheDocument();
    expect(screen.getByText("Instrukcje opisowe: ocena ręczna")).toBeInTheDocument();
    expect(screen.getByText("Długość punktów: brak treści do zastosowania")).toBeInTheDocument();
  });
});
