import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiPost = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ default: { post: apiPost } }));

import {
  buildCandidateExportRequest,
  downloadCandidateExport,
} from "@/lib/candidate-export";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

describe("candidate export request", () => {
  it("builds a filtered request from the canonical filter model", () => {
    const request = buildCandidateExportRequest(
      {
        ...DEFAULT_FILTERS,
        q: "React",
        status: ["active"],
        openTo: ["side_projects"],
        recentlyChangedJobs: 2,
        recruitmentIds: [17],
        page: 9,
      },
      "xlsx",
      "filtered",
      [1, 2],
    );

    expect(request).toMatchObject({
      format: "xlsx",
      scope: "filtered",
      candidate_ids: [],
      limit: 100_000,
      filters: {
        q: "React",
        status: ["active"],
        open_to: ["side_projects"],
        recently_changed_jobs: 2,
        recruitment_id: [17],
      },
    });
    expect(request.filters).not.toHaveProperty("page");
    expect(request.filters).not.toHaveProperty("include_match_stats");
  });

  it("deduplicates selected ids and omits filters", () => {
    const request = buildCandidateExportRequest(
      { ...DEFAULT_FILTERS, q: "ignored" },
      "csv",
      "selected",
      [8, 3, 8],
    );

    expect(request.filters).toEqual({});
    expect(request.candidate_ids).toEqual([8, 3]);
  });
});

describe("downloadCandidateExport — pobranie pliku eksportu", () => {
  const request = buildCandidateExportRequest(DEFAULT_FILTERS, "csv", "filtered");
  let clicked: HTMLAnchorElement[];

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-24T12:00:00Z"));
    clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this);
    });
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:eksport"),
      revokeObjectURL: vi.fn(),
    });
    apiPost.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function respond(headers: Record<string, string>) {
    const data = new Blob(["id;imie\n1;Anna"]);
    apiPost.mockResolvedValueOnce({ data, headers });
    return data;
  }

  it("wysyła żądanie jako blob i klika link z nazwą z `filename*=UTF-8''`", async () => {
    const data = respond({
      "content-disposition":
        "attachment; filename=\"kandydaci.csv\"; filename*=UTF-8''kandydaci%20%C5%BC%C3%B3%C5%82te.csv",
    });

    await downloadCandidateExport(request);

    expect(apiPost).toHaveBeenCalledWith("/api/candidates/export", request, {
      responseType: "blob",
    });
    expect(URL.createObjectURL).toHaveBeenCalledWith(data);
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("kandydaci żółte.csv");
    expect(clicked[0].href).toBe("blob:eksport");
    // Link nie zostaje w dokumencie po kliknięciu.
    expect(document.body.contains(clicked[0])).toBe(false);
  });

  it("nazwa z `filename=\"…\"` w cudzysłowie i bez cudzysłowu", async () => {
    respond({ "content-disposition": 'attachment; filename="lista_2026.xlsx"' });
    await downloadCandidateExport(request);
    expect(clicked[0].download).toBe("lista_2026.xlsx");

    respond({ "content-disposition": "attachment; filename=lista.csv; size=10" });
    await downloadCandidateExport(request);
    expect(clicked[1].download).toBe("lista.csv");
  });

  it("bez nagłówka albo bez nazwy w nagłówku — nazwa zapasowa z datą i formatem", async () => {
    respond({});
    await downloadCandidateExport({ ...request, format: "xlsx" });
    expect(clicked[0].download).toBe("kandydaci-2026-11-24.xlsx");

    respond({ "content-disposition": "attachment" });
    await downloadCandidateExport(request);
    expect(clicked[1].download).toBe("kandydaci-2026-11-24.csv");
  });

  it("adres bloba zwalnia dopiero po minucie, nie od razu", async () => {
    respond({});
    await downloadCandidateExport(request);

    vi.advanceTimersByTime(59_999);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:eksport");
  });

  it("błąd API przechodzi do wywołującego i nie klika żadnego linku", async () => {
    apiPost.mockRejectedValueOnce(new Error("403"));
    await expect(downloadCandidateExport(request)).rejects.toThrow("403");
    expect(clicked).toHaveLength(0);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("nazwa zapasowa ma dzień kalendarza firmy, nie UTC: 23:30 UTC 30.09 to w Warszawie 01.10", async () => {
    vi.setSystemTime(new Date("2026-09-30T23:30:00Z"));
    respond({});
    await downloadCandidateExport(request);
    expect(clicked[0].download).toBe("kandydaci-2026-10-01.csv");
  });
});
