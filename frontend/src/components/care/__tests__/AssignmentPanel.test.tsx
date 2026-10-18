/**
 * „Opieka · Przydział” (M3): awaria to nie „każdy ma opiekuna”, obciążenie
 * z rytmów z ostrzeżeniem progu, zmiana wielu osób naraz z powodem tylko dla
 * head back office i admina (pozostali bez zaznaczania i bez progu).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), showToast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

// Pula opiekunów ma własne zapytanie i własny test (``OwnerPoolPanel.test.tsx``).
vi.mock("@/components/care/OwnerPoolPanel", () => ({
  OwnerPoolPanel: () => <section aria-label="Pula opiekunów" />,
}));

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { AssignmentPanel } from "@/components/care/AssignmentPanel";
import type { AssignmentRow, CareAssignment } from "@/lib/api/care";

const natalia = { id: 7, name: "Natalia Opiekuńcza" };
const kamil = { id: 8, name: "Kamil Testowy" };

function item(overrides: Partial<AssignmentRow>): AssignmentRow {
  return {
    contract_id: 1,
    candidate_id: 1,
    candidate_name: "Marek Nowoprzyjęty",
    job_title: "Python Developer",
    contract_type: "b2b",
    client_id: 3,
    client_name: "Klinika Testowa IT",
    start_date: "2026-11-03",
    end_date: null,
    owner: null,
    owner_source: null,
    explicit_owner_id: null,
    client_default_owner: null,
    hint: "no_default",
    ending_soon: false,
    cadence_level: "biweekly",
    conversations_next_month: 2,
    ...overrides,
  };
}

function overview(overrides: Partial<CareAssignment> = {}): CareAssignment {
  return {
    today: "2026-10-17",
    month: { from: "2026-11-01", to: "2026-11-30" },
    counts: { active: 3, without_owner: 2, owners: 2, conversations: 50, ending: 0 },
    threshold: { monthly_conversations: 40 },
    owners: [
      {
        id: natalia.id,
        name: natalia.name,
        is_delivery_lead: false,
        consultants: 38,
        conversations: 47,
        by_level: { biweekly: 9, monthly: 21, quarterly: 6, paused: 2 },
        clients: [],
        over_threshold: true,
      },
      {
        id: kamil.id,
        name: kamil.name,
        is_delivery_lead: true,
        consultants: 1,
        conversations: 3,
        by_level: { monthly: 1 },
        clients: ["Telekom Wzorcowy"],
        over_threshold: false,
      },
    ],
    items: [
      item({ contract_id: 1 }),
      item({ contract_id: 2, candidate_name: "Iga Próbna", contract_type: "uzlecenie" }),
      item({
        contract_id: 3,
        candidate_name: "Leon Wzorcowy",
        owner: natalia,
        owner_source: "contract",
        explicit_owner_id: natalia.id,
        hint: "contract",
      }),
    ],
    clients: [],
    owner_choices: [natalia, kamil],
    can_assign: true,
    can_edit_threshold: true,
    can_edit_defaults: true,
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AssignmentPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.put.mockReset();
});

describe("AssignmentPanel", () => {
  it("awaria serwera to komunikat, nie „każdy konsultant ma opiekuna”", async () => {
    mocks.get.mockRejectedValue(
      Object.assign(new Error("HTTP 500"), { response: { status: 500, data: {} } }),
    );
    renderPanel();
    expect(await screen.findByText("Nie udało się wczytać przydziału opiekunów.")).toBeInTheDocument();
    expect(screen.queryByText("Każdy konsultant ma opiekuna")).not.toBeInTheDocument();
  });

  it("obciążenie z rytmów i próg; zaznaczenie wielu osób przypisuje je z powodem", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockResolvedValue({ data: overview() });
    mocks.post.mockResolvedValue({ data: { changed: 2, unchanged: 0, owner: kamil } });
    renderPanel();
    const loads = await screen.findByRole("region", { name: "Opiekunowie i obciążenie" });
    expect(screen.getByRole("region", { name: "Pula opiekunów" })).toBeInTheDocument();
    const card = within(loads).getByRole("button", { name: /Natalia Opiekuńcza/ });
    expect(within(card).getByText("38 osób · 47 rozmów")).toBeInTheDocument();
    expect(within(card).getByText("powyżej progu 40 rozmów")).toBeInTheDocument();
    expect(within(card).getByText("9 co 2 tygodnie")).toBeInTheDocument();
    expect(within(loads).getByText(/klienci: Telekom Wzorcowy/)).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "Kontrakty do przydziału" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getAllByText("klient bez domyślnego opiekuna · ustaw go")).toHaveLength(2);
    expect(screen.queryByRole("group", { name: "Zmiana opiekuna zaznaczonych" })).toBeNull();

    await user.click(within(table).getByRole("checkbox", { name: "Zaznacz wszystkich" }));
    const bar = screen.getByRole("group", { name: "Zmiana opiekuna zaznaczonych" });
    expect(within(bar).getByText("Zaznaczone: 2")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Przypisz" })).toBeDisabled();
    await user.click(within(bar).getByRole("combobox", { name: "Przypisz do" }));
    await user.click(await screen.findByRole("option", { name: kamil.name }));
    await user.click(within(bar).getByRole("combobox", { name: "Powód zmiany opiekuna" }));
    await user.click(await screen.findByRole("option", { name: "Wyrównanie obciążenia" }));
    await user.click(within(bar).getByRole("button", { name: "Przypisz" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0]).toEqual([
      "/api/care/assignment",
      { contract_ids: [1, 2], owner_user_id: kamil.id, reason: "balance_load" },
    ]);

    await user.click(within(loads).getByRole("button", { name: /Natalia Opiekuńcza/ }));
    expect(within(screen.getByRole("table", { name: "Kontrakty do przydziału" })).getByText("Leon Wzorcowy")).toBeInTheDocument();
  });

  it("bez prawa przydziału: bez zaznaczania i bez progu", async () => {
    mocks.get.mockResolvedValue({
      data: overview({ can_assign: false, can_edit_threshold: false }),
    });
    renderPanel();
    const table = await screen.findByRole("table", { name: "Kontrakty do przydziału" });
    expect(within(table).queryByRole("checkbox")).toBeNull();
    expect(screen.queryByLabelText(/Próg obciążenia/)).toBeNull();
    expect(screen.getByText(/przypisuje head back office albo administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Pula opiekunów" })).toBeNull();
  });
});
