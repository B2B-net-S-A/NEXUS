import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ClientFormField, ClientFormYears, ClientFormYearsRole } from "@/lib/api/clientForms";

import { ClientFormYearsGrid } from "../ClientFormYearsGrid";

const role = (over: Partial<ClientFormYearsRole>): ClientFormYearsRole => ({
  key: "r1",
  employer: "Firma Alfa",
  title: "Tester",
  start: "2025-03",
  end: "2025-12",
  period: "03.2025 – 12.2025",
  quote: "03.2025 – 12.2025 Tester / Firma Alfa",
  level: "role",
  evidence: "zgłaszanie błędów w Jira",
  on: true,
  ...over,
});

const R1 = role({});
const R2 = role({
  key: "r2",
  employer: "Firma Beta",
  start: "2024-05",
  end: "2024-12",
  period: "05.2024 – 12.2024",
  quote: "05.2024 – 12.2024 Młodszy tester / Firma Beta",
  level: "implied",
  evidence: "testy regresji w projekcie dla NFZ",
});

const years = (over: Partial<ClientFormYears>): ClientFormYears => ({
  kind: "competency",
  basis: [],
  skills: null,
  minimum_months: null,
  thresholds: [],
  max_points: null,
  question: "Pytanie?",
  ask: false,
  months: 0,
  ...over,
});

const field = (over: Partial<ClientFormField>): ClientFormField => ({
  id: "t2.r3.c3",
  kind: "cell",
  label: "Liczba lat doświadczenia",
  section: null,
  row_label: "Narzędzia do zarządzania testami (JIRA, Xray)",
  table: "Kompetencje",
  value: "1 rok 6 mies.",
  source: "cv",
  quote: null,
  ...over,
});

const FIELDS: ClientFormField[] = [
  field({
    id: "p4",
    kind: "line",
    label: "Łączna liczba lat doświadczenia zawodowego",
    row_label: null,
    value: "1 rok 6 mies.",
    years: years({ kind: "total", basis: [R1, R2] }),
  }),
  field({ years: years({ basis: [R1, R2] }) }),
  field({
    id: "t2.r2.c3",
    row_label: "Znajomość języka SQL;",
    value: null,
    source: null,
    years: years({
      skills: "SQL, Postman",
      question: "Znajomość języka SQL — w której firmie i od kiedy do kiedy?",
    }),
  }),
  field({
    id: "t2.r10.c2",
    row_label: "Doświadczenie w pracy z wtyczką do Jira Xray",
    value: null,
    source: null,
    years: years({ question: "Doświadczenie w pracy z wtyczką do Jira Xray — w której firmie i od kiedy do kiedy?" }),
  }),
];

function renderGrid(props: Partial<React.ComponentProps<typeof ClientFormYearsGrid>> = {}) {
  const onSaveRoles = vi.fn();
  const onAsk = vi.fn();
  render(<ClientFormYearsGrid fields={FIELDS} onSaveRoles={onSaveRoles} onAsk={onAsk} {...props} />);
  return { onSaveRoles, onAsk };
}

describe("ClientFormYearsGrid — lata w kompetencjach z ról w CV", () => {
  it("pokazuje role jako kolumny, wprost i pośrednio zaznaczone, braki z „dopytaj”", () => {
    renderGrid();
    const grid = screen.getByTestId("client-form-years");
    expect(within(grid).getByText("Firma Alfa")).toBeInTheDocument();
    expect(within(grid).getByText("05.2024 – 12.2024")).toBeInTheDocument();
    const jira = screen.getByText("Narzędzia do zarządzania testami (JIRA, Xray)").closest("tr") as HTMLElement;
    expect(within(jira).getByRole("button", { name: "Firma Alfa: liczy się" })).toHaveTextContent("●");
    expect(within(jira).getByRole("button", { name: "Firma Beta: liczy się" })).toHaveTextContent("◐");
    expect(within(jira).getByText("1 rok 6 mies.")).toBeInTheDocument();
    const sql = screen.getByText("Znajomość języka SQL;").closest("tr") as HTMLElement;
    expect(within(sql).getByText("dopytaj")).toBeInTheDocument();
    expect(within(sql).getByText(/tylko lista umiejętności: „SQL, Postman”/)).toBeInTheDocument();
    // Łączny staż to pierwszy wiersz — też da się w nim zdjąć rolę.
    const total = screen.getByText("Łączna liczba lat doświadczenia zawodowego").closest("tr") as HTMLElement;
    expect(within(total).getByText("1 rok 6 mies.")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[1]).toBe(total);
  });

  it("klik zdejmuje rolę, wartość zmienia się od razu, zapis wysyła wybór", () => {
    const { onSaveRoles } = renderGrid();
    const jira = screen.getByText("Narzędzia do zarządzania testami (JIRA, Xray)").closest("tr") as HTMLElement;
    expect(screen.getByRole("button", { name: "Lata zapisane" })).toBeDisabled();
    fireEvent.click(within(jira).getByRole("button", { name: "Firma Beta: liczy się" }));
    expect(within(jira).getByRole("button", { name: "Firma Beta: nie liczy się" })).toHaveTextContent("○");
    expect(within(jira).getByText("10 mies.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz lata · 1" }));
    expect(onSaveRoles).toHaveBeenCalledWith({ "t2.r3.c3": ["r1"] });
  });

  it("braki bez żadnej roli idą do ściągi screeningu", () => {
    const { onAsk } = renderGrid();
    const asks = screen.getByLabelText("Do dopytania");
    expect(within(asks).getByText(/Lat nie ma w CV · 2/)).toBeInTheDocument();
    fireEvent.click(within(asks).getByRole("checkbox", { name: "Znajomość języka SQL;" }));
    fireEvent.click(within(asks).getByRole("button", { name: /Dodaj do ściągi screeningu · 1/ }));
    expect(onAsk).toHaveBeenCalledWith(["t2.r10.c2"]);
  });

  it("tylko do odczytu: bez zapisu i bez wysyłki pytań", () => {
    renderGrid({ readOnly: true });
    expect(screen.queryByRole("button", { name: /Zapisz lata|Lata zapisane/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ściągi screeningu/ })).not.toBeInTheDocument();
    for (const cell of screen.getAllByRole("button", { name: "Firma Alfa: liczy się" })) expect(cell).toBeDisabled();
  });
});
