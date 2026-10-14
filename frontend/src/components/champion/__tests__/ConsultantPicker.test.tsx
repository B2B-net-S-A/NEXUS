/**
 * Wybór konsultanta w weryfikacji Profilu Championa — zgłoszenie Marcina
 * z 14.10.2026: „System mi nie pozwala wybrać innych konsultantów, miałem do
 * wyboru z 20, a akurat nie ma tego, którego miałem”.
 *
 * Plik trzyma trzy drogi do osoby, której nie ma na liście „U tego klienta”:
 * szukanie po nazwisku (bez polskich znaków), szukanie w całej bazie i wpis
 * ręczny — oraz to, że awaria listy nie udaje „nikogo nie ma”.
 */
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ConsultantPicker,
  type ConsultantChoice,
} from "@/components/champion/ConsultantPicker";
import type { ChampionConsultantSuggestion } from "@/lib/api";

const getMock = vi.fn();
const suggestionsMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { get: (...args: unknown[]) => getMock(...args) },
    championApi: {
      ...actual.championApi,
      consultantSuggestions: (...args: unknown[]) => suggestionsMock(...args),
    },
  };
});

const AT_CLIENT: ChampionConsultantSuggestion[] = Array.from({ length: 24 }, (_, i) => ({
  candidate_id: 100 + i,
  name: `Osoba${String(i).padStart(2, "0")} Przykładowa`,
  job_title: i === 0 ? "Java Developer" : null,
  since: null,
})).concat({
  candidate_id: 200,
  name: "Piotr Studziński",
  job_title: "Analityk",
  since: null,
});

let lastChoice: ConsultantChoice | null = null;

function Harness() {
  const [value, setValue] = useState<ConsultantChoice | null>(null);
  lastChoice = value;
  return <ConsultantPicker jobId={7} value={value} onChange={setValue} />;
}

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  lastChoice = null;
  getMock.mockReset();
  getMock.mockResolvedValue({ data: { items: [] } });
  suggestionsMock.mockReset();
  suggestionsMock.mockResolvedValue({ data: AT_CLIENT });
});

describe("ConsultantPicker", () => {
  it("pokazuje wszystkich konsultantów klienta i zawęża po nazwisku bez polskich znaków", async () => {
    const user = userEvent.setup();
    renderPicker();

    expect(await screen.findAllByTestId("consultant-picker-option")).toHaveLength(25);
    expect(screen.getByText(/Nasi konsultanci u tego klienta · 25/)).toBeInTheDocument();

    await user.type(screen.getByTestId("consultant-picker-search"), "studzin");
    const options = screen.getAllByTestId("consultant-picker-option");
    expect(options).toHaveLength(1);
    await user.click(options[0]);

    expect(lastChoice).toEqual({ candidateId: 200, name: "Piotr Studziński", detail: "Analityk" });
    expect(screen.getByTestId("consultant-picker-selected")).toHaveTextContent("Piotr Studziński");
  });

  it("osobę spoza listy klienta znajduje w całej bazie, bez dubli z listy", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({
      data: {
        items: [
          { id: 200, name: "Piotr", lastname: "Studziński", email: "ps@example.com" },
          { id: 900, name: "Marek", lastname: "Spozalisty", email: "ms@example.com" },
        ],
      },
    });
    renderPicker();
    await screen.findAllByTestId("consultant-picker-option");

    await user.type(screen.getByTestId("consultant-picker-search"), "Spozalisty");

    const base = await screen.findAllByTestId("consultant-picker-base-option");
    expect(base).toHaveLength(1);
    expect(getMock).toHaveBeenLastCalledWith("/api/candidates", {
      params: { q: "Spozalisty", page_size: 8, sort: "relevance" },
    });
    expect(
      within(screen.getByRole("group", { name: "U tego klienta" })).getByText(
        /Nikt u tego klienta nie pasuje/,
      ),
    ).toBeInTheDocument();

    await user.click(base[0]);
    expect(lastChoice).toEqual({
      candidateId: 900,
      name: "Marek Spozalisty",
      detail: "ms@example.com",
    });

    // „Zmień” wraca do szukania — wybór nie zamyka drogi do innej osoby.
    await user.click(screen.getByTestId("consultant-picker-change"));
    expect(lastChoice).toBeNull();
    expect(screen.getByTestId("consultant-picker-search")).toBeInTheDocument();
  });

  it("osobę spoza NEXUSA zapisuje z wpisanego imienia i nazwiska", async () => {
    const user = userEvent.setup();
    renderPicker();
    await screen.findAllByTestId("consultant-picker-option");

    await user.type(screen.getByTestId("consultant-picker-search"), "  Jan Zewnętrzny ");
    await user.click(screen.getByTestId("consultant-picker-manual"));

    expect(lastChoice).toEqual({ candidateId: null, name: "Jan Zewnętrzny" });
    expect(screen.getByTestId("consultant-picker-selected")).toHaveTextContent(
      "wpisane ręcznie",
    );
  });

  it("awaria listy klienta to komunikat błędu, nie „system nie znalazł”", async () => {
    suggestionsMock.mockRejectedValue(new Error("500"));
    renderPicker();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać konsultantów tego klienta",
    );
    expect(screen.queryByTestId("consultant-picker-none-at-client")).not.toBeInTheDocument();
    expect(screen.getByTestId("consultant-picker-search")).toBeEnabled();
  });

  it("pusta lista klienta mówi, jak dojść do osoby", async () => {
    suggestionsMock.mockResolvedValue({ data: [] });
    renderPicker();

    expect(await screen.findByTestId("consultant-picker-none-at-client")).toHaveTextContent(
      "wyszukaj osobę w bazie albo wpisz imię i nazwisko",
    );
  });
});
