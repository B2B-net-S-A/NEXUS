/**
 * Przycisk pobrania nad CV firmowym idzie za formatem pliku z reguły klienta
 * (25.11.2026). Bez wymagań — jak dotąd: PDF przy Nowym CV, inaczej Word.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  stageCvPdf: vi.fn(),
  stageCvFile: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));
vi.mock("@/lib/docx-preview-safe", () => ({ renderDocxSafely: async () => undefined }));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/docx-fit", () => ({ observeDocxFit: () => undefined }));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({ ConsentAttachButton: () => null }));
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({ CvPagesPreview: () => <div data-testid="pages" /> }));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => mocks.stageCvFile(...a),
  fetchStageCvPdf: (...a: unknown[]) => mocks.stageCvPdf(...a),
}));
vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
}));

import { StageCvPreview } from "../StageCvPreview";

const BRANDED = {
  status: "draft",
  content_html: "<p>CV</p>",
  from_generator: true,
  generated_document_id: 41,
  new_layout_enabled: true,
};

function mount(branded: Record<string, unknown>) {
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/cv/branded") ? { data: { ...BRANDED, ...branded } } : { data: [] },
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <StageCvPreview
        candidateId={1}
        jobId={2}
        cvStageId={3}
        loadStageCvFile={(...a: Parameters<typeof mocks.stageCvFile>) => mocks.stageCvFile(...a)}
      />
    </QueryClientProvider>,
  );
}

async function downloadLabels(): Promise<string[]> {
  await waitFor(() => expect(screen.getAllByRole("button", { name: /^Pobierz/ }).length).toBeGreaterThan(0));
  return screen.getAllByRole("button", { name: /^Pobierz/ }).map((b) => b.textContent?.trim() ?? "");
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.stageCvPdf.mockReset().mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "CV.pdf" });
  mocks.stageCvFile.mockReset().mockResolvedValue({ blob: new Blob(["docx"]), filename: "CV.docx" });
  mocks.downloadBlob.mockReset();
});

describe("StageCvPreview — przycisk pobrania za formatem klienta", () => {
  it("bez wymagań: Word przy klasycznym, PDF przy Nowym CV — jak dotąd", async () => {
    mount({ cv_layout: "classic", client_file_format: null });
    expect(await downloadLabels()).toEqual(["Pobierz DOCX"]);
  });

  it("bez wymagań przy Nowym CV: sam PDF", async () => {
    mount({ cv_layout: "new", client_file_format: null });
    expect(await downloadLabels()).toEqual(["Pobierz PDF"]);
  });

  it("klient z PDF przy klasycznym CV: PDF etapu zamiast Worda", async () => {
    mount({ cv_layout: "classic", client_file_format: "pdf" });
    expect(await downloadLabels()).toEqual(["Pobierz PDF"]);
    await userEvent.setup().click(screen.getByRole("button", { name: /Pobierz PDF/ }));
    await waitFor(() => expect(mocks.stageCvPdf).toHaveBeenCalledWith(3, { download: "preview" }));
    expect(mocks.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV.pdf");
  });

  it("klient z Wordem przy Nowym CV: Word (nowy wygląd), bez klasycznego", async () => {
    mount({ cv_layout: "new", client_file_format: "docx" });
    expect(await downloadLabels()).toEqual(["Pobierz DOCX"]);
    await userEvent.setup().click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    await waitFor(() => expect(mocks.stageCvFile).toHaveBeenCalledWith(3, { download: "preview" }));
  });

  it("klient chce obu: Word i PDF", async () => {
    mount({ cv_layout: "new", client_file_format: "both" });
    expect(await downloadLabels()).toEqual(["Pobierz DOCX", "Pobierz PDF"]);
  });
});
