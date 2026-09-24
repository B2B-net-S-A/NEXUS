import { describe, expect, it } from "vitest";

import {
  companyCvSentence,
  dockOriginalCv,
  originalCvSentence,
  primaryProfileCv,
} from "@/lib/dock-cv-summary";
import { summarizeRequirements, type MoveRequirementItem } from "@/lib/api/moveRequirements";
import { nextStageHeading } from "@/components/v2/jobs/DockNextStage";

const doc = (id: number, extra: Partial<{ is_primary: boolean; filename: string; uploaded_at: string | null }> = {}) => ({
  id,
  filename: extra.filename ?? `cv-${id}.pdf`,
  is_primary: extra.is_primary ?? false,
  uploaded_at: extra.uploaded_at ?? null,
  created_at: "2026-01-05T10:00:00Z",
});

describe("dockOriginalCv", () => {
  it("kopia ze zgłoszenia wygrywa z profilem", () => {
    const state = dockOriginalCv({
      snapshot: { has_snapshot: true, original_snapshot_at: "2026-08-20T08:00:00Z" },
      snapshotLoading: false,
      profileDocs: [doc(1)],
      profileDocsFailed: false,
    });
    expect(state.kind).toBe("snapshot");
  });

  it("bez kopii — plik z profilu, nie „brak”", () => {
    const state = dockOriginalCv({
      snapshot: { has_snapshot: false },
      snapshotLoading: false,
      profileDocs: [doc(1), doc(2, { is_primary: true, uploaded_at: "2026-09-01T10:00:00Z" })],
      profileDocsFailed: false,
    });
    expect(state).toMatchObject({ kind: "profile", date: "2026-09-01T10:00:00Z" });
    expect(originalCvSentence(state)).toBe(
      "Oryginał CV: z profilu (1.09.2026) — do zgłoszenia nie dołączono pliku",
    );
  });

  it("„brak pliku” tylko przy wczytanej, pustej liście dokumentów", () => {
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: [], profileDocsFailed: false })
        .kind,
    ).toBe("none");
    // Nieudany odczyt profilu to nie brak pliku.
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: undefined, profileDocsFailed: true })
        .kind,
    ).toBe("unknown");
    // W toku — ani brak, ani obecność.
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: undefined, profileDocsFailed: false })
        .kind,
    ).toBe("loading");
  });

  it("główne CV profilu: oznaczone jako główne → nazwa z profilu → pierwsze", () => {
    expect(primaryProfileCv([doc(1), doc(2, { is_primary: true })])?.id).toBe(2);
    expect(primaryProfileCv([doc(1), doc(2, { filename: "moje.pdf" })], "moje.pdf")?.id).toBe(2);
    expect(primaryProfileCv([doc(1), doc(2)])?.id).toBe(1);
    expect(primaryProfileCv([])).toBeNull();
  });
});

describe("companyCvSentence", () => {
  it("brak / szkic / zatwierdzone / stary szablon — każde z datą, gdy jest", () => {
    expect(companyCvSentence({ status: "none" }).text).toBe("CV firmowe: brak");
    expect(
      companyCvSentence({ status: "draft", from_generator: true, updated_at: "2026-09-03T10:00:00Z" }).text,
    ).toBe("CV firmowe: szkic · zmienione 3.09.2026");
    expect(
      companyCvSentence({ status: "finalized", from_generator: true, finalized_at: "2026-09-04T10:00:00Z" }).text,
    ).toBe("CV firmowe: zatwierdzone 4.09.2026");
    expect(companyCvSentence({ status: "draft", from_generator: false }).text).toMatch(/stary szablon/);
  });
});

describe("summarizeRequirements", () => {
  const item = (key: string, status: MoveRequirementItem["status"]): MoveRequirementItem => ({
    key,
    label: key,
    status,
    blocking: true,
  });

  it("liczy braki (także „w toku”) i oddziela bramki serwera od przypomnień", () => {
    const summary = summarizeRequirements([
      item("cv_qc", "missing"),
      item("company_cv", "missing"),
      item("client_slot", "waiting"),
      item("availability", "ok"),
    ]);
    expect(summary.missing).toBe(3);
    expect(summary.total).toBe(4);
    expect(summary.enforced.map((i) => i.key)).toEqual(["cv_qc"]);
    expect(summary.reminders.map((i) => i.key)).toEqual(["company_cv", "client_slot"]);
  });
});

describe("nextStageHeading", () => {
  it("numer i nazwa kolumny z serwera, a przed odpowiedzią nazwa etapu z karty", () => {
    expect(nextStageHeading({ to_column: "cv_qc", items: [] }, "Przepuszczony przez DZ")).toEqual({
      step: 4,
      label: "QC CV",
    });
    expect(nextStageHeading(null, "QC CV")).toEqual({ step: null, label: "QC CV" });
  });

  it("u Nordei kolumna 5 to „Wysłane do Cpro”", () => {
    const heading = nextStageHeading(
      { to_column: "cv_sent", items: [{ key: "cpro_upload", label: "x", status: "waiting", blocking: false }] },
      "CV wysłane",
    );
    expect(heading.step).toBe(5);
    expect(heading.label).toMatch(/Cpro/);
  });
});
