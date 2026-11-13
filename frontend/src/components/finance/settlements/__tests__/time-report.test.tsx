import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TimeReportMonth, TimeReportRow } from "@/lib/api/client-time-reports";

import { TimeReportView } from "../TimeReportView";
import { countT4tFilter, hoursText, matchesSearch, matchesT4tFilter, periodLabel } from "../time-report-format";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), success: vi.fn(), error: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }) }));

const PERIODS = [
  { start: "2026-09-01", end: "2026-09-06" },
  { start: "2026-09-25", end: "2026-09-30" },
];

function row(over: Partial<TimeReportRow>): TimeReportRow {
  return {
    key: "M000001",
    person_no: "M000001",
    name: "Jan Testowy",
    report_name: "Jan Testowy",
    contract_id: 1,
    contract_status: "active",
    mapping: "confirmed",
    projects: ["2020-000001"],
    status: "ok",
    previous_status: "ok",
    changed: false,
    approved: "64.00",
    submitted: "0.00",
    invoice_hours: "64.00",
    difference: "0.00",
    notes: [],
    weeks: [
      ["32.00", "0.00"],
      ["32.00", "0.00"],
    ],
    ...over,
  };
}

const ROWS = [
  row({}),
  row({
    key: "M000002",
    person_no: "M000002",
    name: "Anna Przykładowa",
    status: "differs",
    previous_status: "waiting",
    changed: true,
    invoice_hours: "72.00",
    difference: "8.00",
    notes: ["Faktura ma o 8 h więcej niż raport."],
  }),
  row({ key: "M000003", person_no: "M000003", name: "Ewa Próbna", status: "waiting", previous_status: "waiting", projects: ["2020-000002"] }),
];

const MONTH: TimeReportMonth = {
  client_id: 11,
  client_name: "Klient testowy",
  month: "2026-09",
  versions: [
    { id: 1, version_no: 1, received_on: "2026-10-01", file_name: "t4t.xlsx", sheet_name: null, rows_count: 100, people_count: 3, hours_approved: "150.00", hours_submitted: "40.00" },
    { id: 2, version_no: 2, received_on: "2026-10-05", file_name: "t4t.xlsx", sheet_name: null, rows_count: 110, people_count: 3, hours_approved: "190.00", hours_submitted: "0.00" },
  ],
  version_id: 2,
  previous_version_id: 1,
  periods: PERIODS,
  counts: { ok: 1, waiting: 1, no_approval: 0, differs: 1, no_invoice: 0, not_in_report: 0, unmatched: 0, changed: 1, all: 3 },
  rows: ROWS,
};

function renderView(data: TimeReportMonth, onVersion = vi.fn(), onOpen = vi.fn()) {
  mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TimeReportView clientId={11} month="2026-09" canWrite versionId={null} onVersion={onVersion} onOpen={onOpen} />
    </QueryClientProvider>,
  );
  return { onVersion, onOpen };
}

describe("Raport klienta T4T: filtry i formaty", () => {
  it("„Do zrobienia” to rozbieżności, brak akceptacji, faktury i kartoteki, bez „Czekamy”", () => {
    expect(matchesT4tFilter("todo", { status: "differs", changed: false })).toBe(true);
    expect(matchesT4tFilter("todo", { status: "unmatched", changed: false })).toBe(true);
    expect(matchesT4tFilter("todo", { status: "waiting", changed: true })).toBe(false);
    expect(matchesT4tFilter("changed", { status: "ok", changed: true })).toBe(true);
    expect(countT4tFilter("todo", ROWS)).toBe(1);
  });

  it("szuka po numerze osoby i NIDS", () => {
    expect(matchesSearch(ROWS[2], "m000003")).toBe(true);
    expect(matchesSearch(ROWS[2], "2020-000002")).toBe(true);
    expect(matchesSearch(ROWS[2], "anna")).toBe(false);
  });

  it("godziny i przedziały po polsku", () => {
    expect(hoursText("7.50")).toBe("7,5 h");
    expect(hoursText(null)).toBe("–");
    expect(periodLabel({ start: "2026-09-25", end: "2026-09-30" })).toBe("25–30.09");
    expect(periodLabel({ start: "2026-09-28", end: "2026-10-04" })).toBe("28.09–4.10");
  });
});

describe("Raport klienta T4T: panel miesiąca", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
  });

  it("pokazuje wersję, liczniki i domyślnie listę do zrobienia", async () => {
    renderView(MONTH);
    expect(await screen.findByText("Raport Time for Teams: wersja 2 z 05.10.2026")).toBeInTheDocument();
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getByText("Anna Przykładowa")).toBeInTheDocument();
    expect(within(table).queryByText("Jan Testowy")).not.toBeInTheDocument();
    expect(within(table).getByText("Czekamy → Rozbieżność")).toBeInTheDocument();
  });

  it("filtr zmian od poprzedniej wersji i otwarcie karty osoby", async () => {
    const { onOpen } = renderView(MONTH);
    await screen.findByText("Raport Time for Teams: wersja 2 z 05.10.2026");
    fireEvent.click(screen.getByRole("button", { name: /Zmiany od poprzedniej wersji/ }));
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    fireEvent.click(within(table).getByRole("button", { name: "Anna Przykładowa" }));
    expect(onOpen).toHaveBeenCalledWith("M000002");
  });

  it("wybór starszej wersji przekazuje jej id, najnowsza = null", async () => {
    const { onVersion } = renderView(MONTH);
    await screen.findByText("Raport Time for Teams: wersja 2 z 05.10.2026");
    fireEvent.click(screen.getByRole("button", { name: "v1 · 01.10" }));
    expect(onVersion).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "v2 · 05.10" }));
    expect(onVersion).toHaveBeenLastCalledWith(null);
  });

  it("bez raportu w miesiącu mówi, co zrobić", async () => {
    renderView({ ...MONTH, versions: [], version_id: null, previous_version_id: null, rows: [], counts: { ...MONTH.counts, all: 0 } });
    expect(await screen.findByText(/nie ma jeszcze raportu od klienta/)).toBeInTheDocument();
  });

  it("plik z kilkoma arkuszami raportu prosi o wybór arkusza i wysyła go drugi raz", async () => {
    renderView(MONTH);
    await screen.findByText("Raport Time for Teams: wersja 2 z 05.10.2026");
    mocks.post.mockResolvedValueOnce({
      data: {
        needs_sheet: true,
        sheets: [
          { name: "Sheet1", rows: 10, people: 3, month: "2026-09" },
          { name: "Sheet1 (2)", rows: 12, people: 3, month: "2026-09" },
        ],
      },
    });
    const input = screen.getByLabelText("Plik z Time for Teams (XLSX)") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "t4t.xlsx")] } });
    fireEvent.click(screen.getByRole("button", { name: /Wgraj nową wersję/ }));
    const select = await screen.findByLabelText(/Arkusz raportu/);
    expect((select as HTMLSelectElement).value).toBe("Sheet1 (2)");
    mocks.post.mockResolvedValueOnce({
      data: { duplicate: false, version: { ...MONTH.versions[1], id: 3, version_no: 3 }, suggested: 0 },
    });
    fireEvent.click(screen.getByRole("button", { name: /Wgraj nową wersję/ }));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Wgrano wersję 3: 3 osób."));
    const form = mocks.post.mock.calls[1][1] as FormData;
    expect(form.get("sheet")).toBe("Sheet1 (2)");
  });
});
