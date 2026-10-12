import { describe, expect, it } from "vitest";

import type { RecruitmentOutcomeRow } from "@/components/v2/pages/candidate-outcomes-query";
import {
  dockNotesSummary,
  earlierSummaryLabel,
  groupFactsLine,
  notesForFilter,
  periodLabel,
  splitPersonNotes,
} from "../notes-by-recruitment";

const JOB = 42;

const note = (id: number, extra: Record<string, unknown> = {}) => ({
  id,
  job_id: null as number | null,
  job_title: null as string | null,
  created_at: "2025-03-14T15:20:00Z",
  is_system: false,
  group: "talks",
  ...extra,
});

const row = (jobId: number, extra: Partial<RecruitmentOutcomeRow> = {}): RecruitmentOutcomeRow => ({
  job_id: jobId,
  job_title: `Rekrutacja ${jobId}`,
  job_status: "published",
  client_name: "Klient Przykładowy",
  latest_stage: "screening",
  latest_stage_name: null,
  first_seen: "2025-03-01T09:00:00Z",
  last_seen: "2025-04-02T09:00:00Z",
  rejection_reason: null,
  stages: [],
  ...extra,
});

describe("splitPersonNotes", () => {
  it("oddziela notatki tej rekrutacji i grupuje resztę od najświeższej rozmowy", () => {
    const notes = [
      note(1, { job_id: JOB, job_title: "Analityk", created_at: "2026-10-12T08:00:00Z" }),
      note(2, { job_id: 7, job_title: "Analityk systemowy", created_at: "2025-04-02T09:40:00Z" }),
      note(3, { job_id: 7, job_title: "Analityk systemowy", created_at: "2025-03-14T15:20:00Z" }),
      note(4, { job_id: 9, job_title: "Business Analyst", created_at: "2024-09-18T12:30:00Z" }),
      // Import z Traffita bez powiązania, ale najświeższy — idzie na górę.
      note(5, { created_at: "2026-09-30T10:00:00Z" }),
    ];

    const split = splitPersonNotes(notes, JOB);

    expect(split.here.map((n) => n.id)).toEqual([1]);
    expect(split.earlier.map((n) => n.id)).toEqual([2, 3, 4, 5]);
    expect(split.groups.map((g) => g.key)).toEqual(["none", "job:7", "job:9"]);
    expect(split.groups[0]).toMatchObject({ jobId: null, title: "Bez rekrutacji", humanCount: 1 });
    expect(split.groups[1]).toMatchObject({
      jobId: 7,
      title: "Analityk systemowy",
      newestAt: "2025-04-02T09:40:00Z",
      oldestAt: "2025-03-14T15:20:00Z",
    });
  });

  it("liczy notatki ludzi bez wpisów automatów i rekrutacje bez grupy „bez rekrutacji”", () => {
    const split = splitPersonNotes(
      [
        note(1, { job_id: JOB }),
        note(2, { job_id: JOB, is_system: true, group: "automat" }),
        note(3, { job_id: 7, created_at: "2023-05-11T07:12:00Z" }),
        note(4, { job_id: 7, is_system: true, group: "automat", created_at: "2021-01-01T00:00:00Z" }),
        note(5, { created_at: "2024-01-05T00:00:00Z" }),
      ],
      JOB,
    );

    expect(split.hereHuman).toBe(1);
    expect(split.earlierHuman).toBe(2);
    expect(split.earlierRecruitments).toBe(1);
    // Najstarsza notatka CZŁOWIEKA — wpis automatu z 2021 nie cofa „od”.
    expect(split.sinceYear).toBe(2023);
    expect(earlierSummaryLabel(split)).toBe("2 notatki · 1 rekrutacja · od 2023");
    expect(dockNotesSummary(split)).toBe("1 tu · 2 wcześniej");
  });

  it("wynik bierze wyłącznie z wiersza historii zakończonej rekrutacji", () => {
    const notes = [
      note(1, { job_id: 7, job_title: "Tytuł z notatki" }),
      note(2, { job_id: 8, job_title: "W toku" }),
      note(3, { job_id: 9, job_title: "Spoza historii" }),
    ];
    const outcomes = [
      row(7, {
        job_title: "Analityk systemowy",
        latest_stage: "rejected",
        rejection_reason: "Klient — za mało integracji",
        stages: [
          { stage: "rejected", stage_name: null, moved_at: "2025-04-02T09:00:00Z" },
          { stage: "client_interview", stage_name: null, moved_at: "2025-03-20T09:00:00Z" },
          { stage: "new", stage_name: null, moved_at: "2025-03-01T09:00:00Z" },
        ],
      }),
      row(8, { latest_stage: "screening" }),
    ];

    const groups = new Map(splitPersonNotes(notes, JOB, outcomes).groups.map((g) => [g.jobId, g]));

    expect(groups.get(7)).toMatchObject({
      title: "Analityk systemowy",
      clientName: "Klient Przykładowy",
      outcome: { label: "Odrzucony", tone: "danger" },
      furthest: "Rozmowa u klienta",
      rejectionReason: "Klient — za mało integracji",
      currentStage: null,
    });
    expect(groupFactsLine(groups.get(7)!)).toBe(
      "Najdalej: Rozmowa u klienta · powód: Klient — za mało integracji · 1 notatka",
    );
    // Rekrutacja w toku: etap zamiast wyniku.
    expect(groups.get(8)).toMatchObject({ outcome: null, currentStage: "Screening" });
    expect(groupFactsLine(groups.get(8)!)).toBe("W toku: Screening · 1 notatka");
    // Notatka wskazuje rekrutację, której historia nie zwróciła: tytuł
    // z notatki, żadnego zgadywanego „Rekrutacja zamknięta”.
    expect(groups.get(9)).toMatchObject({
      title: "Spoza historii",
      clientName: null,
      outcome: null,
      currentStage: null,
      furthest: null,
    });
    expect(groupFactsLine(groups.get(9)!)).toBe("1 notatka");
  });

  it("rekrutacja zamknięta bez zatrudnienia ani odrzucenia też jest zakończona", () => {
    const [group] = splitPersonNotes(
      [note(1, { job_id: 7 })],
      JOB,
      [row(7, { job_status: "closed", latest_stage: "verified" })],
    ).groups;
    expect(group.outcome).toEqual({ label: "Rekrutacja zamknięta", tone: "neutral" });
  });

  it("bez historii poza rekrutacją dok zostaje przy dotychczasowym napisie", () => {
    const split = splitPersonNotes([note(1, { job_id: JOB })], JOB);
    expect(split.groups).toEqual([]);
    expect(dockNotesSummary(split)).toBe("1 w tej rekrutacji");
    expect(earlierSummaryLabel(split)).toBe("0 notatek");
  });
});

