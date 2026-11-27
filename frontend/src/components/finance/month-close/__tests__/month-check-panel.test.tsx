import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MonthCheckCase, MonthCheckView } from "@/lib/api/client-settlements";

import { caseDetail, matchesState, MonthCheckPanel } from "../MonthCheckPanel";

// Osoby, klienci, faktury i kwoty zmyślone.
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));

function row(patch: Partial<MonthCheckCase> = {}): MonthCheckCase {
  return {
    id: 1,
    kind: "hours_mismatch",
    kind_label: "Inne godziny u klienta i u konsultanta",
    month: "2026-10",
    candidate_id: 5,
    person: "Jan Przykładowy",
    contract_id: 9,
    client_id: 7,
    client: "Firma Testowa",
    amount: "6000.00",
    currency: "PLN",
    data_issue: null,
    data_issue_label: null,
    details: {
      client_hours: "160.00",
      contractor_hours: "200.00",
      sales_invoices: ["FS/1/11/2026"],
      contractor_invoices: [{ number: "K/10/2026" }],
    },
    state: "new",
    reason: null,
    decided_at: null,
    first_seen_at: "2026-11-25T02:00:00+00:00",
    closed_at: null,
    ...patch,
  };
}

function view(cases: MonthCheckCase[], patch: Partial<MonthCheckView> = {}): MonthCheckView {
  return {
    month: "2026-10",
    checked_at: "2026-11-25T02:00:00+00:00",
    waits_until: null,
    amounts: true,
    summary: {
      person_months: 470,
      matched: 360,
      skipped: { parallel_contracts: 5 },
      overtime_confirmed: 39,
      cases: cases.length,
      cases_amount: "6000.00",
      open: cases.filter((c) => c.state === "new" || c.state === "to_correct").length,
      open_amount: "6000.00",
      by_state: { new: 1, to_correct: 0, explained: 1, closed: 0 },
      by_kind: { hours_mismatch: 1, cost_without_sale: 0, sale_without_cost: 0, over_working_days: 0 },
    },
    cases,
    ...patch,
  };
}

function setup(data: MonthCheckView | Error) {
  mocks.get.mockImplementation(() => (data instanceof Error ? Promise.reject(data) : Promise.resolve({ data })));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MonthCheckPanel month="2026-10" />
    </QueryClientProvider>,
  );
}

describe("MonthCheckPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("podsumowanie, wiersz z kwotą i fakturami, domyślnie otwarte", async () => {
    setup(view([row(), row({ id: 2, person: "Anna Zmyślona", state: "explained", reason: "Klient przyjął 15 MD" })]));
    expect(await screen.findByText("360 z 470")).toBeInTheDocument();
    expect(screen.getByText(/dwa kontrakty w miesiącu 5/)).toBeInTheDocument();
    expect(screen.getByText("Jan Przykładowy")).toBeInTheDocument();
    expect(screen.queryByText("Anna Zmyślona")).not.toBeInTheDocument();
    expect(screen.getByText(/FS\/1\/11\/2026/)).toBeInTheDocument();
    expect(screen.getByText(/K\/10\/2026/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Wyjaśnione 1/ }));
    expect(screen.getByText("Anna Zmyślona")).toBeInTheDocument();
    expect(screen.getByText("Klient przyjął 15 MD")).toBeInTheDocument();
  });

  it("„Wyjaśnione” wymaga powodu i wysyła go", async () => {
    mocks.post.mockResolvedValue({ data: row({ state: "explained", reason: "OK" }) });
    setup(view([row()]));
    const line = (await screen.findByText("Jan Przykładowy")).closest("tr") as HTMLElement;
    fireEvent.click(within(line).getByRole("button", { name: "Wyjaśnione" }));
    const save = await screen.findByRole("button", { name: "Zapisz" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Powód"), { target: { value: "Klient przyjął 15 MD" } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/month-check/1/decision", {
        action: "explained",
        reason: "Klient przyjął 15 MD",
      }),
    );
  });

  it("po zapisie okno dla kolejnej sprawy ma pusty powód", async () => {
    mocks.post.mockResolvedValue({ data: row({ state: "explained", reason: "OK" }) });
    setup(view([row(), row({ id: 2, person: "Anna Zmyślona" })]));
    const first = (await screen.findByText("Jan Przykładowy")).closest("tr") as HTMLElement;
    fireEvent.click(within(first).getByRole("button", { name: "Wyjaśnione" }));
    fireEvent.change(await screen.findByLabelText("Powód"), { target: { value: "Klient przyjął 15 MD" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(screen.queryByLabelText("Powód")).not.toBeInTheDocument());

    const second = screen.getByText("Anna Zmyślona").closest("tr") as HTMLElement;
    fireEvent.click(within(second).getByRole("button", { name: "Wyjaśnione" }));
    expect(await screen.findByLabelText("Powód")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  });

  it("„Do korekty” bez okna", async () => {
    mocks.post.mockResolvedValue({ data: row({ state: "to_correct" }) });
    setup(view([row()]));
    fireEvent.click(await screen.findByRole("button", { name: "Do korekty" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/month-check/1/decision", { action: "to_correct", reason: null }),
    );
  });

  it("awaria to komunikat, nie pusta lista", async () => {
    setup(new Error("boom"));
    expect(await screen.findByText("Nie udało się pobrać rozbieżności.")).toBeInTheDocument();
    expect(screen.queryByText("Bez rozbieżności w tym miesiącu.")).not.toBeInTheDocument();
  });

  it("miesiąc niesprawdzony i bez kwot", async () => {
    setup(view([row({ amount: null })], { checked_at: null, amounts: false }));
    expect(await screen.findByText(/jeszcze nie sprawdzał/)).toBeInTheDocument();
    expect(screen.getAllByText("–").length).toBeGreaterThan(0);
  });

  it("opis i filtr stanu", () => {
    expect(caseDetail(row())).toBe("klient 160 h · konsultant ok. 200 h");
    expect(caseDetail(row({ kind: "cost_without_sale" }))).toMatch(/u klienta tej osoby nie ma/);
    expect(matchesState("open", "to_correct")).toBe(true);
    expect(matchesState("open", "explained")).toBe(false);
    expect(matchesState("closed", "closed")).toBe(true);
  });
});
