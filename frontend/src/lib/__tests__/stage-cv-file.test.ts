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

import { fetchStageCvFile, fetchStageCvForClient } from "@/lib/stage-cv-file";

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

  it("„Pobierz” dokleja intencję i miejsce w aplikacji, podgląd — nic", async () => {
    get.mockResolvedValue({ data: { status: "finalized", version: 3, docx_filename: "CV_A.docx" } });
    fetchAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["v3"]), filename: null });
    await fetchStageCvFile(12, { download: "cpro" });
    expect(fetchAuthenticatedDownload).toHaveBeenLastCalledWith(
      "/api/candidates/stages/12/cv/branded/versions/3/docx?intent=download&surface=cpro",
    );

    get.mockResolvedValue({
      data: { status: "draft", version: 1, content_html: "<p>szkic</p>", edit_revision: 2 },
    });
    postAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["d"]), filename: null });
    await fetchStageCvFile(12, { download: "preview" });
    expect(postAuthenticatedDownload).toHaveBeenLastCalledWith(
      "/api/candidates/stages/12/cv/branded/preview-docx?intent=download&surface=preview",
      { content_html: "<p>szkic</p>", expected_revision: 2 },
    );
  });
});

describe("fetchStageCvForClient — plik do klienta w układzie CV (22.11.2026)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Nowe CV: zatwierdzona wersja idzie jako PDF tej wersji, nie Word", async () => {
    get.mockResolvedValue({
      data: { status: "finalized", version: 4, cv_layout: "new", new_layout_enabled: true },
    });
    fetchAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "B2B_Tester.pdf" });
    const file = await fetchStageCvForClient(12, { download: "cpro" });
    expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/12/cv/branded/versions/4/pdf?intent=download&surface=cpro",
    );
    expect(file.filename).toBe("B2B_Tester.pdf");
  });

  it("Nowe CV, szkic: PDF z bieżącej treści etapu", async () => {
    get.mockResolvedValue({
      data: {
        status: "draft",
        version: 1,
        content_html: "<p>po QC</p>",
        edit_revision: 3,
        cv_layout: "new",
        new_layout_enabled: true,
      },
    });
    postAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: null });
    const file = await fetchStageCvForClient(12);
    expect(postAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/12/cv/branded/preview-pdf",
      { content_html: "<p>po QC</p>", expected_revision: 3 },
    );
    expect(file.filename).toBe("SZKIC_CV.pdf");
  });

  it("klasyczne albo wyłączona flaga: plik Word jak dotąd", async () => {
    get.mockResolvedValue({
      data: { status: "finalized", version: 2, cv_layout: "new", new_layout_enabled: false, docx_filename: "CV_B.docx" },
    });
    fetchAuthenticatedDownload.mockResolvedValue({ blob: new Blob(["w"]), filename: null });
    const file = await fetchStageCvForClient(12, { download: "cpro" });
    expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/12/cv/branded/versions/2/docx?intent=download&surface=cpro",
    );
    expect(file.filename).toBe("CV_B.docx");
  });
});
