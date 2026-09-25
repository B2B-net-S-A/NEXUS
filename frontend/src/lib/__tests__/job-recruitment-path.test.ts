import { describe, expect, it } from "vitest";

import {
  buildRecruitmentPath,
  nearestStep,
  relativeDayLabel,
  summarizeBoard,
  type BoardSummary,
} from "@/lib/job-recruitment-path";

const NOW = new Date(2026, 8, 24, 10, 0, 0);

type Col = {
  stage: string;
  name: string;
  category?: string;
  terminal_type?: string | null;
  count: number;
  items: Array<{ id: number; interview_badge?: { kind: string; at?: string | null } | null }>;
};

let nextId = 1;
function col(stage: string, name: string, n: number, extra: Partial<Col> = {}): Col {
  return {
    stage,
    name,
    category: "internal",
    count: n,
    items: Array.from({ length: n }, () => ({ id: nextId++ })),
    ...extra,
  };
}

/** „Default B2B" w kształcie tablicy (także etap-odznaka Cpro i zamknięci). */
function board(counts: Partial<Record<string, number>> = {}): Col[] {
  return [
    col("new", "Nowi / Analiza CV", counts.new ?? 0),
    col("screening", "Screening", counts.screening ?? 0),
    col("verified", "Zweryfikowany", counts.verified ?? 0),
    col("new", "Przepuszczony przez DZ", counts.qc ?? 0),
    col("new", "Wysłać do Cpro", counts.cpro ?? 0),
    col("cv_sent", "CV Wysłane", counts.sent ?? 0),
    col("client_interview", "Interview Klient", counts.interview ?? 0, { category: "external" }),
    col("new", "Umowa wysłana", counts.contract ?? 0, { category: "external" }),
    col("new", "Zatrudniony", counts.hired ?? 0, { category: "terminal", terminal_type: "hired" }),
    col("new", "Odrzucony", counts.rejected ?? 0, { category: "terminal", terminal_type: "rejected" }),
  ];
}

function summary(counts: Partial<Record<string, number>> = {}): BoardSummary {
  return summarizeBoard(board(counts), { now: NOW });
}

describe("summarizeBoard", () => {
  it("liczy kolumny Tablicy tą samą regułą co render (Cpro wpada do QC CV, ale osobno)", () => {
    const s = summary({ new: 2, qc: 1, cpro: 1, sent: 3, hired: 1, rejected: 5 });
    // Kolejka Cpro stoi w kolumnie „QC CV”, ale nie jest „do sprawdzenia w QC”.
    expect(s.counts).toMatchObject({ new: 2, cv_qc: 1, cv_sent: 3, hired: 1 });
    expect(s.cproQueue).toBe(1);
    // W procesie = bez zatrudnionych i bez zamkniętych.
    expect(s.inProcess).toBe(7);
  });

  it("najbliższa rozmowa to najwcześniejszy PRZYSZŁY termin w kolumnie rozmów", () => {
    const columns = board({ interview: 0 });
    columns[6] = {
      ...columns[6],
      count: 3,
      items: [
        { id: 900, interview_badge: { kind: "slot", at: "2026-09-23T10:00:00" } },
        { id: 901, interview_badge: { kind: "slot", at: "2026-09-27T09:00:00" } },
        { id: 902, interview_badge: { kind: "slot", at: "2026-09-25T09:00:00" } },
      ],
    };
    expect(summarizeBoard(columns, { now: NOW }).nextInterviewAt).toBe("2026-09-25T09:00:00");
  });
});

describe("telefon po rozmowie (debrief)", () => {
  it("liczy call_due w każdej kolumnie i prowadzi do niego ścieżkę i najbliższy krok", () => {
    const columns = board({ interview: 0, contract: 0 });
    columns[7] = {
      ...columns[7],
      count: 1,
      items: [{ id: 950, interview_badge: { kind: "call_due", at: "2026-09-24T09:30:00" } }],
    };
    const s = summarizeBoard(columns, { now: NOW });
    expect(s.callDue).toBe(1);
    expect(s.callDueColumn).toBe("contract");
    const path = buildRecruitmentPath({ orderMissing: 0, board: s, proposals: 0, headcount: 1, now: NOW });
    expect(path[3]).toMatchObject({ state: "missing", detail: "telefon po rozmowie: 1" });
    expect(
      nearestStep({ orderMissing: 0, board: s, proposals: 5, canAddCandidates: true }),
    ).toMatchObject({ rule: "call", action: { kind: "column", column: "contract" } });
  });
});

