import { describe, expect, it } from "vitest";

import {
  autoMatchBadgeLabel,
  collapsedNotePreview,
  visibleNoteLines,
  autoMatchBadgeTitle,
  formatAbsoluteNoteDate,
  humanNoteCount,
  isLongNote,
  noteDateLabel,
  noteRecruitmentOptions,
  parseRecruitmentFilter,
  systemNoteCount,
  threadContainsNote,
  visibleNotes,
} from "@/lib/candidate-notes-view";
import { unwrapNoteContent } from "@/components/v2/candidate-profile/profile-shared";

const NOW = new Date(2026, 8, 29, 12, 0);
const relative = () => "2 godz. temu";

const notes = [
  { id: 1, job_id: 10, job_title: "Java Dev", pinned_at: "2026-09-28T10:00:00Z" },
  { id: 2, job_id: null },
  { id: 3, job_id: 11, job_title: "QA", is_system: true },
  { id: 4, job_id: 10, job_title: "Java Dev", replies: [{ id: 9 }] },
];

describe("noteDateLabel", () => {
  it("uses the relative label for the last 7 days", () => {
    expect(noteDateLabel(new Date(2026, 8, 29, 10, 0).toISOString(), NOW, relative)).toBe(
      "2 godz. temu",
    );
  });

  it("uses DD.MM.RRRR HH:MM for older notes", () => {
    const iso = new Date(2026, 8, 1, 9, 5).toISOString();
    expect(noteDateLabel(iso, NOW, relative)).toBe("01.09.2026 09:05");
    expect(formatAbsoluteNoteDate(new Date(2025, 0, 2, 23, 7))).toBe("02.01.2025 23:07");
  });

  it("returns an empty label for a missing or broken date", () => {
    expect(noteDateLabel(null, NOW, relative)).toBe("");
    expect(noteDateLabel("nie-data", NOW, relative)).toBe("");
  });
});

describe("filters", () => {
  it("hides system notes unless asked", () => {
    expect(visibleNotes(notes, { recruitment: "all", showSystem: false }).map((n) => n.id)).toEqual([
      1, 2, 4,
    ]);
    expect(visibleNotes(notes, { recruitment: "all", showSystem: true })).toHaveLength(4);
    expect(systemNoteCount(notes)).toBe(1);
    expect(humanNoteCount(notes)).toBe(3);
  });

  it("filters by recruitment and by notes without a recruitment", () => {
    expect(visibleNotes(notes, { recruitment: 10, showSystem: false }).map((n) => n.id)).toEqual([
      1, 4,
    ]);
    expect(visibleNotes(notes, { recruitment: "none", showSystem: false }).map((n) => n.id)).toEqual([
      2,
    ]);
  });

  it("offers only recruitments present in the (visible) notes, with counts", () => {
    expect(noteRecruitmentOptions(notes, { showSystem: false })).toEqual([
      { value: "all", label: "Wszystkie rekrutacje", count: 3 },
      { value: 10, label: "Java Dev", count: 2 },
      { value: "none", label: "Bez rekrutacji", count: 1 },
    ]);
    const withSystem = noteRecruitmentOptions(notes, { showSystem: true });
    expect(withSystem.map((o) => o.value)).toEqual(["all", 10, 11, "none"]);
  });

  it("parses the select value safely", () => {
    expect(parseRecruitmentFilter("none")).toBe("none");
    expect(parseRecruitmentFilter("12")).toBe(12);
    expect(parseRecruitmentFilter("")).toBe("all");
    expect(parseRecruitmentFilter("-3")).toBe("all");
  });

  it("finds a focused reply inside its thread", () => {
    expect(threadContainsNote(notes[3], 9)).toBe(true);
    expect(threadContainsNote(notes[3], 4)).toBe(true);
    expect(threadContainsNote(notes[0], 9)).toBe(false);
  });
});

