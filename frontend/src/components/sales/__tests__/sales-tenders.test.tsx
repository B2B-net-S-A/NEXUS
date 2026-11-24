/** Sprzedaż → Leady → Przetargi (decyzja Artura z 24.11.2026, wariant B). Dane fikcyjne. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TenderNotice, Tenders, TenderStatus } from "@/lib/api/sales-tenders";

import { deadlineLabel } from "../tenders/tender-dates";

const restore = vi.fn();
const run = vi.fn();
const refetch = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };
type Query = { data?: Tenders; isLoading: boolean; isSuccess: boolean; error: unknown; refetch: () => void };
let queries: Record<TenderStatus, Query>;

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales-tenders", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-tenders")>()),
  useSalesTenders: (status: TenderStatus) => queries[status],
  useRestoreTender: () => ({ mutate: restore, isPending: false }),
  useRunTenders: () => ({ mutate: run, isPending: false }),
  useTenderRules: () => ({ data: undefined, isLoading: true, isSuccess: false, error: null, refetch }),
  useSaveTenderRules: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { TendersView } from "../tenders/TendersView";

function notice(over: Partial<TenderNotice>): TenderNotice {
  return {
    id: 1,
    source: "bzp",
    number: "2026/BZP 00000001",
    title: "Usługi zespołu programistów",
    buyer_name: "Urząd Przykładowy",
    buyer_city: "Warszawa",
    url: "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/abc",
    published_at: "2026-11-20T10:00:00Z",
    deadline_date: "2026-12-04",
    deadline_at: "2026-12-04T09:00:00Z",
    status: "created",
    rule: null,
    rule_label: null,
    rule_detail: null,
    match_detail: "fraza „programista”",
    opportunity_id: 501,
    opportunity_status: "open",
    opportunity_stage: "Identyfikacja",
    restored_by: null,
    restored_at: null,
    ...over,
  };
}

function data(over: Partial<Tenders>): Tenders {
  return {
    enabled: true,
    can_run: false,
    can_edit: true,
    last_run: {
      status: "ok",
      trigger: "schedule",
      started_at: "2026-11-24T04:31:00Z",
      finished_at: "2026-11-24T04:32:00Z",
      error: null,
      counts: { bzp: 612, ted: 21, it: 15, created: 5, rejected: 10, closed: 2 },
    },
    created: 1,
    rejected: 2,
    items: [],
    ...over,
  };
}

function ok(value: Tenders): Query {
  return { data: value, isLoading: false, isSuccess: true, error: null, refetch };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-24T08:00:00Z"));
  vi.clearAllMocks();
  queries = {
    created: ok(data({ items: [notice({})] })),
    rejected: ok(
      data({
        items: [
          notice({
            id: 2,
            status: "rejected",
            rule: "buyer",
            rule_label: "Zamawiający",
            rule_detail: "szpital",
            buyer_name: "Szpital Przykładowy",
            opportunity_id: null,
            opportunity_status: null,
            opportunity_stage: null,
          }),
          notice({
            id: 3,
            status: "rejected",
            rule: "expired",
            rule_label: "Termin minął",
            deadline_date: "2026-11-20",
            deadline_at: "2026-11-20T09:00:00Z",
            opportunity_id: null,
          }),
        ],
      }),
    ),
  };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TendersView", () => {
  it("pokazuje założone szanse z terminem, powodem i linkiem do szansy", () => {
    render(<TendersView />);
    expect(screen.getByRole("radio", { name: "Założone szanse (1)" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("tenders-last-run")).toHaveTextContent("BZP 612, TED 21 · do bramki 15 · założone 5");
    const row = screen.getByText("Usługi zespołu programistów").closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("04.12, 10:00")).toBeInTheDocument();
    expect(cells.getByText("za 10 dni")).toBeInTheDocument();
    expect(cells.getByText("fraza „programista”")).toBeInTheDocument();
    expect(cells.getByRole("link", { name: "Identyfikacja" })).toHaveAttribute("href", "/sales/opportunities/501");
    expect(cells.getByRole("link", { name: /BZP 2026\/BZP 00000001/ })).toHaveAttribute(
      "href",
      "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/abc",
    );
  });

  it("odsiane mają regułę, a „Przywróć” tylko przed terminem", () => {
    render(<TendersView />);
    fireEvent.click(screen.getByRole("radio", { name: "Odsiane (2)" }));
    const hospital = within(screen.getByText("Szpital Przykładowy").closest("tr") as HTMLElement);
    expect(hospital.getByText("Zamawiający")).toBeInTheDocument();
    expect(hospital.getByText("„szpital”")).toBeInTheDocument();
    fireEvent.click(hospital.getByRole("button", { name: "Przywróć" }));
    expect(restore).toHaveBeenCalledWith(2, expect.any(Object));
    const late = within(screen.getByText("Termin minął").closest("tr") as HTMLElement);
    expect(late.queryByRole("button", { name: "Przywróć" })).toBeNull();
    expect(late.getByText("po terminie")).toBeInTheDocument();
  });

  it("nieudany bieg to czerwony pasek, nie pusta lista", () => {
    queries.created = ok(
      data({
        items: [],
        last_run: {
          status: "failed",
          started_at: "2026-11-24T04:31:00Z",
          error: "Rejestr BZP nie odpowiedział.",
          counts: {},
        },
      }),
    );
    render(<TendersView />);
    expect(screen.getByText(/się nie udał/)).toBeInTheDocument();
    expect(screen.getByText("Rejestr BZP nie odpowiedział.")).toBeInTheDocument();
  });

  it("błąd zapytania nie wygląda jak pusta lista", () => {
    queries.created = { data: undefined, isLoading: false, isSuccess: false, error: { response: { status: 500 } }, refetch };
    render(<TendersView />);
    expect(screen.queryByText(/nie założyła żadnej szansy/)).toBeNull();
    expect(screen.getByText("Nie udało się pobrać danych")).toBeInTheDocument();
  });

  it("administrator uruchamia bieg, a przy wyłączonej fladze widzi to na ekranie", () => {
    queries.created = ok(data({ enabled: false, can_run: true, items: [notice({})] }));
    render(<TendersView />);
    expect(screen.getByText("Bieg codzienny wyłączony")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Uruchom teraz" }));
    expect(run).toHaveBeenCalledTimes(1);
  });
});

describe("deadlineLabel", () => {
  it("liczy dni w kalendarzu firmy i godzinę w Warszawie", () => {
    expect(deadlineLabel("2026-11-24", "2026-11-24T22:30:00Z", "2026-11-24")).toMatchObject({
      date: "24.11, 23:30",
      hint: "dziś",
      past: false,
    });
    expect(deadlineLabel("2026-11-25", null, "2026-11-24")).toMatchObject({ date: "25.11", hint: "jutro", urgent: true });
    expect(deadlineLabel("2026-11-23", null, "2026-11-24")).toMatchObject({ hint: "po terminie", past: true });
    expect(deadlineLabel(null, null, "2026-11-24")).toBeNull();
  });
});
