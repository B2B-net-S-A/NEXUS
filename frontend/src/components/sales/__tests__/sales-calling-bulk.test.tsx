/**
 * Tabela Dzwonienia: akcje zbiorcze (decyzja Artura 27.11.2026, wariant A) — zaznaczanie,
 * „Zaznacz wszystkie z filtra”, liczby przed zapisem, usunięcie z „Cofnij”. Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkInput, QueueItem } from "@/lib/api/sales-calling";

const records = vi.fn();
const bulk = vi.fn();
const recordIds = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const showInfo = vi.fn();
const showActionToast = vi.fn();

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({
  mutate,
  mutateAsync: mutate,
  isPending: false,
  reset: vi.fn(),
});

vi.mock("@/lib/api/sales-calling", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-calling")>()),
  useCallRecords: (filters: unknown) => records(filters),
  useChangeState: () => mutation(vi.fn()),
  useBulkRecords: () => mutation(bulk),
  fetchRecordIds: (filters: unknown) => recordIds(filters),
  useCallCampaigns: () => ({
    data: [
      { id: 3, name: "Kampania Testowa", service: null, script: null, total: 0, counts: {} },
      { id: 4, name: "Druga Kampania", service: null, script: null, total: 0, counts: {} },
    ],
  }),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useOwnerCandidates: () => ({ data: [{ id: 9, name: "Druga Osoba" }] }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess, showInfo, showActionToast }),
}));
vi.mock("../calling/CallCard", () => ({ CallCard: () => null }));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    id,
    ariaLabel,
    value,
    onValueChange,
    options,
    anyLabel,
  }: {
    id?: string;
    ariaLabel?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: { value: string; label: string }[];
    anyLabel?: string;
  }) => (
    <select id={id} aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {anyLabel !== undefined && <option value="">{anyLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { CallTableView } from "../calling/CallTableView";

function item(id: number, overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    key: `r:${id}`,
    section: "callbacks",
    record_id: id,
    opportunity_id: null,
    opportunity_title: null,
    company: { id: 100 + id, name: `Firma ${id}` },
    campaign: { id: 3, name: "Kampania Testowa" },
    person_name: "Jan Testowy",
    person_title: null,
    phone: "600100200",
    state: "new",
    due_on: null,
    attempts: 0,
    last_outcome_at: null,
    since: "2026-11-20T10:00:00Z",
    ...overrides,
  };
}

const ok = <T,>(data: T) => ({ data, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() });

const opportunityRow = item(3, {
  key: "o:30",
  campaign: null,
  opportunity_id: 30,
  company: { id: 130, name: "Szansa S.A." },
});

function renderTable(canEdit = true) {
  return render(<CallTableView today="2026-11-28" campaignId={null} canEdit={canEdit} meetingStage={null} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  records.mockReturnValue(ok({ items: [item(1), item(2), opportunityRow], total: 239, counts: { new: 239 } }));
  bulk.mockImplementation(async (input: BulkInput) => ({
    done: input.record_ids.slice(0, 1),
    skipped: input.record_ids.length > 1 ? { already_in_campaign: input.record_ids.length - 1 } : {},
  }));
});

describe("akcje zbiorcze w Tabeli", () => {
  it("zaznacza rekordy kampanii, a pozycja szansy nie ma pola wyboru", () => {
    renderTable();
    expect(screen.queryByRole("region", { name: "Akcje zbiorcze" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Zaznacz: Szansa S.A." })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz rekordy na tej stronie" }));
    const bar = screen.getByRole("region", { name: "Akcje zbiorcze" });
    expect(within(bar).getByText("Zaznaczone: 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Firma 1" }));
    expect(within(bar).getByText("Zaznaczone: 1")).toBeInTheDocument();
  });

  it("„Zaznacz wszystkie z filtra” bierze id z serwera z filtrami Tabeli", async () => {
    recordIds.mockResolvedValue({ ids: Array.from({ length: 239 }, (_, i) => i + 1), truncated: false });
    renderTable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Firma 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Zaznacz wszystkie 239 z filtra" }));
    await waitFor(() => expect(screen.getByText("Zaznaczone: 239")).toBeInTheDocument());
    expect(recordIds).toHaveBeenCalledWith(expect.objectContaining({ state: null, scope: "mine", search: "" }));
  });

  it("przeniesienie najpierw liczy, potem zapisuje wybraną kampanię", async () => {
    renderTable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz rekordy na tej stronie" }));
    fireEvent.click(screen.getByRole("button", { name: "Przenieś do kampanii" }));
    const save = screen.getByRole("button", { name: /^Przenieś \d+$/ });
    expect(save).toBeDisabled();
    expect(bulk).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Kampania"), { target: { value: "4" } });
    await waitFor(() => expect(screen.getByText("Przejdzie do kampanii: 1.")).toBeInTheDocument());
    expect(screen.getByText("Bez zmian: 1 — firma jest już w tej kampanii.")).toBeInTheDocument();
    expect(bulk).toHaveBeenLastCalledWith({ action: "move", record_ids: [1, 2], campaign_id: 4, dry_run: true });
    fireEvent.click(screen.getByRole("button", { name: "Przenieś 1" }));
    await waitFor(() =>
      expect(bulk).toHaveBeenLastCalledWith({ action: "move", record_ids: [1, 2], campaign_id: 4, dry_run: false }),
    );
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Przeniesiono: 1."));
    expect(screen.queryByRole("region", { name: "Akcje zbiorcze" })).not.toBeInTheDocument();
  });

  it("przypisanie wybiera osobę z „Sprzedaż: edycja”", async () => {
    renderTable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Firma 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Przypisz osobie" }));
    fireEvent.change(screen.getByLabelText("Osoba"), { target: { value: "9" } });
    await waitFor(() => expect(screen.getByText("Dostanie je ta osoba: 1.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Przypisz 1" }));
    await waitFor(() =>
      expect(bulk).toHaveBeenLastCalledWith({ action: "assign", record_ids: [2], assignee_user_id: 9, dry_run: false }),
    );
  });

  it("usunięcie z listy pokazuje liczby, a dymek ma „Cofnij”, które przywraca te same rekordy", async () => {
    bulk.mockImplementation(async (input: BulkInput) => ({ done: input.record_ids, skipped: {} }));
    renderTable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz rekordy na tej stronie" }));
    fireEvent.click(screen.getByRole("button", { name: "Usuń z listy" }));
    await waitFor(() => expect(screen.getByText("Zniknie z listy: 2.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Usuń 2 z listy" }));
    await waitFor(() => expect(showActionToast).toHaveBeenCalled());
    const [message, options] = showActionToast.mock.calls[0];
    expect(message).toBe("Usunięto z listy: 2.");
    expect(options.actionLabel).toBe("Cofnij");
    await options.onAction();
    expect(bulk).toHaveBeenLastCalledWith({ action: "restore", record_ids: [1, 2] });
    expect(showSuccess).toHaveBeenCalledWith("Przywrócono na listę: 2.");
  });

  it("błąd liczenia nie wygląda jak zero rekordów", async () => {
    bulk.mockRejectedValue({ response: { status: 500 } });
    renderTable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Firma 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Usuń z listy" }));
    await waitFor(() => expect(screen.getByText(/Nie udało się policzyć rekordów/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Usuń \d+ z listy$/ })).toBeDisabled();
  });

  it("bez „Sprzedaż: edycja” nie ma pól wyboru ani paska", () => {
    renderTable(false);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Akcje zbiorcze" })).not.toBeInTheDocument();
  });
});