describe("relativeDayLabel", () => {
  it("dziś / jutro / pojutrze / DD.MM", () => {
    expect(relativeDayLabel("2026-09-24T16:00:00", NOW)).toBe("dziś");
    expect(relativeDayLabel("2026-09-25T09:00:00", NOW)).toBe("jutro");
    expect(relativeDayLabel("2026-09-26T09:00:00", NOW)).toBe("pojutrze");
    expect(relativeDayLabel("2026-10-03T09:00:00", NOW)).toBe("03.10");
  });
});

describe("buildRecruitmentPath", () => {
  it("pięć kroków z kropką stanu i jedną linią faktu", () => {
    const board = summarizeBoard(
      (() => {
        const c = board_({ new: 10, screening: 5, qc: 1, interview: 2, hired: 0 });
        c[6].items = [
          { id: 9001, interview_badge: { kind: "slot", at: "2026-09-25T11:00:00" } },
          { id: 9002 },
        ];
        return c;
      })(),
      { now: NOW },
    );
    const steps = buildRecruitmentPath({
      orderMissing: 5,
      board,
      proposals: 17,
      headcount: 1,
      now: NOW,
    });
    expect(steps.map((s) => [s.key, s.state, s.detail])).toEqual([
      ["order", "missing", "brakuje 5 — uzupełnij"],
      ["candidates", "active", "18 w procesie · 17 propozycji"],
      ["cv", "active", "1 w QC · 0 wysłanych"],
      ["interviews", "active", "2 rozmowy · najbliższa jutro"],
      ["contract", "todo", "obsada 0 / 1"],
    ]);
  });

  it("nie udaje wiedzy: zlecenie bez bramki i tablica w trakcie ładowania", () => {
    const steps = buildRecruitmentPath({ orderMissing: null, board: null, proposals: null, headcount: null });
    expect(steps[0]).toMatchObject({ state: "todo", detail: "otwórz zlecenie" });
    expect(steps[1]).toMatchObject({ state: "todo", detail: "wczytywanie…" });
    expect(steps[4]).toMatchObject({ detail: "obsada — / —" });
  });

  it("gotowe ✓: zlecenie bez braków, obsada pełna, etapy za plecami", () => {
    const steps = buildRecruitmentPath({
      orderMissing: 0,
      board: summary({ hired: 1 }),
      proposals: 0,
      headcount: 1,
      now: NOW,
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "missing", "done", "done", "done"]);
    expect(steps[1].detail).toBe("nikogo jeszcze — dodaj kandydatów");
    expect(steps[3].detail).toBe("brak zaplanowanych");
  });

  it("odmiana: 1 rozmowa, 5 rozmów, 1 wysłane, 1 propozycja", () => {
    const one = buildRecruitmentPath({
      orderMissing: 0,
      board: summary({ new: 1, sent: 1, interview: 1 }),
      proposals: 1,
      headcount: null,
      now: NOW,
    });
    expect(one[1].detail).toBe("3 w procesie · 1 propozycja");
    expect(one[2].detail).toBe("0 w QC · 1 wysłane");
    expect(one[3].detail).toBe("1 rozmowa · brak zaplanowanych");
    const five = buildRecruitmentPath({
      orderMissing: 0,
      board: summary({ interview: 5 }),
      proposals: null,
      headcount: null,
      now: NOW,
    });
    expect(five[3].detail).toBe("5 rozmów · brak zaplanowanych");
  });
});

// Pomocnik bez kolizji z nazwą `board` w teście wyżej.
function board_(counts: Partial<Record<string, number>>): Col[] {
  return board(counts);
}