describe("notesForFilter", () => {
  const notes = [
    note(1),
    note(2, { group: "contact" }),
    note(3, { group: "delivery" }),
    note(4, { group: "automat", is_system: true }),
    // Odpowiedź sprzed pola `group`: wpis systemowy to automat, reszta — rozmowa.
    note(5, { group: undefined }),
    note(6, { group: undefined, is_system: true }),
  ];

  it("domyślnie zostawia same rozmowy", () => {
    expect(notesForFilter(notes, "talks").map((n) => n.id)).toEqual([1, 5]);
  });

  it("„Wszystko” niesie też próby kontaktu i wpisy automatów", () => {
    expect(notesForFilter(notes, "all").map((n) => n.id)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(notesForFilter(notes, "automat").map((n) => n.id)).toEqual([4, 6]);
  });
});

describe("periodLabel", () => {
  it("skraca okres do miesięcy i nie zmyśla dat", () => {
    expect(periodLabel("2024-09-03T08:00:00", "2024-09-18T12:30:00")).toBe("09.2024");
    expect(periodLabel("2025-03-01T09:00:00", "2025-04-02T09:00:00")).toBe("03–04.2025");
    expect(periodLabel("2024-11-20T09:00:00", "2025-02-02T09:00:00")).toBe("11.2024–02.2025");
    expect(periodLabel(null, "2023-05-11T07:12:00")).toBe("05.2023");
    expect(periodLabel(null, undefined)).toBeNull();
    expect(periodLabel("nie-data", null)).toBeNull();
  });

  it("okres grupy bierze z historii rekrutacji, a bez niej z notatek", () => {
    const notes = [note(1, { job_id: 7, created_at: "2025-03-14T15:20:00" }), note(2, { created_at: "2023-05-11T07:12:00" })];
    const groups = splitPersonNotes(notes, JOB, [
      row(7, { first_seen: "2025-02-27T09:00:00", last_seen: "2025-04-02T09:00:00" }),
    ]).groups;
    expect(groups.map((g) => g.period)).toEqual(["02–04.2025", "05.2023"]);
  });
});
