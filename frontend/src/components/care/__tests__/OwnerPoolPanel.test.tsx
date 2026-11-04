/**
 * Pula opiekunów i „Przypisz wg obłożenia” (decyzja Artura 18.10.2026):
 * awaria to komunikat, rozkład „teraz → po przydziale” tylko dla tych, których
 * automat bierze, osoba bez dostępu do Opieki z powodem, „Nie przypisuj”
 * zapisuje pulę (toast przeżywa przemontowanie edytora), zapis przydziału
 * po potwierdzeniu wysyła pary z podglądu.
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

if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { AutoAssignBar, OwnerPoolPanel } from "@/components/care/OwnerPoolPanel";
import { careKeys, type CareAutoAssignment } from "@/lib/api/care";

const hanna = { id: 3, name: "Hanna Finansowa" };
const igor = { id: 4, name: "Igor Testowy" };

function preview(overrides: Partial<CareAutoAssignment> = {}): CareAutoAssignment {
  return {
    pool: [
      { id: 1, name: "Beata Księgowa", excluded: true, sees_care: true, eligible: false, note: null, consultants_now: null, consultants_after: null },
      { id: 2, name: "Daria Przykładowa", excluded: false, sees_care: false, eligible: false, note: "nie widzi Opieki (brak sekcji albo podglądu Delivery)", consultants_now: null, consultants_after: null },
      { ...hanna, excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 2, consultants_after: 3 },
      { ...igor, excluded: false, sees_care: true, eligible: true, note: null, consultants_now: 0, consultants_after: 2 },
    ],
    config: {
      manager: { id: 9, name: "Szef Przykładowy" },
      manager_from_division: false,
      excluded_user_ids: [1],
      auto_new_contracts: true,
      saved: true,
    },
    manager_choices: [{ id: 9, name: "Szef Przykładowy" }],
    items: [
      { contract_id: 11, candidate_name: "Marek Nowoprzyjęty", client_name: "Klinika Testowa", start_date: "2026-10-01", owner: igor },
      { contract_id: 12, candidate_name: "Iga Próbna", client_name: "Klinika Testowa", start_date: "2026-10-02", owner: igor },
      { contract_id: 13, candidate_name: "Leon Wzorcowy", client_name: "Bank Przykładowy", start_date: "2026-10-03", owner: hanna },
    ],
    unassigned: [],
    counts: { targets: 3, assigned: 3, unassigned: 0, eligible: 2 },
    ...overrides,
  };
}

function renderPanel(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <OwnerPoolPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.put.mockReset();
  mocks.showToast.mockReset();
});

describe("OwnerPoolPanel", () => {
  it("awaria serwera to komunikat, nie pusta pula", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("HTTP 500"), { response: { status: 500, data: {} } }));
    renderPanel();
    expect(await screen.findByText("Nie udało się wczytać puli opiekunów.")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma kogo przypisać.")).toBeNull();
  });

  it("rozkład teraz → po przydziale tylko dla puli automatu; bez dostępu z powodem", async () => {
    mocks.get.mockResolvedValue({ data: preview() });
    renderPanel();
    const table = await screen.findByRole("table", { name: "Pula opiekunów" });
    const igorRow = within(table).getByText("Igor Testowy").closest("tr") as HTMLElement;
    expect(within(igorRow).getByText("0")).toBeInTheDocument();
    expect(within(igorRow).getByText("2")).toBeInTheDocument();
    const daria = within(table).getByText("Daria Przykładowa").closest("tr") as HTMLElement;
    expect(within(daria).getByText(/nie widzi Opieki/)).toBeInTheDocument();
    expect(within(daria).getAllByText("—")).toHaveLength(2);
    expect(screen.getByLabelText("Nie przypisuj konsultantów: Beata Księgowa")).toBeChecked();
    expect(screen.getByText("przypisujemy do 2 osoby")).toBeInTheDocument();
  });

  it("„Nie przypisuj” zapisuje pulę i pokazuje toast po przemontowaniu edytora", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockResolvedValue({ data: preview() });
    mocks.put.mockResolvedValue({
      data: preview({ config: { ...preview().config, excluded_user_ids: [1, 3] } }),
    });
    renderPanel();
    await user.click(await screen.findByLabelText("Nie przypisuj konsultantów: Hanna Finansowa"));
    // Niezapisana pula = stary podgląd — przydziału nie da się zapisać.
    expect(screen.getByRole("button", { name: "Przypisz wg obłożenia (3)" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Zapisz pulę" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/care/assignment/pool", {
        manager_user_id: 9,
        excluded_user_ids: [1, 3],
        auto_new_contracts: true,
      }),
    );
    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith("Pula opiekunów zapisana", "success"));
  });

  it("zapis puli odświeża listę wyboru opiekuna (wykluczony znika od razu)", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockResolvedValue({ data: preview() });
    mocks.put.mockResolvedValue({ data: preview() });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(careKeys.owners, [{ id: 1, name: "Hanna Finansowa" }]);
    renderPanel(client);
    await user.click(await screen.findByLabelText("Nie przypisuj konsultantów: Hanna Finansowa"));
    await user.click(screen.getByRole("button", { name: "Zapisz pulę" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    await waitFor(() => expect(client.getQueryState(careKeys.owners)?.isInvalidated).toBe(true));
  });

  it("niezapisana pula: podpowiedź i przydział zablokowany do zapisu", async () => {
    mocks.get.mockResolvedValue({
      data: preview({ config: { ...preview().config, auto_new_contracts: false, saved: false } }),
    });
    renderPanel();
    expect(await screen.findByText(/Pula nie jest jeszcze zapisana/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz pulę" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przypisz wg obłożenia (3)" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Nowy kontrakt od razu dostaje opiekuna/ })).toBeChecked();
  });

  it("zapis przydziału po potwierdzeniu wysyła pary z podglądu", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockResolvedValue({ data: preview() });
    mocks.post.mockResolvedValue({ data: { changed: 3, skipped: 0, notified: 0, by_owner: [] } });
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Przypisz wg obłożenia (3)" }));
    await user.click(await screen.findByRole("button", { name: "Zapisz przydział" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/care/assignment/auto", {
        items: [
          { contract_id: 11, owner_user_id: 4 },
          { contract_id: 12, owner_user_id: 4 },
          { contract_id: 13, owner_user_id: 3 },
        ],
      }),
    );
    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith("Przypisano: 3 osoby", "success"));
  });

  it("okno ustawień: pula bez przydziału (przydział jest na pasku ekranu)", async () => {
    mocks.get.mockResolvedValue({ data: preview() });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <OwnerPoolPanel withAutoPreview={false} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("table", { name: "Pula opiekunów" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Przypisz wg obłożenia/ })).toBeNull();
  });
});

describe("AutoAssignBar", () => {
  function renderBar() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <AutoAssignBar />
      </QueryClientProvider>,
    );
  }

  it("pasek: ilu bez opiekuna, u kogo i od kiedy; podgląd i zapis par z podglądu", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockResolvedValue({ data: preview() });
    mocks.post.mockResolvedValue({ data: { changed: 3, skipped: 0, notified: 0, by_owner: [] } });
    renderBar();
    expect(
      await screen.findByText("3 konsultantów bez opiekuna (Klinika Testowa, Bank Przykładowy, start 01.10)."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Podgląd" }));
    expect(screen.getByRole("table", { name: "Podgląd przydziału wg obłożenia" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Przypisz wg obłożenia (3)" }));
    await user.click(await screen.findByRole("button", { name: "Zapisz przydział" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/care/assignment/auto", expect.anything()));
  });

  it("nikogo do przypisania — paska nie ma", async () => {
    mocks.get.mockResolvedValue({ data: preview({ items: [] }) });
    const { container } = renderBar();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
