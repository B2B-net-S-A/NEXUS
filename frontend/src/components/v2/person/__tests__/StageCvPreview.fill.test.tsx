/**
 * Podgląd „Nowego CV” (PDF) w trybie `fill` wypełnia wysokość panelu
 * (27.11.2026). `flex-1` pola z kartkami działa tylko w kolumnie flex — sekcja
 * z `space-y-2` zostawiała sztywne 28 rem i rekruter widział ucięty podgląd
 * z szarym pasem pod spodem.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({ CvPagesPreview: () => <div data-testid="pages" /> }));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: vi.fn(),
  fetchStageCvPdf: vi.fn(),
}));

import { StageCvPreview } from "../StageCvPreview";

function mount(fill: boolean) {
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/cv/branded")
      ? {
          data: {
            status: "draft",
            content_html: "<p>CV</p>",
            from_generator: true,
            generated_document_id: 41,
            new_layout_enabled: true,
            cv_layout: "new",
          },
        }
      : { data: [] },
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <StageCvPreview candidateId={1} jobId={2} cvStageId={3} loadStageCvFile={vi.fn()} fill={fill} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("StageCvPreview — Nowe CV w trybie fill", () => {
  it("sekcja jest kolumną flex na całą wysokość, więc pole PDF się rozciąga", async () => {
    mount(true);
    const box = await screen.findByTestId("stage-cv-pdf-preview");
    expect(box.className).toContain("flex-1");
    const section = screen.getByRole("region", { name: "CV kandydata" });
    expect(section.className).toMatch(/\bflex\b/);
    expect(section.className).toContain("flex-col");
    expect(section.className).toContain("h-full");
  });

  it("bez fill zostaje stałe 28 rem w zwykłym bloku", async () => {
    mount(false);
    const box = await screen.findByTestId("stage-cv-pdf-preview");
    expect(box.className).toContain("h-[28rem]");
    const section = screen.getByRole("region", { name: "CV kandydata" });
    expect(section.className).toContain("space-y-2");
  });
});
