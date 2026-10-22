/**
 * „Opieka · Konsultanci” (M1, przebudowa 22.10.2026): awaria to nie pusta
 * lista, rytm z podpisem, kolumna „Zdrowie” zamiast „Sygnał”, filtry stanu
 * z licznikami w zakresie, „Zmień” tylko przy prawie zmiany rytmu,
 * zaznaczanie — komunikat do zaznaczonych i opiekun hurtem.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

import { ConsultantsPanel, matchesConsultantsFilter } from "@/components/care/ConsultantsPanel";
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

interface PanelOptions {
  scope?: "mine" | "all";
  canAnnounce?: boolean;
  canAssign?: boolean;
  onOpenAnnouncement?: (id: number) => void;
  onOpenContract?: (id: number) => void;
}

function Harness({ scope: initial = "mine", ...options }: PanelOptions) {
  const [scope, setScope] = React.useState<"mine" | "all">(initial);
  return (
    <ConsultantsPanel
      scope={scope}
      onScopeChange={setScope}
      onOpenContract={options.onOpenContract ?? vi.fn()}
      onOpenAnnouncement={options.onOpenAnnouncement ?? vi.fn()}
      canAnnounce={options.canAnnounce ?? false}
      canAssign={options.canAssign ?? false}
    />
  );
}

function renderPanel(options: PanelOptions = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...options} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  window.history.replaceState(null, "", "/care?tab=consultants");
});

describe("ConsultantsPanel", () => {
  it("awaria serwera to komunikat z ponowieniem, nie „nie opiekujesz się nikim”", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderPanel();
    expect(await screen.findByText("Nie udało się wczytać listy konsultantów.")).toBeInTheDocument();
    expect(screen.queryByText("Nie opiekujesz się żadnym konsultantem")).not.toBeInTheDocument();
  });

  it("pusty „Moi” prowadzi do wszystkich w zakresie (zakres z nagłówka /care)", async () => {
    // Testy produkcji 19.10.2026: admin bez podopiecznych widział pustkę,
    // a „Wszyscy w moim zakresie” miało 501 osób.
    mocks.get.mockResolvedValue({ data: payload([row({ is_mine: false })]) });
    renderPanel();
    expect(await screen.findByText("Nie opiekujesz się żadnym konsultantem")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pokaż wszystkich w moim zakresie" }));
    expect(screen.queryByText("Nie opiekujesz się żadnym konsultantem")).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Ewa Przykładowa/ })).toBeInTheDocument();
  });

  it("rytm z podpisem, zaległość przy rozmowie, sygnał bez etykiety zdrowia i filtry z licznikami", async () => {
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
    const { unmount } = renderPanel();
    const table = await screen.findByRole("table", { name: "Konsultanci i rytm kontaktu" });
    expect(within(table).getByRole("columnheader", { name: "Zdrowie" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Sygnał" })).toBeNull();
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

    expect(screen.getByRole("button", { name: "Rytm: co 2 tygodnie 1" })).toBeInTheDocument();
    // Bez etykiety zdrowia (spoza D11) „Z sygnałem” liczy dawne sygnały rytmu.
    await user.click(screen.getByRole("button", { name: "Z sygnałem 2" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
    unmount();

    renderPanel({ scope: "all" });
    await user.click(await screen.findByRole("button", { name: "Wstrzymani 1" }));
    const olga = await screen.findByRole("row", { name: /Olga Zielona/ });
    expect(within(olga).getByText("do 15.11 · długa nieobecność")).toBeInTheDocument();
    expect(within(olga).getByText("po 15.11")).toBeInTheDocument();
    expect(within(olga).getByText("Natalia Opiekuńcza")).toBeInTheDocument();
  });

  it("„Zdrowie” z etykietą i „dlaczego”; „Z sygnałem” = Uwaga i Ryzyko; „Do przepięcia” z listy", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({
      data: payload([
        row({ health: { level: "risk", label: "Ryzyko", reasons: ["chce zmiany projektu (01.10)"] }, redeploy_active: true }),
        row({
          contract_id: 2,
          candidate_name: "Adam Wzorcowy",
          signals: [{ kind: "order_end", days: 70, on: "2026-12-30" }],
          health: { level: "ok", label: "Dobrze", reasons: [] },
        }),
      ]),
    });
    renderPanel();
    const ewa = await screen.findByRole("row", { name: /Ewa Przykładowa/ });
    expect(within(ewa).getByText("Ryzyko")).toBeInTheDocument();
    expect(within(ewa).getByText("chce zmiany projektu (01.10)")).toBeInTheDocument();
    const adam = screen.getByRole("row", { name: /Adam Wzorcowy/ });
    expect(within(adam).getByText("Dobrze")).toBeInTheDocument();
    // Sygnał rytmu przy etykiecie zdrowia już się nie powtarza.
    expect(within(adam).queryByText(/koniec zamówienia/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Z sygnałem 1" }));
    expect(screen.queryByRole("row", { name: /Adam Wzorcowy/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Do przepięcia 1" }));
    expect(screen.getByRole("row", { name: /Ewa Przykładowa/ })).toBeInTheDocument();
  });

  it("klik w osobę otwiera kartę konsultanta", async () => {
    const onOpenContract = vi.fn();
    mocks.get.mockResolvedValue({ data: payload([row({})]) });
    renderPanel({ onOpenContract });
    await userEvent.click(await screen.findByRole("button", { name: "Karta konsultanta: Ewa Przykładowa" }));
    expect(onOpenContract).toHaveBeenCalledWith(1);
  });

  it("zaznaczeni → szkic komunikatu z grupą „wybrane osoby”; opiekun hurtem tylko z prawem przydziału", async () => {
    const user = userEvent.setup();
    const onOpenAnnouncement = vi.fn();
    mocks.get.mockResolvedValue({
      data: payload([row({}), row({ contract_id: 2, candidate_id: 22, candidate_name: "Adam Wzorcowy" })]),
    });
    mocks.post.mockResolvedValue({ data: { id: 77 } });
    renderPanel({ canAnnounce: true, onOpenAnnouncement });
    await user.click(await screen.findByRole("checkbox", { name: "Zaznacz: Ewa Przykładowa" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Adam Wzorcowy" }));
    expect(screen.getByText("Zaznaczone: 2")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Nowy opiekun zaznaczonych" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Napisz komunikat do zaznaczonych" }));
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/care/announcements",
      expect.objectContaining({ audience: { group: "selected", candidate_ids: [1, 22] } }),
    );
    expect(onOpenAnnouncement).toHaveBeenCalledWith(77);
  });

  it("bez prawa do komunikatów i przydziału nie ma zaznaczania", async () => {
    mocks.get.mockResolvedValue({ data: payload([row({})]) });
    renderPanel();
    await screen.findByRole("row", { name: /Ewa Przykładowa/ });
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("„Konsultanci” z „Zespołu opiekunów” (`?owner=`): cały zakres, tylko ten opiekun, chip zdejmuje filtr", async () => {
    window.history.replaceState(null, "", "/care?tab=consultants&owner=8");
    mocks.get.mockResolvedValue({
      data: payload([
        row({}),
        row({
          contract_id: 2,
          candidate_id: 22,
          candidate_name: "Adam Wzorcowy",
          owner: { id: 8, name: "Kamil Testowy" },
          is_mine: false,
        }),
      ]),
    });
    renderPanel();
    expect(await screen.findByRole("row", { name: /Adam Wzorcowy/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Ewa Przykładowa/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Usuń filtr opiekuna: Kamil Testowy" }));
    expect(screen.getByRole("row", { name: /Ewa Przykładowa/ })).toBeInTheDocument();
    expect(window.location.search).toBe("?tab=consultants");
  });

  it("`?owner=none` pokazuje konsultantów bez opiekuna", async () => {
    window.history.replaceState(null, "", "/care?tab=consultants&owner=none");
    mocks.get.mockResolvedValue({
      data: payload([row({}), row({ contract_id: 3, candidate_name: "Iga Próbna", owner: null, is_mine: false })]),
    });
    renderPanel();
    expect(await screen.findByRole("row", { name: /Iga Próbna/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Ewa Przykładowa/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Usuń filtr opiekuna: bez opiekuna" })).toBeInTheDocument();
  });

  it("„Kończą w 60 dni” — koniec od dziś do 59 dni naprzód, bez przeszłych i bezterminowych", () => {
    const today = "2026-10-22";
    const ending = (end_date: string | null) => matchesConsultantsFilter(row({ end_date }), "ending", today);
    expect(ending("2026-10-22")).toBe(true);
    expect(ending("2026-12-20")).toBe(true);
    expect(ending("2026-12-21")).toBe(false);
    expect(ending("2026-10-21")).toBe(false);
    expect(ending(null)).toBe(false);
  });
});
