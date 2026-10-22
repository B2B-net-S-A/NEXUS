/**
 * Kartoteka → „Nieobecności i godziny” (22.10.2026): nieobecności roku i raporty
 * godzin z `GET /api/hr/people/{id}/history`. Awaria to zdanie z „Spróbuj
 * ponownie”, nigdy pusta lista; „Brak nieobecności w <rok>.” tylko po sukcesie.
 * Część modułu zamkniętego (`null`) nie ma listy ani karty. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonHistory } from "@/lib/api/hr-person-history";

const mocks = vi.hoisted(() => ({
  responses: [] as Array<() => unknown>,
  calls: [] as string[],
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: async (url: string, config?: { params?: Record<string, unknown> }) => {
      mocks.calls.push(`${url}?year=${config?.params?.year}`);
      const next = mocks.responses.shift();
      if (!next) throw Object.assign(new Error(url), { response: { status: 500 } });
      return { data: next() };
    },
  },
}));

import { olaFull } from "@/app/preview/hr-person/fixtures";

import { PersonAbsencesHours } from "../PersonAbsencesHours";

function history(partial: Partial<PersonHistory> = {}): PersonHistory {
  return {
    year: 2026,
    today: "2026-10-22",
    absences: {
      type_visible: true,
      items: [
        {
          id: "a",
          start_date: "2026-12-21",
          end_date: "2026-12-23",
          half_day: null,
          days_total: "3.0",
          status: "approved",
          state: "planned",
          leave_type: "vacation",
          label: "Przerwa w świadczeniu usług",
        },
        {
          id: "b",
          start_date: "2026-11-12",
          end_date: "2026-11-12",
          half_day: null,
          days_total: "1.0",
          status: "pending",
          state: "waiting",
          leave_type: "vacation",
          label: "Przerwa w świadczeniu usług",
        },
      ],
    },
    timesheets: {
      timesheet_required: true,
      items: [
        {
          year: 2026,
          month: 10,
          timesheet_id: 5,
          status: "draft",
          hours: 64,
          norm_hours: 184,
          has_pdf: false,
        },
        {
          year: 2026,
          month: 9,
          timesheet_id: 4,
          status: "approved",
          hours: 168,
          norm_hours: 176,
          has_pdf: true,
        },
        {
          year: 2026,
          month: 8,
          timesheet_id: null,
          status: null,
          hours: 0,
          norm_hours: 168,
          has_pdf: false,
        },
      ],
    },
    ...partial,
  };
}

function renderCards({ canEditPool = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onEditPool = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <PersonAbsencesHours
        person={{ ...olaFull("b2b"), leave_balance: null, entitlements: [] }}
        year={2026}
        canEditPool={canEditPool}
        onEditPool={onEditPool}
      />
    </QueryClientProvider>,
  );
  return { onEditPool };
}

describe("PersonAbsencesHours", () => {
  beforeEach(() => {
    mocks.responses = [];
    mocks.calls = [];
  });

  it("lista nieobecności roku ze stanem i raporty godzin wobec normy", async () => {
    mocks.responses.push(() => history());
    renderCards();

    const list = await screen.findByRole("list", { name: "Nieobecności 2026" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("21–23.12.2026");
    expect(rows[0]).toHaveTextContent("Przerwa w świadczeniu usług · 3 dni");
    expect(within(rows[0]).getByText("zaplanowana")).toBeInTheDocument();
    expect(within(rows[1]).getByText("czeka")).toBeInTheDocument();

    const reports = screen.getByRole("list", { name: "Raport godzin" });
    const months = within(reports).getAllByRole("listitem");
    expect(months[0]).toHaveTextContent("64 / 184 h");
    expect(months[0]).toHaveTextContent("szkic");
    expect(within(months[1]).getByRole("button", { name: "PDF" })).toBeInTheDocument();
    expect(months[2]).toHaveTextContent("nie założony");
    expect(within(months[0]).queryByRole("button", { name: "PDF" })).toBeNull();
    expect(mocks.calls).toEqual(["/api/hr/people/101/history?year=2026"]);
  });

  it("pusty rok: „Brak nieobecności w 2026.” po sukcesie", async () => {
    mocks.responses.push(() => history({ absences: { type_visible: false, items: [] } }));
    renderCards();
    expect(await screen.findByText("Brak nieobecności w 2026.")).toBeInTheDocument();
  });

  it("awaria: zdanie z „Spróbuj ponownie”, nie pusta lista; ponowienie wczytuje dane", async () => {
    const user = userEvent.setup();
    renderCards();
    expect(await screen.findByText("Nie udało się wczytać nieobecności i raportów godzin.")).toBeInTheDocument();
    expect(screen.queryByText(/Brak nieobecności/)).toBeNull();
    expect(screen.queryByRole("list", { name: "Raport godzin" })).toBeNull();

    mocks.responses.push(() => history());
    await user.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByRole("list", { name: "Nieobecności 2026" })).toBeInTheDocument();
  });

  it("moduły zamknięte dla patrzącego: sama linia puli, bez listy i bez raportów", async () => {
    mocks.responses.push(() => history({ absences: null, timesheets: null }));
    const { onEditPool } = renderCards({ canEditPool: true });
    await screen.findByText("Pula na 2026 nie jest ustawiona.");
    // Odpowiedź przyszła — nie ma ani listy, ani „Brak nieobecności”.
    await vi.waitFor(() => expect(screen.queryByText(/Wczytywanie/)).toBeNull());
    expect(screen.queryByText(/Brak nieobecności/)).toBeNull();
    expect(screen.queryByTestId("person-timesheets")).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Zmień pulę" }));
    expect(onEditPool).toHaveBeenCalled();
  });
});
