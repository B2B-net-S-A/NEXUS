import { describe, expect, it } from "vitest";

import type { Activity, SalesFile } from "@/lib/api/sales";

import { stripTranscriptFooter } from "../ActivityBody";
import { followUpSteps, isTodo } from "../ActivityTimeline";
import { groupByFolder } from "../FilesSection";

const file = (id: number, folder: string | null): SalesFile => ({
  id,
  filename: `plik-${id}.pdf`,
  content_type: "application/pdf",
  size_bytes: 1,
  folder,
  company_id: null,
  opportunity_id: 1,
  uploaded_by: null,
  uploaded_by_user_id: null,
  created_at: "2026-10-01T10:00:00Z",
});

const activity = (patch: Partial<Activity>): Activity =>
  ({
    id: 1,
    kind: "note",
    subject: null,
    body: null,
    due_at: null,
    done_at: null,
    ...patch,
  }) as Activity;

describe("groupByFolder", () => {
  it("grupuje po folderze alfabetycznie, pliki bez folderu na końcu", () => {
    const groups = groupByFolder([file(1, null), file(2, "Umowa"), file(3, "Oferta"), file(4, "Umowa")]);
    expect(groups.map(([folder, files]) => [folder, files.map((f) => f.id)])).toEqual([
      ["Oferta", [3]],
      ["Umowa", [2, 4]],
      ["", [1]],
    ]);
  });

  it("pusta lista to brak grup", () => {
    expect(groupByFolder([])).toEqual([]);
  });
});

describe("isTodo", () => {
  it("zadanie zawsze, telefon tylko z terminem, notatka nigdy", () => {
    expect(isTodo(activity({ kind: "task" }))).toBe(true);
    expect(isTodo(activity({ kind: "call", due_at: "2026-11-02T09:00:00Z" }))).toBe(true);
    expect(isTodo(activity({ kind: "call" }))).toBe(false);
    expect(isTodo(activity({ kind: "note", due_at: "2026-11-02T09:00:00Z" }))).toBe(false);
  });
});

describe("followUpSteps", () => {
  it("trzy kroki jak w Atlasie: dziś, za 6 dni (dzień przed ofertą), za 14 dni", () => {
    const now = new Date(2026, 9, 28, 15, 30);
    const steps = followUpSteps(now);
    expect(steps).toHaveLength(3);
    const days = steps.map((step) => Math.round((new Date(step.due_at).getTime() - new Date(2026, 9, 28, 9).getTime()) / 86_400_000));
    expect(days).toEqual([0, 6, 14]);
  });
});

describe("stripTranscriptFooter", () => {
  it("wycina stopkę o zakładce Transkrypcje", () => {
    const body = "**Overview:** ustalenia\n\n_Pełna transkrypcja w zakładce „Transkrypcje” na dealu — do pobrania._";
    expect(stripTranscriptFooter(body)).toBe("**Overview:** ustalenia");
  });

  it("zostawia treść bez stopki", () => {
    expect(stripTranscriptFooter("Zwykła notatka")).toBe("Zwykła notatka");
  });
});
