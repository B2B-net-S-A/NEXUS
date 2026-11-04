import { beforeEach, expect, it, vi } from "vitest";

const get = vi.fn();
const downloadBlob = vi.fn();

vi.mock("@/lib/api", () => ({ __esModule: true, default: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/lib/cv-generator", () => ({
  downloadBlob: (...a: unknown[]) => downloadBlob(...a),
  extractErrorDetail: async (error: { detail?: string }) => error.detail ?? "",
}));

import { downloadGeneratedCv } from "../cv-generated-files";

const ITEM = { id: 7, filename: "CV_A.docx", approved_version_id: null };

beforeEach(() => vi.clearAllMocks());

it("pobranie wyniku generatora niesie intencję i miejsce w aplikacji", async () => {
  get.mockResolvedValue({ data: new Blob(["docx"]) });
  expect(await downloadGeneratedCv(ITEM)).toBeNull();
  expect(get).toHaveBeenCalledWith("/api/cv-generator/generated/7/docx?intent=download&surface=result", {
    responseType: "blob",
  });
  expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV_A.docx");
});

it("zatwierdzona wersja pobiera się ze swojej trasy, a lista plików podaje własne miejsce", async () => {
  get.mockResolvedValue({ data: new Blob(["docx"]) });
  await downloadGeneratedCv({ ...ITEM, approved_version_id: 3 }, "docx", "files");
  expect(get).toHaveBeenCalledWith(
    "/api/cv-generator/generated/7/approved/3/docx?intent=download&surface=files",
    { responseType: "blob" },
  );
});

it("odmowę serwera oddaje jego słowami, a bez nich mówi, czego nie pobrano", async () => {
  get.mockRejectedValueOnce({ detail: "Dołącz zrzut zgody RODO." });
  expect(await downloadGeneratedCv(ITEM)).toBe("Dołącz zrzut zgody RODO.");
  get.mockRejectedValueOnce({});
  expect(await downloadGeneratedCv(ITEM, "html")).toBe("Nie udało się pobrać pliku HTML.");
  expect(downloadBlob).not.toHaveBeenCalled();
});