describe("isLongNote", () => {
  it("collapses long or many-line notes", () => {
    expect(isLongNote("krótko")).toBe(false);
    expect(isLongNote("x".repeat(400))).toBe(true);
    expect(isLongNote("a\nb\nc\nd\ne\nf")).toBe(true);
    expect(isLongNote(null)).toBe(false);
  });

  it("counts only lines with visible text", () => {
    // Krótka notatka rozdzielona pustymi akapitami nie jest „długa”.
    expect(isLongNote("Pierwsza\n\n \n\u00a0\n\n\nDruga\n\n\n")).toBe(false);
    expect(isLongNote("\u00a0\n \n\u200b")).toBe(false);
  });
});

// Notatka z Traffita: wzmianki, potem puste akapity `<p>&nbsp;</p>`.
const TRAFFIT_HTML = [
  "<p>@Anna Nowak @Jan Kowalski</p>",
  "<p>&nbsp;</p>",
  "<p>&nbsp;</p>",
  "<p>Rozmowa telefoniczna 12.09 — kandydat zainteresowany projektem.</p>",
  "<p>&nbsp;</p>",
  "<p>Stawka 160 zł/h netto B2B, dostępny od 1.11.</p>",
  "<p> </p>",
  "<p>Preferuje hybrydę, max 2 dni w biurze w Warszawie.</p>",
  "<p>&#160;</p>",
  "<p>Oddzwonić po rozmowie z klientem.</p>",
  "<p>Ma ofertę konkurencyjną — decyzja do piątku.</p>",
].join("");

describe("collapsed note preview", () => {
  it("skips empty Traffit paragraphs, so the preview shows real text", () => {
    const text = unwrapNoteContent(TRAFFIT_HTML);
    expect(isLongNote(text)).toBe(true);
    expect(collapsedNotePreview(text).split("\n")).toEqual([
      "@Anna Nowak @Jan Kowalski",
      "Rozmowa telefoniczna 12.09 — kandydat zainteresowany projektem.",
      "Stawka 160 zł/h netto B2B, dostępny od 1.11.",
      "Preferuje hybrydę, max 2 dni w biurze w Warszawie.",
    ]);
  });

  it("unwraps Traffit HTML without whitespace-only lines", () => {
    const text = unwrapNoteContent(TRAFFIT_HTML);
    for (const line of text.split("\n")) {
      expect(line).toBe(line.trimEnd());
    }
    expect(text).not.toMatch(/\n{3,}/);
  });

  it("plain text keeps its first four non-empty lines", () => {
    const text = "raz\n\ndwa\n   \ntrzy\ncztery\npięć\nsześć";
    expect(visibleNoteLines(text)).toEqual(["raz", "dwa", "trzy", "cztery", "pięć", "sześć"]);
    expect(collapsedNotePreview(text)).toBe("raz\ndwa\ntrzy\ncztery");
    expect(isLongNote(text)).toBe(true);
  });

  it("short note stays whole", () => {
    expect(isLongNote("Nie dzwonić przed 10.")).toBe(false);
    expect(collapsedNotePreview("Nie dzwonić przed 10.")).toBe("Nie dzwonić przed 10.");
    expect(collapsedNotePreview(null)).toBe("");
  });
});

describe("auto-match badge", () => {
  it("names the source", () => {
    expect(autoMatchBadgeLabel({ score: 66.6, source: "jjit" })).toBe("Auto-match 67/100 · JJIT");
    expect(autoMatchBadgeLabel({ score: 86, source: "nexus" })).toBe("Auto-match 86/100");
    expect(autoMatchBadgeLabel(null)).toBeNull();
    expect(autoMatchBadgeLabel({ score: "x" })).toBeNull();
  });

  it("explains must-have hits in the tooltip", () => {
    expect(autoMatchBadgeTitle({ must_hit: ["Java"], must_total: 3 })).toContain(
      "Must-have: 1/3 (Java).",
    );
  });
});
