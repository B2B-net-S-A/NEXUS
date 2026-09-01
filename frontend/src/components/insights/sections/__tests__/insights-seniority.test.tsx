/**
 * Ścieżka rozwoju (D6) — sekcja `/insights` → Rekrutacja.
 *
 * Cztery reguły pod ochroną. Każda jest o tym, że liczba na ekranie znaczy
 * co innego, niż wygląda:
 *
 * 1. **Reguła awansu wypisana SŁOWAMI.** Sam pasek postępu nie mówi, ile
 *    trzeba — a to ekran, na którym ocenia się ludzi z imienia i nazwiska.
 * 2. **Poziom nie spada.** Pusty licznik bieżącego okna przy poziomie „Senior”
 *    musi być opisany jako poprawny, bo inaczej czyta się jak błąd.
 * 3. **Zero PRZYPISANEJ historii ≠ zły wynik.** Osoba bez ani jednego
 *    placementu w NEXUSIE nie może dostać paska „0/6” — to nie ocena, tylko
 *    brak danych. Idzie na osobną listę.
 * 4. **Awaria ≠ pustka.** 403 i 500 renderują się jako awaria, nigdy jako
 *    „brak osób”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { InsightsSeniority } from "@/components/insights/sections/InsightsSeniority";
import type { SeniorityResponse } from "@/lib/insights-api";

const URL = "/api/insights/recruitment/seniority";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function respond(value: unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url !== URL) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InsightsSeniority />
    </QueryClientProvider>,
  );
}

const BODY: SeniorityResponse = {
  as_of: "2026-09-01",
  thresholds: {
    senior_placements: 6,
    senior_window_months: 6,
    expert_placements: 12,
    expert_window_months: 6,
    senior_alt_placements: 12,
    senior_alt_window_months: 12,
    expert_alt_placements: 24,
    expert_alt_window_months: 12,
  },
  window: {
    senior: { months: 6, start_month: "2026-04", end_month: "2026-09" },
    expert: { months: 12, start_month: "2025-10", end_month: "2026-09" },
  },
  entries: [
    {
      user_id: 1,
      name: "Anna Kowalska",
      role: "recruiter",
      level: "senior",
      total_placements: 9,
      first_placement_month: "2025-02",
      // Osiągnęła poziom w oknie, które już minęło — licznik bieżącego okna
      // jest zerem, a poziom zostaje. To jest reguła „bez degradacji”.
      placements_in_senior_window: 0,
      placements_in_expert_window: 0,
      placements_to_next_level: 12,
      senior_since: null,
      expert_since: null,
      progress_pct: 0,
    },
    {
      user_id: 2,
      name: "Bartosz Nowak",
      role: "sourcer",
      level: "expert",
      total_placements: 14,
      first_placement_month: "2024-06",
      placements_in_senior_window: 8,
      placements_in_expert_window: 14,
      // Expert nie ma następnego poziomu — obie wartości to `null`.
      placements_to_next_level: null,
      senior_since: "2025-03",
      expert_since: "2025-09",
      progress_pct: null,
    },
    {
      user_id: 3,
      name: "Celina Widmo",
      role: "tac",
      level: "junior",
      total_placements: 0,
      // Zero PRZYPISANEJ historii — wiersz idzie na listę „nieoceniani”.
      first_placement_month: null,
      placements_in_senior_window: 0,
      placements_in_expert_window: 0,
      placements_to_next_level: 6,
      senior_since: "2026-01",
      expert_since: null,
      progress_pct: 0,
    },
  ],
  totals: { users: 3, levels: { junior: 1, senior: 1, expert: 1 } },
  coverage: {
    unattributed_placements: 41,
    outside_pool_placements: 7,
    note: "Poziom liczymy wyłącznie z placementów przypisanych do aktywnych kont.",
  },
  regressions: [],
  journal: { last_observed_at: "2026-08-31T02:00:00+00:00", observations: 25 },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InsightsSeniority", () => {
  it("wypisuje regułę awansu słowami, nie tylko paskiem", async () => {
    respond(BODY);
    renderSection();

    // Bez tego zdania „6” obok nazwiska nie ma znaczenia — pasek nie mówi,
    // ile trzeba, a osoba oceniana ma prawo znać regułę.
    //
    // Każdy poziom ma DWIE alternatywne drogi. Opis wyłącznie tej krótszej
    // kazałby ludziom mierzyć się do progu, którego nie muszą osiągnąć.
    expect(
      await screen.findByText(
        /6 placementów w 6 miesięcy lub 12 placementów w 12 miesięcy/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /12 placementów w 6 miesięcy lub 24 placementy w 12 miesięcy/,
      ),
    ).toBeInTheDocument();
  });

  it("mówi wprost, że poziom nie spada", async () => {
    respond(BODY);
    renderSection();

    // Wiersz „Senior” z zerem w bieżącym oknie bez tego zdania wygląda na błąd.
    expect(
      await screen.findByText(/okno służy do\s+awansu, nie do cofania/i),
    ).toBeInTheDocument();
    expect(screen.getByText("zostaje")).toBeInTheDocument();
  });

  it("nie wystawia oceny osobie bez ani jednego przypisanego placementu", async () => {
    respond(BODY);
    renderSection();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    // Osoba z zerem PRZYPISANEJ historii wychodzi z tabeli na osobną listę
    // z powodem po polsku — zamiast dostać pasek „0/6”, który czyta się
    // jak wynik pracy.
    expect(screen.getByText("Bez przypisanych placementów")).toBeInTheDocument();
    expect(screen.getByText("Celina Widmo")).toBeInTheDocument();
    expect(
      screen.getByText(/poziom nie jest liczony/i),
    ).toBeInTheDocument();
  });

  it("pokazuje placementy spoza tabeli, żeby suma się zgadzała", async () => {
    respond(BODY);
    renderSection();

    // Decyzja D1: dorobek nieprzypisany i przypisany do kont spoza puli musi
    // być widoczny, inaczej tabela wygląda na zepsutą zamiast niekompletną.
    expect(
      await screen.findByText(/41 placementów bez przypisanego operatora/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/7 placementów przypisanych do kont spoza puli/),
    ).toBeInTheDocument();
  });

  it("renderuje brak następnego poziomu jako „—”, nie jako zero", async () => {
    respond(BODY);
    renderSection();

    await screen.findByText("Bartosz Nowak");
    // `null` w „Do awansu” i w „Postęp” to brak następnego poziomu. Zero
    // czytałoby się jako „awans tuż-tuż”.
    const expertRow = screen.getByText("Bartosz Nowak").closest("tr");
    expect(expertRow).not.toBeNull();
    expect(expertRow!.textContent).toContain("—");
  });

  it("renderuje 403 jako brak uprawnień, nie jako pustkę", async () => {
    respond(httpError(403));
    renderSection();

    // Kluczowe jest zdanie „Dane NIE są puste” — bez niego 403 czyta się jak
    // informacja, że w firmie nie ma nikogo w tych rolach.
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Dane NIE są puste/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak osób w rolach sourcer/),
    ).not.toBeInTheDocument();
  });

  it("renderuje 500 jako awarię, nie jako pustkę", async () => {
    respond(httpError(500));
    renderSection();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Dane mogą istnieć/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak osób w rolach sourcer/),
    ).not.toBeInTheDocument();
  });

  it("wypisuje spadek poziomu NAD tabelą, z obiema wartościami", async () => {
    // Sekcja mówi obok, że „poziom raz osiągnięty zostaje”. Spadek jest więc
    // sprzeczny z regułą, którą czytelnik właśnie przeczytał — schowanie go
    // pod tabelą albo w szczególe zostawiłoby na ekranie samą sprzeczność.
    respond({
      ...BODY,
      regressions: [
        {
          user_id: 2,
          name: "Bogna Ekspertka",
          level: "senior",
          previous_level: "expert",
          total_placements: 9,
          previous_total_placements: 14,
          observed_at: "2026-08-30T02:00:00+00:00",
          thresholds_fingerprint: "6-6-12-6-12-12-24-12",
        },
      ],
    });
    renderSection();

    expect(await screen.findByText(/Jednej osobie spadł poziom/)).toBeInTheDocument();
    // Obie liczby placementów, bo „spadł na seniora” bez nich nie mówi, o ile.
    expect(await screen.findByText(/14 → 9 placementów/)).toBeInTheDocument();
    // Dwie osobne asercje zamiast jednej po `textContent`: matcher czytający
    // `textContent` trafia w KAŻDEGO przodka (body, div, sekcję), więc zwraca
    // wiele elementów i wywala się na dobrze wyrenderowanym komunikacie.
    expect(
      await screen.findByText(/Poziom nie spada z upływem czasu/),
    ).toBeInTheDocument();
    expect(await screen.findByText("historia przypisań")).toBeInTheDocument();
  });

  it("dziennik bez ani jednej obserwacji NIE udaje „brak regresji”", async () => {
    // `regressions: []` przy `last_observed_at: null` to nie odpowiedź, tylko
    // jej brak: pętla dobowa nigdy nic nie zapisała, więc nie ma z czym
    // porównać dzisiejszych poziomów. Cisza w tym miejscu znaczyłaby
    // „sprawdzono, jest dobrze” i zepsuta pętla wyglądałaby tak w nieskończoność.
    respond({
      ...BODY,
      regressions: [],
      journal: { last_observed_at: null, observations: 0 },
    });
    renderSection();

    expect(
      await screen.findByText(/nie wykonał jeszcze żadnej obserwacji/),
    ).toBeInTheDocument();
    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
  });

  it("`null` mówi, że NIE WIADOMO — nie renderuje ciszy", async () => {
    // `null` znaczy „dziennika nie dało się odczytać". Cisza w tym miejscu
    // czyta się jako „nikomu nic nie spadło", czyli awaria udająca wynik.
    // Tabela poziomów ma przy tym dojechać — to właściwa treść sekcji.
    respond({ ...BODY, regressions: null });
    renderSection();

    expect(
      await screen.findByText(/Nie udało się sprawdzić, czy komuś spadł poziom/),
    ).toBeInTheDocument();
    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(screen.queryByText(/Spadek poziomu/)).not.toBeInTheDocument();
  });

  it("bez regresji nie renderuje pustego ostrzeżenia", async () => {
    // Pusta ramka „0 spadków” uczy ignorować to miejsce, więc gdy spadek
    // naprawdę wystąpi, nikt go nie zauważy.
    respond(BODY);
    renderSection();

    expect(await screen.findByText(/Ścieżka rozwoju/)).toBeInTheDocument();
    expect(screen.queryByText(/spadł poziom/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Spadek poziomu/)).not.toBeInTheDocument();
  });
});
