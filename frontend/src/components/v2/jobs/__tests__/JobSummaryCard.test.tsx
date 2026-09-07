/**
 * `JobSummaryCard` — sekcja „Zlecenie" kroku 02 (program „flow w języku C2", PR 5/7).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobSummaryCard } from "@/components/v2/jobs/JobSummaryCard";

const fullJob = {
  title: "Programista Python",
  client_name: "PKO Bank Polski",
  recruitment_type: "body_leasing",
  salary_min: 15000,
  salary_max: 22000,
  location: "Warszawa / hybryda",
  // Południe UTC, nie sama data — `formatDate` renderuje w strefie lokalnej
  // testu; sam "2026-09-30" (północ UTC) cofnąłby się na 29.09 w strefach
  // za UTC.
  deadline: "2026-09-30T12:00:00Z",
};

describe("JobSummaryCard — dane", () => {
  it("renderuje sześć pól z wartościami zlecenia", () => {
    render(<JobSummaryCard job={fullJob} />);

    expect(screen.getByText("Programista Python")).toBeInTheDocument();
    expect(screen.getByText("PKO Bank Polski")).toBeInTheDocument();
    expect(screen.getByText("Body leasing")).toBeInTheDocument();
    // `toLocaleString("pl-PL")` grupuje tysiące spacją NIEROZDZIELAJĄCĄ
    // (U+00A0). Testing Library normalizuje TYLKO tekst z DOM-u (kolapsuje
    // `\s+`, w tym U+00A0, do zwykłej spacji) — matcher-string porównuje z
    // `String(matcher)` bez normalizacji (`@testing-library/dom/dist/
    // matches.js`). Zwykła spacja w oczekiwanym stringu jest więc POPRAWNA:
    // to jest to, na co U+00A0 się znormalizuje. Zbudowanie matchera przez
    // `toLocaleString` (żeby "nie zgadywać znaku") byłoby błędem — przeniosłoby
    // nieznormalizowany U+00A0 do matchera i test przestałby cokolwiek
    // znajdować (zweryfikowane empirycznie).
    expect(screen.getByText("15 000–22 000 PLN/mies.")).toBeInTheDocument();
    expect(screen.getByText("Warszawa / hybryda")).toBeInTheDocument();
    expect(screen.getByText("30.09.2026")).toBeInTheDocument();
  });

  it("nagłówek karty to „Zlecenie”", () => {
    render(<JobSummaryCard job={fullJob} />);
    expect(screen.getByText("Zlecenie")).toBeInTheDocument();
  });
});

describe("JobSummaryCard — pola brakujące renderują się jako „—”, nie znikają", () => {
  it("brak klienta/typu/widełek/lokalizacji/deadline'u", () => {
    render(
      <JobSummaryCard
        job={{
          title: "Rola bez reszty pól",
          client_name: null,
          recruitment_type: null,
          salary_min: null,
          salary_max: null,
          location: null,
          deadline: null,
        }}
      />,
    );
    // 5 pól bez klienta/typu/widełek/lokalizacji/deadline'u — tytuł ma wartość.
    expect(screen.getAllByText("—")).toHaveLength(5);
  });

  it("tylko jeden koniec widełek (dolny) formatuje się jako „od X PLN”", () => {
    render(<JobSummaryCard job={{ ...fullJob, salary_max: null }} />);
    expect(screen.getByText("od 15 000 PLN/mies.")).toBeInTheDocument();
  });

  it("tylko górny koniec widełek formatuje się jako „do X PLN”", () => {
    render(<JobSummaryCard job={{ ...fullJob, salary_min: null }} />);
    expect(screen.getByText("do 22 000 PLN/mies.")).toBeInTheDocument();
  });

  it("typ nieznany w słowniku pokazuje surową wartość zamiast zniknąć", () => {
    render(<JobSummaryCard job={{ ...fullJob, recruitment_type: "unknown_type" }} />);
    expect(screen.getByText("unknown_type")).toBeInTheDocument();
  });
});

describe("JobSummaryCard — przycisk Edytuj (RBAC)", () => {
  it("bez `onEdit` przycisk się nie renderuje (odczyt bez prawa zapisu)", () => {
    render(<JobSummaryCard job={fullJob} />);
    expect(screen.queryByRole("button", { name: "Edytuj" })).not.toBeInTheDocument();
  });

  it("z `onEdit` przycisk woła TEN SAM callback (otwiera istniejący EditJobModal, nie duplikuje formularza)", () => {
    const onEdit = vi.fn();
    render(<JobSummaryCard job={fullJob} onEdit={onEdit} />);
    const button = screen.getByRole("button", { name: "Edytuj" });
    button.click();
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
