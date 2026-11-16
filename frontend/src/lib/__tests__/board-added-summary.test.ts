import { describe, expect, it } from "vitest";

import { addedToJobSummary } from "@/lib/board-added-summary";

// 16.11.2026 12:00 w Warszawie.
const NOW = new Date("2026-11-16T11:00:00Z");

const col = (stage: string, name: string, items: object[], category = "internal") => ({
  stage,
  name,
  category,
  terminal_type: null,
  items: items as never[],
});

const card = (
  candidate_id: number,
  by: number | null,
  at = "2026-11-16T08:00:00Z",
  extra: object = {},
) => ({
  candidate_id,
  added_to_job_by_id: by,
  added_to_job_by_name: by == null ? null : `Osoba ${by} Nazwisko`,
  added_to_job_at: at,
  ...extra,
});

describe("Kto ilu dodał (16.11.2026)", () => {
  it("liczy dodania po osobie z pierwszego wpisu, także zamkniętych", () => {
    const summary = addedToJobSummary(
      [
        col("new", "Nowi / Analiza CV", [card(1, 10), card(2, 10)]),
        col("rejected", "Odrzucony", [card(3, 10), card(4, 20)], "terminal"),
      ],
      [],
      NOW,
    );
    const ten = summary.rows.find((r) => r.key === "user:10")!;
    expect(ten.added).toBe(3);
    expect(ten.inProgress).toBe(2);
    expect(summary.total).toBe(4);
    expect(summary.byPeople).toBe(4);
    expect(summary.rows.map((r) => r.key)).toEqual(["user:10", "user:20"]);
  });

  it("osoba z zespołu bez dodań zostaje z zerem, za tymi, którzy dodali", () => {
    const summary = addedToJobSummary(
      [col("new", "Nowi", [card(1, 10)])],
      [
        { user_id: 30, name: "Osoba 30 Nazwisko" },
        { user_id: 10, name: "Osoba 10 Nazwisko" },
      ],
      NOW,
    );
    expect(summary.rows.map((r) => [r.key, r.added])).toEqual([
      ["user:10", 1],
      ["user:30", 0],
    ]);
  });

  it("silnik „Nowi” i stary wpis bez osoby idą osobno, nie do ludzi", () => {
    const summary = addedToJobSummary(
      [
        col("new", "Nowi", [
          card(1, null, undefined, { entry_source: "system" }),
          card(2, null, undefined, { entry_source: "system" }),
          card(3, null, undefined, { entry_source: "added_manual" }),
          card(4, 10),
        ]),
      ],
      [],
      NOW,
    );
    expect(summary.rows.map((r) => [r.kind, r.added])).toEqual([
      ["user", 1],
      ["system", 2],
      ["none", 1],
    ]);
    expect(summary.byPeople).toBe(1);
    expect(summary.total).toBe(4);
  });

  it("ta sama osoba w dwóch kolumnach liczy się raz", () => {
    const summary = addedToJobSummary(
      [col("new", "Nowi", [card(1, 10)]), col("screening", "Screening", [card(1, 10)])],
      [],
      NOW,
    );
    expect(summary.total).toBe(1);
    expect(summary.rows[0].added).toBe(1);
  });

  it("7 dni w kalendarzu firmy: dziś i sześć dni wstecz, ósmy dzień już nie", () => {
    const summary = addedToJobSummary(
      [
        col("new", "Nowi", [
          card(1, 10, "2026-11-16T08:00:00Z"),
          card(2, 10, "2026-11-10T08:00:00Z"),
          // 09.11 23:30 w Warszawie (22:30 UTC) — ósmy dzień wstecz.
          card(3, 10, "2026-11-09T22:30:00Z"),
          card(4, 10, null as unknown as string),
        ]),
      ],
      [],
      NOW,
    );
    expect(summary.rows[0].last7).toBe(2);
  });

  it("Zweryfikowany i dalej, CV u klienta i dalej — tylko w toku", () => {
    const summary = addedToJobSummary(
      [
        col("screening", "Screening", [card(1, 10)]),
        col("verified", "Zweryfikowany", [card(2, 10)]),
        col("cv_sent", "CV Wysłane", [card(3, 10)]),
        col("client_interview", "Interview Klient", [card(4, 10)]),
        col("rejected", "Odrzucony", [card(5, 10)], "terminal"),
      ],
      [],
      NOW,
    );
    const row = summary.rows[0];
    expect(row).toMatchObject({ added: 5, inProgress: 4, pastScreening: 3, atClient: 2 });
  });

  it("pusta rekrutacja bez zespołu nie ma wierszy", () => {
    const summary = addedToJobSummary([col("new", "Nowi", [])], [], NOW);
    expect(summary).toEqual({ rows: [], total: 0, byPeople: 0 });
  });
});
