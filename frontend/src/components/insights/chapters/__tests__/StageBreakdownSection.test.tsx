/**
 * „Lejek po etapach” — każdy etap i odznaka Tablicy (Pipeline v4).
 *
 * Pilnowane reguły:
 * 1. Konwersja bez mianownika to „—”, nigdy „0%”.
 * 2. Konwersję ma tylko etap główny (do poprzedniego głównego); odznaka „—”.
 * 3. Awaria (403/500) nie renderuje się jako pustka.
 * 4. Karta „Zamknięci — kto skończył” pokazuje grupy i powody.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { StageBreakdownSection } from "@/components/insights/chapters/StageBreakdownSection";
import {
  stageConversion,
  stageConversionPct,
  type StageBreakdownResponse,
  type StageBreakdownRow,
} from "@/lib/api/insightsStageBreakdown";

const ENDPOINT = "/api/insights/recruitment/stage-breakdown";

function row(
  column: StageBreakdownRow["column"],
  key: string,
  label: string,
  is_main: boolean,
  reached: number,
  now = 0,
): StageBreakdownRow {
  return {
    column,
    column_label: column,
    key,
    label,
    is_main,
    reached,
    now,
  };
}

const ROWS: StageBreakdownRow[] = [
  { ...row("new", "added", "Dodani", true, 40, 12), column_label: "Nowi" },
  row("new", "reassign", "Przepięcie", false, 4, 1),
  {
    ...row("verified", "verified", "Zweryfikowani", true, 20, 5),
    column_label: "Zweryfikowany",
  },
  row("verified", "dz", "DZ ✓", false, 10, 2),
  {
    ...row("cv_sent", "cv_sent", "Wysłani do klienta", true, 0, 0),
    column_label: "CV wysłane",
  },
  row("client_interview", "prep", "Prep", false, 3, 1),
  {
    ...row("contract", "acceptance", "Akceptacja", true, 1, 0),
    column_label: "Umowa",
  },
  row("contract", "contract_sent", "Umowa wysłana", false, 1, 1),
];

function body(
  overrides: Partial<StageBreakdownResponse> = {},
): StageBreakdownResponse {
  return {
    period: {
      kind: "month",
      start: "2026-08-01T00:00:00+02:00",
      end: "2026-09-01T00:00:00+02:00",
      timezone: "Europe/Warsaw",
    },
    rows: ROWS,
    closed_by: [
      {
        key: "candidate",
        label: "Zrezygnował",
        count: 2,
        top_reasons: [
          { label: "Bez podanego powodu", count: 2, kind: "none", details: [] },
        ],
      },
      {
        key: "recruiter",
        label: "Odrzucony przez nas",
        count: 5,
        top_reasons: [
          { label: "Za wysoka stawka", count: 3, kind: "reason", details: [] },
          {
            label: "Inne",
            count: 2,
            kind: "other",
            details: ["Za daleko do biura", "Brak EN (2)"],
          },
        ],
      },
      {
        key: "delivery_lead",
        label: "Odrzucony przez DL",
        count: 0,
        top_reasons: [],
      },
      {
        key: "client",
        label: "Odrzucony przez klienta",
        count: 1,
        top_reasons: [],
      },
    ],
    definitions: { reached: "Doszło — definicja.", now: "Teraz — definicja." },
    ...overrides,
  };
}

function respond(value: unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url !== ENDPOINT)
      return Promise.reject(new Error(`Nieoczekiwany adres: ${url}`));
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <StageBreakdownSection period={{ period: "month", offset: -1 }} />
    </QueryClientProvider>,
  );
}

// Klamry: funkcja zwrócona z beforeEach to dla Vitesta hook sprzątający.
beforeEach(() => {
  mocks.get.mockReset();
});

describe("stageConversionPct", () => {
  it("etap główny dzieli przez poprzedni główny, odznaka nie ma konwersji", () => {
    expect(stageConversionPct(ROWS, 0)).toBeNull();
    expect(stageConversionPct(ROWS, 1)).toBeNull(); // Przepięcie — odznaka
    expect(stageConversionPct(ROWS, 2)).toBe(50); // 20 / 40
    expect(stageConversionPct(ROWS, 3)).toBeNull(); // DZ ✓ — odznaka
    expect(stageConversionPct(ROWS, 4)).toBe(0); // 0 / 20 — policzone zero
    expect(stageConversionPct(ROWS, 5)).toBeNull(); // Prep — odznaka
    expect(stageConversionPct(ROWS, 7)).toBeNull(); // Umowa wysłana — odznaka
  });

  it("zerowy mianownik daje null, nie 0", () => {
    const rows = [
      row("verified", "verified", "Zweryfikowani", true, 0),
      row("cv_sent", "cv_sent", "Wysłani", true, 0),
    ];
    expect(stageConversionPct(rows, 1)).toBeNull();
  });

  it("etap z zerem, przez który nikt nie przeszedł, nie jest mianownikiem", () => {
    // Akceptacja (6, 1 osoba) przy „Wysłani do klienta” = 0 liczy się
    // względem Zweryfikowanych (20), a nie „—” ani ∞.
    const conversion = stageConversion(ROWS, 6);
    expect(conversion.pct).toBe(5);
    expect(conversion.base?.label).toBe("Zweryfikowani");
  });

  it("etap większy od poprzedniego i bez wcześniejszego = „—”, nie 120%", () => {
    const rows = [
      row("cv_sent", "cv_sent", "Wysłani", true, 10),
      row("client_interview", "after_interview", "Po rozmowie", false, 30),
      row("client_interview", "client_interview", "Rozmowa", true, 12),
    ];
    expect(stageConversionPct(rows, 1)).toBeNull();
    expect(stageConversionPct(rows, 2)).toBeNull();
  });

  it("pomija nowy etap QC CV i liczy względem ostatniego, przez który ludzie przeszli (audyt 24.09.2026)", () => {
    // Produkcja: Zweryfikowani 930, QC CV 217 (etap z 24.09), Wysłani 598 —
    // było 275,6%.
    const rows = [
      row("verified", "verified", "Zweryfikowani", true, 930),
      row("cv_qc", "qc", "QC CV", true, 217),
      row("cv_qc", "cpro", "W kolejce Cpro", false, 5),
      row("cv_sent", "cv_sent", "Wysłani do klienta", true, 598),
    ];
    const conversion = stageConversion(rows, 3);
    expect(conversion.pct).toBe(64.3);
    expect(conversion.base?.label).toBe("Zweryfikowani");
    expect(conversion.skipped.map((r) => r.label)).toEqual(["QC CV"]);
    // QC CV względem Zweryfikowanych zostaje normalnym procentem.
    expect(stageConversionPct(rows, 1)).toBe(23.3);
  });
});

describe("StageBreakdownSection", () => {
  it("rysuje wiersze z Doszło, Teraz i konwersją", async () => {
    respond(body());
    renderSection();

    const dz = await screen.findByTestId("stage-row-dz");
    const cells = within(dz).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("DZ ✓");
    expect(cells[3]).toHaveTextContent("10");
    expect(cells[4]).toHaveTextContent("2");
    expect(cells[5]).toHaveTextContent("—");

    const verified = screen.getByTestId("stage-row-verified");
    expect(within(verified).getAllByRole("cell")[5]).toHaveTextContent("50%");

    const prep = screen.getByTestId("stage-row-prep");
    expect(within(prep).getAllByRole("cell")[5]).toHaveTextContent("—");

    expect(screen.getByText("Nowi")).toBeInTheDocument();
    expect(screen.getByText(/Doszło — definicja\./)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(ENDPOINT, {
      params: { period: "month", offset: -1 },
    });
  });

  it("pokazuje, kto zakończył proces, z powodami", async () => {
    respond(body());
    renderSection();

    const card = await screen.findByRole("complementary", {
      name: "Zamknięci — kto skończył",
    });
    expect(
      within(card).getByText(/zakończone w wybranym okresie: 8/),
    ).toBeInTheDocument();
    const recruiter = within(card).getByTestId("closed-by-recruiter");
    expect(recruiter).toHaveTextContent("Odrzucony przez nas");
    expect(recruiter).toHaveTextContent("Za wysoka stawka");

    // Jednorazowe wpisy ręczne jako „Inne” z listą treści w dymku.
    const other = within(card).getByTestId("closed-by-recruiter-other");
    expect(other).toHaveTextContent("Inne");
    expect(other).toHaveAttribute(
      "title",
      "Za daleko do biura\nBrak EN (2)",
    );

    const candidate = within(card).getByTestId("closed-by-candidate");
    expect(candidate).toHaveTextContent("Bez podanego powodu");
    expect(candidate).not.toHaveTextContent("legacy_unknown");
  });

  it("403 to brak uprawnień, a nie pusta sekcja", async () => {
    respond(
      Object.assign(new Error("HTTP 403"), { response: { status: 403 } }),
    );
    renderSection();

    expect(await screen.findByText(/nie ma dostępu/)).toBeInTheDocument();
    expect(screen.queryByText(/nikt nie wszedł/)).not.toBeInTheDocument();
  });

  it("500 to awaria z ponowieniem, a nie pusta sekcja", async () => {
    respond(
      Object.assign(new Error("HTTP 500"), { response: { status: 500 } }),
    );
    renderSection();

    expect(
      (await screen.findAllByText(/Nie udało się pobrać/)).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText(/nikt nie wszedł/)).not.toBeInTheDocument();
  });

  it("same zera to pusty stan dopiero po sukcesie", async () => {
    respond(
      body({
        rows: ROWS.map((r) => ({ ...r, reached: 0, now: 0 })),
        closed_by: body().closed_by.map((g) => ({
          ...g,
          count: 0,
          top_reasons: [],
        })),
      }),
    );
    renderSection();

    expect(
      await screen.findByText(/nikt nie wszedł na żaden etap/),
    ).toBeInTheDocument();
  });
});
