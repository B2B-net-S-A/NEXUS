import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  PlacementExclusionsTab,
  groupPlacementExclusions,
  type PlacementExclusionItem,
} from "./PlacementExclusionsTab";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: { get: mocks.get } }));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PlacementExclusionsTab />
    </QueryClientProvider>,
  );
}

describe("PlacementExclusionsTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje kandydata, rekrutację, kto ustawił i powód", async () => {
    mocks.get.mockResolvedValue({
      data: {
        total: 1,
        series_threshold: 10,
        reasons: {},
        items: [
          {
            id: 1,
            candidate_id: 5,
            candidate_name: "Anna Przykładowa",
            job_id: 9,
            job_title: "Java Developer",
            client_id: 3,
            client_name: "Firma Testowa",
            hired_at: "2025-09-24T08:00:00Z",
            moved_by_user_id: 2,
            moved_by_name: "Konto Testowe",
            reason: "admin_bulk_no_cv",
            reason_label: "Seria bez CV",
            had_cv_sent: false,
            series_day: "2025-09-24",
            series_size: 22,
            rule_version: 1,
            detected_at: "2026-09-22T10:00:00Z",
          },
        ],
      },
    });
    renderTab();

    expect(await screen.findByText("Anna Przykładowa")).toBeTruthy();
    expect(screen.getByText("Java Developer")).toBeTruthy();
    expect(screen.getByText("Firma Testowa")).toBeTruthy();
    expect(screen.getByText("Konto Testowe")).toBeTruthy();
    expect(screen.getByText("Seria bez CV")).toBeTruthy();
    expect(screen.getByText("22 pary w dniu")).toBeTruthy();
    expect(screen.getByText("1 wykluczony placement")).toBeTruthy();
  });

  it("403 to „brak uprawnień”, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(
      new AxiosError("forbidden", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 403,
        statusText: "Forbidden",
        data: {},
        headers: {},
        config: { headers: new AxiosHeaders() },
      }),
    );
    renderTab();

    expect(await screen.findByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText("Żaden placement nie jest wykluczony.")).toBeNull();
  });

  it("dzieli wiersze na grupy powodów, zwinięte, z licznikiem — klik rozwija", async () => {
    mocks.get.mockResolvedValue({ data: { total: 3, series_threshold: 10, reasons: {}, items: ITEMS } });
    renderTab();

    const series = await screen.findByRole("button", { name: /Seria jednego konta/ });
    expect(series).toHaveAttribute("aria-expanded", "false");
    expect(series).toHaveTextContent("2");
    expect(series).toHaveTextContent("1 konto");
    expect(screen.queryByText("Ola Fikcyjna")).toBeNull();

    fireEvent.click(series);
    expect(series).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Ola Fikcyjna")).toBeTruthy();
    expect(screen.queryByText("Jan Fikcyjny")).toBeNull();
  });

  it("wyszukiwarka rozwija grupy i zostawia tylko pasujące wiersze", async () => {
    mocks.get.mockResolvedValue({ data: { total: 3, series_threshold: 10, reasons: {}, items: ITEMS } });
    renderTab();

    fireEvent.change(await screen.findByRole("searchbox", { name: "Szukaj osoby lub rekrutacji" }), {
      target: { value: "jan" },
    });
    expect(screen.getByText("Jan Fikcyjny")).toBeTruthy();
    expect(screen.queryByText("Ola Fikcyjna")).toBeNull();
    expect(screen.queryByRole("button", { name: /Seria jednego konta/ })).toBeNull();
    const group = screen.getByRole("region", { name: /Masowe ustawienie/ });
    expect(within(group).getByRole("button")).toHaveTextContent("1 z 1");

    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj osoby lub rekrutacji" }), {
      target: { value: "nikt taki" },
    });
    expect(screen.getByText(/Nic nie pasuje/)).toBeTruthy();
  });
});

const row = (over: Partial<PlacementExclusionItem>): PlacementExclusionItem => ({
  id: 1,
  candidate_id: 1,
  candidate_name: "Ola Fikcyjna",
  job_id: 10,
  job_title: "Tester",
  client_id: null,
  client_name: null,
  hired_at: "2026-03-02T09:00:00Z",
  moved_by_user_id: 2,
  moved_by_name: "Konto A",
  reason: "admin_bulk_no_cv",
  reason_label: "Seria jednego konta",
  had_cv_sent: false,
  series_day: "2026-03-02",
  series_size: 12,
  rule_version: 1,
  detected_at: "2026-09-22T10:00:00Z",
  ...over,
});

const ITEMS: PlacementExclusionItem[] = [
  row({ id: 1 }),
  row({ id: 2, candidate_id: 2, candidate_name: "Ewa Fikcyjna", job_id: 11 }),
  row({
    id: 3,
    candidate_id: 3,
    candidate_name: "Jan Fikcyjny",
    job_id: 12,
    reason: "admin_bulk_2025_09_series",
    reason_label: "Masowe ustawienie „Zatrudniony” 24–25.09.2025",
    moved_by_user_id: 3,
    series_day: "2025-09-24",
  }),
];

describe("groupPlacementExclusions", () => {
  it("grupuje po powodzie i etapie „CV wysłane”, największa grupa pierwsza", () => {
    const groups = groupPlacementExclusions([
      ...ITEMS,
      row({ id: 4, reason: "admin_bulk_2025_09_series", reason_label: "Masowa", had_cv_sent: true }),
    ]);
    expect(groups.map((g) => [g.label, g.items.length])).toEqual([
      ["Seria jednego konta", 2],
      ["Masowe ustawienie „Zatrudniony” 24–25.09.2025", 1],
      ["Masowa", 1],
    ]);
    expect(groups[0]).toMatchObject({ accounts: 1, days: 1, detail: "Bez etapu „CV wysłane”" });
    expect(groups[2].detail).toBe("Para miała etap „CV wysłane”");
  });
});
