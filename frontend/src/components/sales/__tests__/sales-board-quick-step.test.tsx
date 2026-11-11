/**
 * Tablica szans: krok prosto z kafelka (decyzja Artura 11.11.2026, „mniej kliknięć”).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity, Pipeline, Stage } from "@/lib/api/sales";

const createActivity = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCreateActivity: () => ({ mutate: createActivity, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../useBoardMove", () => ({
  useBoardMove: () => ({ stageOf: (item: Opportunity) => item.stage.id, moveToStage: vi.fn() }),
}));

import { OpportunityBoard } from "../OpportunityBoard";

const LEAD = { id: 1, key: "lead", name: "Lead", position: 1, probability: 0, outcome: "open", qualifies: false, color: null } as Stage;
const PIPELINE = { id: 1, key: "sales", name: "Sprzedaż", is_default: true, stages: [LEAD] } as unknown as Pipeline;

const item = (overrides: Partial<Opportunity> = {}): Opportunity =>
  ({
    id: 41,
    title: "Zespół QA",
    status: "open",
    company: { id: 3, name: "Firma Testowa Sp. z o.o." },
    stage: LEAD,
    owner: { id: 1, name: "Handlowiec" },
    value: null,
    mrr_value: null,
    one_off_value: null,
    currency: "PLN",
    next_step: null,
    overdue_step: null,
    step_alarm: true,
    last_contact: null,
    waiting_for_reply: false,
    archived_at: null,
    ...overrides,
  }) as unknown as Opportunity;

const board = (items: Opportunity[], canEdit = true) =>
  render(
    <OpportunityBoard pipeline={PIPELINE} stages={[LEAD]} items={items} canEdit={canEdit} showOwner={false} refetch={vi.fn()} />,
  );

beforeEach(() => {
  vi.clearAllMocks();
});

describe("„+ krok” na kafelku", () => {
  it("„Jutro” zapisuje „Zadzwonić” przy tej szansie bez wchodzenia w kartę", () => {
    createActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    board([item()]);
    fireEvent.click(screen.getByRole("button", { name: "+ krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    const step = createActivity.mock.calls[0][0];
    expect(step).toMatchObject({ kind: "task", subject: "Zadzwonić", opportunity_id: 41, company_id: null });
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    expect(new Date(step.due_at).toDateString()).toBe(tomorrow.toDateString());
    expect(showSuccess).toHaveBeenCalled();
  });

  it("błąd zapisu wraca jako komunikat", () => {
    createActivity.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    board([item()]);
    fireEvent.click(screen.getByRole("button", { name: "+ krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Za tydzień" }));
    expect(showError).toHaveBeenCalled();
  });

  it("szansa z krokiem pokazuje krok, nie „+ krok”", () => {
    board([item({ next_step: { kind: "call", at: "2026-11-20T09:00:00Z" } as Opportunity["next_step"] })]);
    expect(screen.queryByRole("button", { name: "+ krok" })).toBeNull();
  });

  it("sam podgląd nie ma „+ krok”", () => {
    board([item()], false);
    expect(screen.queryByRole("button", { name: "+ krok" })).toBeNull();
    expect(screen.getByText("brak kroku")).toBeTruthy();
  });
});
