import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";
import {
  hasStageFilter,
  isStageColumn,
  stageDateRangeLabel,
  stageMatchHeadline,
  stageMatchMover,
} from "@/lib/stage-filter";

describe("stage-filter", () => {
  it("zakres dat: ten sam rok raz, przełom roku w obu, jedna granica", () => {
    expect(stageDateRangeLabel("2026-10-01", "2026-10-15")).toBe("01.10 – 15.10.2026");
    expect(stageDateRangeLabel("2025-12-15", "2026-01-05")).toBe("15.12.2025 – 05.01.2026");
    expect(stageDateRangeLabel("2026-10-01", "")).toBe("od 01.10.2026");
    expect(stageDateRangeLabel("", "2026-10-15")).toBe("do 15.10.2026");
    expect(stageDateRangeLabel("", "")).toBeNull();
    expect(stageDateRangeLabel("01.10.2026", "")).toBeNull();
  });

  it("kolumna Tablicy — tylko znane klucze", () => {
    expect(isStageColumn("cv_qc")).toBe(true);
    expect(isStageColumn("closed")).toBe(true);
    expect(isStageColumn("interview")).toBe(false);
  });

  it("lista pyta o etap przy kolumnie, kodzie, osobie, dacie albo kliencie", () => {
    expect(hasStageFilter(DEFAULT_FILTERS)).toBe(false);
    expect(hasStageFilter({ ...DEFAULT_FILTERS, stageColumns: ["cv_qc"] })).toBe(true);
    expect(hasStageFilter({ ...DEFAULT_FILTERS, pipelineStage: ["new"] })).toBe(true);
    expect(hasStageFilter({ ...DEFAULT_FILTERS, stageMovedByIds: [0] })).toBe(true);
    expect(hasStageFilter({ ...DEFAULT_FILTERS, stageMovedBefore: "2026-10-15" })).toBe(true);
    expect(hasStageFilter({ ...DEFAULT_FILTERS, stageClientIds: [3] })).toBe(true);
    // „Wysłany do klienta” to osobny filtr, bez podpisu przejścia.
    const sentOnly: CandidateFilters = { ...DEFAULT_FILTERS, sentToClientFrom: "2026-10-01" };
    expect(hasStageFilter(sentOnly)).toBe(false);
  });

  it("podpis przejścia: kolumna i dzień w kalendarzu firmy, import bez osoby", () => {
    // 23:30 UTC 4.10 to już 5.10 w Warszawie.
    expect(stageMatchHeadline({ column: "cv_qc", moved_at: "2026-10-04T23:30:00Z" })).toBe(
      "QC CV · 05.10.2026",
    );
    expect(stageMatchHeadline({ column: "verified", moved_at: null })).toBe("Zweryfikowany");
    expect(stageMatchMover({ moved_by_name: "Jan Kowalski" })).toBe("Jan Kowalski");
    expect(stageMatchMover({ moved_by_name: null })).toBe("Import systemowy");
  });
});
