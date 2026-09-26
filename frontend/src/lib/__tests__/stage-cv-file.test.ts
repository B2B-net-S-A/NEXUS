import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const fetchAuthenticatedDownload = vi.fn();
const postAuthenticatedDownload = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => get(...a) },
}));
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => fetchAuthenticatedDownload(...a),
  postAuthenticatedDownload: (...a: unknown[]) => postAuthenticatedDownload(...a),
}));

import { fetchStageCvFile } from "@/lib/stage-cv-file";

describe("fetchStageCvFile — plik CV etapu (runda 7, R7-X4-2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("zatwierdzone CV = DOCX zatwierdzonej wersji etapu", async () => {
    get.mockResolvedValue({ data: { status: "finalized", version: 3, docx_filename: "CV_A.docx" } });
    fetchAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["v3"]), filename: null });
    const file = await fetchStageCvFile(12);
    expect(get).toHaveBeenCalledWith("/api/candidates/stages/12/cv/branded");
    expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/12/cv/branded/versions/3/docx",
    );
    expect(file.filename).toBe("CV_A.docx");
  });

  it("szkic = podgląd DOCX z bieżącej treści etapu (po poprawkach QC)", async () => {
    get.mockResolvedValue({
      data: { status: "draft", version: 1, content_html: "<p>po QC</p>", edit_revision: 7 },
    });
    postAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["d"]), filename: "SZKIC_CV.docx" });
    await fetchStageCvFile(12);
    expect(postAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/12/cv/branded/preview-docx",
      { content_html: "<p>po QC</p>", expected_revision: 7 },
    );
    expect(fetchAuthenticatedDownload).not.toHaveBeenCalled();
  });
});
