import { afterEach, describe, expect, it, vi } from "vitest";

import { POLIGON_NEW_CV_PDF, poligonFile, poligonStore } from "../adapter";
import dataset from "../dataset.json";

const ENTRY = (dataset as unknown as { meta: { template_entry_id: number } }).meta.template_entry_id;
const PREVIEW = `http://localhost:8000/api/candidates/stages/${ENTRY}/cv/branded/preview-pdf`;

afterEach(() => vi.unstubAllGlobals());

describe("poligon: podgląd PDF „Nowego CV” (lekcja „Nowe CV”, 23.11.2026)", () => {
  it("klasyczny układ i pobranie to odmowa; „Nowe CV” — fikcyjny PDF z nagłówkami trasy", async () => {
    const pdf = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    const fetchMock = vi.fn(async () => ({ ok: true, blob: async () => pdf }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await poligonFile(PREVIEW)).toBeNull();
    const store = await poligonStore();
    store.handle({ method: "patch", url: `/api/candidates/stages/${ENTRY}/cv/layout`, body: { cv_layout: "new" } });

    const file = await poligonFile(PREVIEW);
    expect(fetchMock).toHaveBeenCalledWith(POLIGON_NEW_CV_PDF);
    expect(file?.blob).toBe(pdf);
    expect(file?.filename).toBe("SZKIC_CV.pdf");
    expect(file?.headers.get("X-CV-Layout")).toBe("new");
    expect(file?.headers.get("X-CV-Page1-Fits")).toBe("1");
    expect(await poligonFile(`${PREVIEW}?intent=download&surface=card`)).toBeNull();
    expect(await poligonFile(`/api/candidates/stages/${ENTRY}/cv/branded/preview-docx`)).toBeNull();
  });
});
