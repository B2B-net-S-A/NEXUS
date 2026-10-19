/**
 * „Opieka · Konsultanci” (M1): awaria to nie pusta lista, rytm z podpisem,
 * filtry z licznikami w zakresie, sygnał z podpowiedzią i „Zmień” tylko
 * przy prawie zmiany rytmu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

import { ConsultantsPanel } from "@/components/care/ConsultantsPanel";
import type { CadenceCurrent, CareConsultants, ConsultantRow } from "@/lib/api/care";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

const program: CadenceCurrent = {
  level: "biweekly",
  source: "program",
  starts_on: "2026-09-01",
  until_on: "2026-11-29",
  returns_to: "monthly",
  reason: null,
  note: null,
  author: null,
};

function row(overrides: Partial<ConsultantRow>): ConsultantRow {
  return {
    contract_id: 1,
    candidate_id: 1,
    candidate_name: "Ewa Przykładowa",
    client_id: 3,
    client_name: "Bank Przykładowy",
    job_title: "Analityczka danych",
    contract_type: "b2b",
    start_date: "2026-09-01",
    end_date: null,
    owner: { id: 7, name: "Natalia Opiekuńcza" },
    is_mine: true,
    manager: { id: 4, name: "Piotr Menedżerski", position: null, area: null },
    cadence: program,
    next_contact: {
      due_on: "2026-10-14",
      label: "Rozmowa według rytmu",
      overdue: true,
      plan_item_id: 5,
      kind: "cadence",
      overdue_days: 3,
    },
    last_conversation: {
      id: 1,
      occurred_on: "2026-10-01",
      satisfaction: 4,
      note_excerpt: "Dobrze, chce więcej Kafki.",
      signals: [],
    },
    signals: [{ kind: "overdue", days: 3 }],
    suggested_level: null,
    conversations: { this_month: 2, next_month: 2 },
    can_change_cadence: true,
    ...overrides,
  };
}

function payload(items: ConsultantRow[]): CareConsultants {
  return {
    today: "2026-10-17",
    months: {
      this: { from: "2026-10-01", to: "2026-10-31" },
      next: { from: "2026-11-01", to: "2026-11-30" },
    },
    items,
    total: items.length,
    feedback_visible: true,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsultantsPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("ConsultantsPanel", () => {
  it("awaria serwera to komunikat z ponowieniem, nie „nie opiekujesz się nikim”", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderPanel();
    expect(await screen.findByText("Nie udało się wczytać listy konsultantów.")).toBeInTheDocument();
    expect(screen.queryByText("Nie opiekujesz się żadnym konsultantem")).not.toBeInTheDocument();
  });

  it("pusty zakres „Moi” ma swój stan dopiero po wczytaniu", async () => {
    mocks.get.mockResolvedValue({ data: payload([row({ is_mine: false })]) });
    renderPanel();
    expect(await screen.findByText("Nie opiekujesz się żadnym konsultantem")).toBeInTheDocument();
  });

  it("pusty „Moi” prowadzi do wszystkich w zakresie, jak w „Ten tydzień”", async () => {
    // Testy produkcji 19.10.2026: admin bez podopiecznych widział pustkę,
    // a „Wszyscy w moim zakresie” miało 501 osób.
    mocks.get.mockResolvedValue({ data: payload([row({ is_mine: false })]) });
    renderPanel();
    await userEvent.click(
      await screen.findByRole("button", { name: "Pokaż wszystkich w moim zakresie" }),
    );
    expect(screen.queryByText("Nie opiekujesz się żadnym konsultantem")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Wszyscy w moim zakresie/ })).toBeChecked();
  });

  it("rytm z podpisem, zaległość przy rozmowie, sygnał z podpowiedzią i filtry z licznikami", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({
      data: payload([
        row({}),
        row({
          contract_id: 2,
          candidate_name: "Adam Wzorcowy",
          contract_type: "uzlecenie",
          start_date: "2023-02-01",
          cadence: { ...program, level: "monthly", source: "default", until_on: null, returns_to: null },
          next_contact: {
            due_on: "2026-10-29",
            label: "Rozmowa według rytmu",
            overdue: false,
            plan_item_id: 6,
            kind: "cadence",
            overdue_days: 0,
          },
          signals: [{ kind: "weak_feedback", average: 2.7, on: "2026-10-15" }],
          suggested_level: "biweekly",
          conversations: { this_month: 1, next_month: 1 },
          can_change_cadence: false,
        }),
        row({
          contract_id: 3,
          candidate_name: "Olga Zielona",
          is_mine: false,
          cadence: {
            ...program,
            level: "paused",
            source: "period",
            until_on: "2026-11-15",
            reason: "long_absence",
          },
          next_contact: null,
          signals: [],
        }),
      ]),
    });
    renderPanel();
    const table = await screen.findByRole("table", { name: "Konsultanci i rytm kontaktu" });
    const ewa = within(table).getByRole("row", { name: /Ewa Przykładowa/ });
    expect(within(ewa).getByText("co 2 tygodnie")).toBeInTheDocument();
    expect(within(ewa).getByText("pierwsze 90 dni")).toBeInTheDocument();
    expect(within(ewa).getByText("zaległa 3 dni")).toBeInTheDocument();
    expect(within(ewa).getByText(/Analityczka danych · B2B · od 01\.09/)).toBeInTheDocument();
    expect(within(ewa).getByRole("button", { name: "Zmień rytm: Ewa Przykładowa" })).toBeInTheDocument();
    const adam = within(table).getByRole("row", { name: /Adam Wzorcowy/ });
    expect(within(adam).getByText("opinia 2,7 / 5")).toBeInTheDocument();
    expect(within(adam).getByText("podnieść rytm?")).toBeInTheDocument();
    expect(within(adam).getByText(/Zlecenie · od 2023/)).toBeInTheDocument();
    expect(within(adam).queryByRole("button", { name: /Zmień rytm/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Olga Zielona")).not.toBeInTheDocument();
    expect(screen.getByText(/Rozmów w tym miesiącu według rytmów/)).toHaveTextContent("3");

    expect(screen.getByRole("radio", { name: "Moi (2)" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Rytm: co 2 tygodnie (1)" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Z sygnałem (2)" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
    await user.click(screen.getByRole("radio", { name: "Wszyscy w moim zakresie (3)" }));
    await user.click(screen.getByRole("radio", { name: "Wstrzymani (1)" }));
    const olga = await screen.findByRole("row", { name: /Olga Zielona/ });
    expect(within(olga).getByText("do 15.11 · długa nieobecność")).toBeInTheDocument();
    expect(within(olga).getByText("po 15.11")).toBeInTheDocument();
    expect(within(olga).getByText("Natalia Opiekuńcza")).toBeInTheDocument();
  });
});