describe("nearestStep — pierwsza pasująca reguła", () => {
  const base = { proposals: 0, canAddCandidates: true };

  it("1. zlecenie niekompletne wygrywa ze wszystkim", () => {
    expect(nearestStep({ ...base, orderMissing: 3, board: summary({ qc: 2 }) })).toMatchObject({
      rule: "order",
      sentence: "Uzupełnij zlecenie (brakuje 3)",
      action: { kind: "order" },
    });
  });

  it("Nordea: sama kolejka Cpro to nie „Sprawdź CV w QC” — ścieżka mówi „N w kolejce Cpro”", () => {
    const board = summarizeBoard(board_({ cpro: 3 }), { cproEnabled: true, now: NOW });
    expect(nearestStep({ ...base, orderMissing: 0, board })?.rule).not.toBe("qc");
    const cv = buildRecruitmentPath({ orderMissing: 0, board, proposals: 0, headcount: null, now: NOW })[2];
    expect(cv).toMatchObject({ state: "active", detail: "0 w QC · 3 w kolejce Cpro · 0 wysłanych" });
  });

  it("2. osoby w QC CV", () => {
    expect(nearestStep({ ...base, orderMissing: 0, board: summary({ qc: 2, verified: 4 }) })).toMatchObject({
      rule: "qc",
      sentence: "Sprawdź CV w QC (2)",
      action: { kind: "column", column: "cv_qc" },
    });
  });

  it("3. osoby w „Zweryfikowany”", () => {
    expect(nearestStep({ ...base, orderMissing: null, board: summary({ verified: 4, new: 3 }) })).toMatchObject({
      rule: "verified",
      sentence: "Przygotuj CV do QC (4)",
      action: { kind: "column", column: "verified" },
    });
  });

  it("3a. osoby znane klientowi z podobnych rekrutacji — przed propozycjami z bazy", () => {
    expect(
      nearestStep({
        ...base,
        orderMissing: 0,
        proposals: 17,
        similarPeople: 5,
        board: summary({ new: 3 }),
      }),
    ).toMatchObject({
      rule: "similar",
      sentence: "Przejrzyj 5 osób z podobnych rekrutacji, które klient już zna",
      action: { kind: "similar" },
    });
    // Bez prawa dodawania i przy nieznanej liczbie reguła milczy.
    expect(
      nearestStep({
        orderMissing: 0,
        proposals: 0,
        similarPeople: 5,
        canAddCandidates: false,
        board: summary({}),
      }),
    ).toBeNull();
    expect(
      nearestStep({ ...base, orderMissing: 0, similarPeople: null, board: summary({ new: 1 }) }),
    ).toBeNull();
  });

  it("4. propozycje z bazy do przejrzenia", () => {
    expect(
      nearestStep({ ...base, orderMissing: 0, proposals: 17, board: summary({ new: 3 }) }),
    ).toMatchObject({ rule: "proposals", sentence: "Przejrzyj 17 propozycji z bazy" });
    expect(nearestStep({ ...base, orderMissing: 0, proposals: 1, board: summary({}) })?.sentence).toBe(
      "Przejrzyj 1 propozycję z bazy",
    );
  });

  it("5. pusto w Nowych i Screeningu → szukaj w bazie (AI)", () => {
    expect(nearestStep({ ...base, orderMissing: 0, board: summary({ sent: 2 }) })).toMatchObject({
      rule: "search",
      action: { kind: "add", tab: "search" },
    });
  });

  it("inaczej brak pola — także gdy tablica się jeszcze nie wczytała", () => {
    expect(nearestStep({ ...base, orderMissing: 0, board: summary({ new: 2 }) })).toBeNull();
    expect(nearestStep({ ...base, orderMissing: 0, board: null })).toBeNull();
  });

  it("bez prawa dodawania nie podsuwa propozycji ani wyszukiwania", () => {
    expect(
      nearestStep({ orderMissing: 0, proposals: 5, canAddCandidates: false, board: summary({}) }),
    ).toBeNull();
  });
});
