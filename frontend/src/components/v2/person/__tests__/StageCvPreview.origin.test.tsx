/**
 * Odznaki nad CV firmowym (02.11.2026): „Wygenerowane automatycznie” stało nad
 * plikiem wgranym ręcznie, bo czytało listę generacji pary, a nie CV etapu.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));
vi.mock("@/lib/docx-preview-safe", () => ({ renderDocxSafely: async () => undefined }));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/docx-fit", () => ({ observeDocxFit: () => undefined }));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({ ConsentAttachButton: () => null }));

import { StageCvPreview } from "../StageCvPreview";

const AUTO_ROW = { id: 41, status: "ready", origin: "auto", needs_review: true };
const GENERATED = {
  status: "draft",
  content_html: "<p>CV</p>",
  from_generator: true,
  source: "generator",
  generated_document_id: 41,
  origin: null,
};
const UPLOADED = {
  status: "draft",
  content_html: "<p>CV</p>",
  from_generator: false,
  source: "document",
  generated_document_id: null,
  origin: { kind: "upload", label: "cv.docx" },
};

function mount(branded: unknown, cvStageId: number | null = 3) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/cv/branded")) {
      if (branded instanceof Error) throw branded;
      return { data: branded };
    }
    return { data: [AUTO_ROW] };
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <StageCvPreview
        candidateId={1}
        jobId={2}
        cvStageId={cvStageId}
        loadStageCvFile={vi.fn().mockResolvedValue({ blob: new Blob(["docx"]), filename: "CV.docx" })}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("StageCvPreview — odznaki pochodzenia", () => {
  it("plik wgrany ręcznie nie ma odznak generacji, ma „z pliku Word”", async () => {
    mount(UPLOADED);
    expect(await screen.findByText("z pliku Word")).toBeTruthy();
    expect(screen.queryByText("Wygenerowane automatycznie")).toBeNull();
    expect(screen.queryByText("Do przeglądu")).toBeNull();
  });

  it("CV z tej generacji zachowuje odznaki", async () => {
    mount(GENERATED);
    expect(await screen.findByText("Wygenerowane automatycznie")).toBeTruthy();
    expect(screen.getByText("Do przeglądu")).toBeTruthy();
    expect(screen.queryByText("z pliku Word")).toBeNull();
  });

  it("CV z innej generacji tej pary nie bierze odznak najnowszej", async () => {
    mount({ ...GENERATED, generated_document_id: 40 });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/candidates/stages/3/cv/branded"));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Wygenerowane automatycznie")).toBeNull();
    expect(screen.queryByText("Do przeglądu")).toBeNull();
  });

  it("awaria odczytu CV etapu nie daje fałszywej odznaki", async () => {
    mount(new Error("500"));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Wygenerowane automatycznie")).toBeNull();
  });

  it("podgląd generacji bez etapu czyta wiersz generacji", async () => {
    mount(null, null);
    expect(await screen.findByText("Wygenerowane automatycznie")).toBeTruthy();
    expect(mocks.get).not.toHaveBeenCalledWith(expect.stringContaining("/cv/branded"));
  });
});
