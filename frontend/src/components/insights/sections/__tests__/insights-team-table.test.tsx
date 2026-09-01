/**
 * „Performance per osoba" — sekcja `/insights` → Rekrutacja.
 *
 * Sześć reguł pod ochroną. Każda jest o tym, że wiersz na ekranie znaczy
 * co innego, niż wygląda:
 *
 * 1. **`unattributed` jest WIDOCZNE obok sumy kolumny.** Kamień bez autora
 *    nie ma wiersza, ale wchodzi do lejka. Wycięty po cichu sprawia, że suma
 *    kolumny nie zgadza się z lejkiem — a tabela wygląda wtedy na ZEPSUTĄ,
 *    nie na niekompletną.
 * 2. **Były pracownik ZOSTAJE.** Jego wyniki nie znikają z historii firmy.
 * 3. **Medal to pozycja w RANKINGU, nie w liście.** Przy sortowaniu rosnąco
 *    lub alfabetycznie podium nie istnieje — złoty krążek przy najsłabszym
 *    wyniku czytałby się jako pochwała.
 * 4. **Awaria ≠ pustka.** 403 i 500 renderują się jako awaria, nigdy jako
 *    „nikt nic nie zrobił".
 * 5. **Wiersz bez nazwy nadal się liczy.** Konto zniknęło, dorobek został.
 * 6. **`renderFlags` to gniazdo, nie zależność.** Sekcja renderuje flagi
 *    wstrzyknięte przez integratora i działa bez nich.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import {
  InsightsTeamTable,
  initialsOf,
  sortRows,
} from "@/components/insights/sections/InsightsTeamTable";
import type { TeamTableResponse, TeamTableRow } from "@/lib/insights-team-api";

const URL = "/api/insights/team-table";

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

function renderSection(
  props: { renderFlags?: (id: number) => React.ReactNode } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InsightsTeamTable period={{ period: "month", offset: -1 }} {...props} />
    </QueryClientProvider>,
  );
}

function row(
  overrides: Partial<TeamTableRow> & { user_id: number },
): TeamTableRow {
  return {
    name: `Osoba ${overrides.user_id}`,
    role: "sourcer",
    role_label: "Sourcer",
    is_active: true,
    verifications: 0,
    recommendations: 0,
    interviews: 0,
    placements: 0,
    total: 0,
    ...overrides,
  };
}

const BODY: TeamTableResponse = {
  period: {
    kind: "month",
    start: "2026-08-01T00:00:00+02:00",
    end: "2026-09-01T00:00:00+02:00",
    timezone: "Europe/Warsaw",
  },
  columns: [
    { key: "verifications", label: "Weryfikacje", stage: "verified" },
    { key: "recommendations", label: "Rekomendacje", stage: "cv_sent" },
    { key: "interviews", label: "Interviews", stage: "interview" },
    { key: "placements", label: "Placements", stage: "hired" },
  ],
  rows: [
    row({
      user_id: 1,
      name: "Monika Czapla",
      role: "recruiter",
      role_label: "Rekruter",
      verifications: 22,
      recommendations: 9,
      interviews: 1,
      placements: 0,
      total: 32,
    }),
    row({
      user_id: 2,
      name: "Ewa Kalata",
      role: "recruiter",
      role_label: "Rekruter",
      verifications: 20,
      recommendations: 10,
      interviews: 2,
      placements: 0,
      total: 32,
    }),
    row({
      user_id: 3,
      name: "Katarzyna Orlińska",
      role: "tac",
      role_label: "TAC",
      verifications: 19,
      recommendations: 4,
      interviews: 1,
      placements: 0,
      total: 24,
    }),
    // Odeszła z firmy, ale w tym oknie ma dorobek — wiersz musi zostać.
    row({
      user_id: 4,
      name: "Aleksandra Nałęcz",
      is_active: false,
      verifications: 15,
      recommendations: 4,
      interviews: 2,
      placements: 0,
      total: 21,
    }),
    // Placementy ma tylko ta osoba — po przesortowaniu wskoczy na górę.
    row({
      user_id: 5,
      name: "Marlena Rosół",
      role: "tac",
      role_label: "TAC",
      verifications: 0,
      recommendations: 0,
      interviews: 0,
      placements: 2,
      total: 2,
    }),
  ],
  totals: {
    attributed: {
      verifications: 76,
      recommendations: 27,
      interviews: 6,
      placements: 2,
    },
    unattributed: {
      verifications: 3,
      recommendations: 0,
      interviews: 1,
      placements: 0,
    },
    all: {
      verifications: 79,
      recommendations: 27,
      interviews: 7,
      placements: 2,
    },
    users: 5,
    former_employees: 1,
  },
};

beforeEach(() => {
  mocks.get.mockReset();
});

function bodyRowNames(): string[] {
  const table = screen.getByRole("table");
  const bodyRows = within(table).getAllByRole("row").slice(1);
  return bodyRows
    .map((r) => within(r).queryAllByRole("cell")[0]?.textContent ?? "")
    .filter((t) => t.length > 0);
}

describe("InsightsTeamTable", () => {
  it("renderuje cztery kolumny per osoba i podium w domyślnym rankingu", async () => {
    respond(BODY);
    renderSection();

    expect(await screen.findByText("Monika Czapla")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    // Domyślnie: weryfikacje malejąco — medale 1–3 dla trzech najlepszych.
    expect(screen.getByLabelText("Miejsce 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Miejsce 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Miejsce 3")).toBeInTheDocument();
    expect(screen.queryByLabelText("Miejsce 4")).not.toBeInTheDocument();
    // Podium siedzi na trzech pierwszych WIERSZACH, nie na trzech pierwszych
    // osobach z odpowiedzi — sortowanie jest po stronie klienta.
    const names = bodyRowNames();
    expect(names[0]).toContain("Monika Czapla");
    expect(names[2]).toContain("Katarzyna Orlińska");
  });

  it("pokazuje nieprzypisane kamienie obok sumy kolumny", async () => {
    respond(BODY);
    renderSection();

    const label = await screen.findByText("Nieprzypisane (bez autora)");
    const unattributedRow = label.closest("tr")!;
    const cells = within(unattributedRow).getAllByRole("cell");
    // Trzy nieprzypisane weryfikacje i jeden interview — per etap, nie jednym
    // skalarem: to dwie różne dziury pod dwiema różnymi kolumnami.
    expect(cells[1]).toHaveTextContent("+3");
    expect(cells[2]).toHaveTextContent("+0");
    expect(cells[3]).toHaveTextContent("+1");

    // I suma, która ma się zgadzać z lejkiem org-level.
    const totalRow = screen
      .getByText("Łącznie (zgodne z lejkiem)")
      .closest("tr")!;
    expect(within(totalRow).getAllByRole("cell")[1]).toHaveTextContent("79");
  });

  it("nie chowa wiersza nieprzypisanych, gdy wszystkie etapy są zerowe", async () => {
    respond({
      ...BODY,
      totals: {
        ...BODY.totals,
        unattributed: {
          verifications: 0,
          recommendations: 0,
          interviews: 0,
          placements: 0,
        },
        all: BODY.totals.attributed,
      },
    });
    renderSection();

    // Wiersz znikający przy zerze nie pozwala odróżnić „sprawdzone, nic nie
    // brakuje" od „nie sprawdzaliśmy".
    expect(
      await screen.findByText("Nieprzypisane (bez autora)"),
    ).toBeInTheDocument();
  });

  it("zostawia byłego pracownika w tabeli i oznacza go chipem", async () => {
    respond(BODY);
    renderSection();

    const name = await screen.findByText("Aleksandra Nałęcz");
    const personCell = name.closest("td")!;
    expect(within(personCell).getByText("były pracownik")).toBeInTheDocument();
    // Jej liczby zostają w tabeli — offboarding nie kasuje historii wstecz.
    const tableRow = name.closest("tr")!;
    expect(within(tableRow).getAllByRole("cell")[2]).toHaveTextContent("15");
  });

  it("sortuje po kliknięciu nagłówka kolumny", async () => {
    respond(BODY);
    renderSection();

    await screen.findByText("Monika Czapla");
    fireEvent.click(screen.getByRole("button", { name: /Placements/i }));

    const names = bodyRowNames();
    expect(names[0]).toContain("Marlena Rosół");
    expect(screen.getByLabelText("Miejsce 1")).toBeInTheDocument();
  });

  it("zdejmuje medale przy sortowaniu, które nie jest rankingiem", async () => {
    respond(BODY);
    renderSection();

    await screen.findByText("Monika Czapla");
    fireEvent.click(screen.getByRole("button", { name: /Osoba/i }));

    expect(bodyRowNames()[0]).toContain("Aleksandra Nałęcz");
    expect(screen.queryByLabelText("Miejsce 1")).not.toBeInTheDocument();
  });

  it("liczy wiersz z nieznanym kontem zamiast zwijać go do nieprzypisanych", async () => {
    respond({
      ...BODY,
      rows: [
        row({
          user_id: 99,
          name: null,
          role: null,
          role_label: null,
          is_active: null,
          verifications: 4,
          total: 4,
        }),
      ],
    });
    renderSection();

    expect(
      await screen.findByText("Nieznany użytkownik (#99)"),
    ).toBeInTheDocument();
    // Brak konta ≠ były pracownik — nie wiemy, więc nie twierdzimy.
    expect(screen.queryByText("były pracownik")).not.toBeInTheDocument();
  });

  it("renderuje plakietki ostrzeżeń wstrzyknięte przez integratora", async () => {
    respond(BODY);
    const renderFlags = vi.fn((userId: number) =>
      userId === 1 ? <span>Słabe wyniki</span> : null,
    );
    renderSection({ renderFlags });

    expect(await screen.findByText("Słabe wyniki")).toBeInTheDocument();
    expect(renderFlags).toHaveBeenCalledWith(1);
  });

  it.each([403, 500])("renderuje awarię (%i), nie pustkę", async (status) => {
    respond(httpError(status));
    renderSection();

    // Zdania Z OPISU, nie z nagłówka: „Nie udało się pobrać danych" pada
    // w `QueryStateNotice` dwa razy (tytuł + opis), więc `findByText` na tym
    // fragmencie wywala się na wielokrotnym trafieniu zamiast czegokolwiek
    // sprawdzić. Opis jest jednoznaczny i to on niesie treść, na której nam
    // zależy: „dane NIE są puste" / „dane mogą istnieć".
    expect(
      await screen.findByText(
        status === 403 ? /Dane NIE są puste/i : /Dane mogą istnieć/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nikt nie odnotował kamienia milowego/i),
    ).not.toBeInTheDocument();
  });

  it("rozróżnia pustkę od pustki z nieprzypisanym ruchem", async () => {
    respond({
      ...BODY,
      rows: [],
      totals: {
        attributed: {
          verifications: 0,
          recommendations: 0,
          interviews: 0,
          placements: 0,
        },
        unattributed: {
          verifications: 2,
          recommendations: 0,
          interviews: 0,
          placements: 0,
        },
        all: {
          verifications: 2,
          recommendations: 0,
          interviews: 0,
          placements: 0,
        },
        users: 0,
        former_employees: 0,
      },
    });
    renderSection();

    expect(
      await screen.findByText(/Nikt nie odnotował kamienia milowego/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/2 kamieni bez przypisanego autora/i),
    ).toBeInTheDocument();
  });
});

describe("sortRows / initialsOf", () => {
  it("trzyma wiersz bez nazwiska na końcu w obie strony", () => {
    const rows = [
      row({ user_id: 1, name: null }),
      row({ user_id: 2, name: "Anna Nowak" }),
    ];
    expect(sortRows(rows, "person", "asc")[0]!.name).toBe("Anna Nowak");
    expect(sortRows(rows, "person", "desc")[0]!.name).toBe("Anna Nowak");
  });

  it("rozstrzyga remis nazwiskiem, żeby kolejność nie migała", () => {
    const rows = [
      row({ user_id: 1, name: "Zofia Zet", verifications: 5 }),
      row({ user_id: 2, name: "Anna Nowak", verifications: 5 }),
    ];
    expect(sortRows(rows, "verifications", "desc").map((r) => r.name)).toEqual([
      "Anna Nowak",
      "Zofia Zet",
    ]);
  });

  it("buduje inicjały z polskich znaków i znosi brak nazwiska", () => {
    expect(initialsOf("Julia Świdkiewicz")).toBe("JŚ");
    expect(initialsOf(null)).toBe("?");
  });
});
