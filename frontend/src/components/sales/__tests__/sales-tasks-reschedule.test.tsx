/**
 * Lista Zadania: „Przełóż” w wierszu z terminami całego modułu (decyzja Artura 11.11.2026).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateActivity = vi.fn();
const updatedIds = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
let canEdit = true;

const TASKS = [
  {
    id: 51,
    subject: "Oddzwonić",
    kind: "task",
    due_at: "2026-11-01T09:00:00Z",
    done_at: null,
    overdue: true,
    assignee: null,
    company: { id: 7, name: "Firma Testowa" },
    opportunity: null,
  },
  {
    id: 52,
    subject: "Zrobione wcześniej",
    kind: "task",
    due_at: "2026-11-01T09:00:00Z",
    done_at: "2026-11-02T09:00:00Z",
    overdue: false,
    assignee: null,
    company: null,
    opportunity: null,
  },
];

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesTasks: () => ({ isLoading: false, error: null, isSuccess: true, data: { items: TASKS, total: TASKS.length } }),
  useCompleteActivity: () => ({ mutate: vi.fn(), isPending: false }),
  useCompleteTasks: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateActivity: (id: number) => ({
    mutate: (payload: unknown, options: unknown) => {
      updatedIds(id);
      updateActivity(payload, options);
    },
    isPending: false,
  }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: object }) => unknown) => selector({ user: {} }),
}));

import { STEP_WHEN } from "../CallLogDialogs";
import { TasksView } from "../TasksView";

beforeEach(() => {
  vi.clearAllMocks();
  canEdit = true;
});

describe("„Przełóż” na liście Zadania", () => {
  it("przekłada otwarte zadanie na wybrany termin bez wchodzenia w kartę", () => {
    updateActivity.mockImplementation((_payload, { onSuccess }) => onSuccess());
    render(<TasksView />);
    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    fireEvent.click(screen.getByRole("button", { name: "Za tydzień" }));
    expect(updatedIds).toHaveBeenCalledWith(51);
    const due = new Date(updateActivity.mock.calls[0][0].due_at);
    const week = new Date();
    week.setDate(week.getDate() + 7);
    expect(due.toDateString()).toBe(week.toDateString());
    expect(showSuccess).toHaveBeenCalled();
  });

  it("zrobione zadanie nie ma „Przełóż”, a podgląd bez edycji nie ma go wcale", () => {
    render(<TasksView />);
    expect(screen.getAllByRole("button", { name: "Przełóż" })).toHaveLength(1);
    canEdit = false;
    render(<TasksView />);
    expect(screen.getAllByRole("button", { name: "Przełóż" })).toHaveLength(1);
  });

  it("błąd zapisu wraca jako komunikat", () => {
    updateActivity.mockImplementation((_payload, { onError }) => onError(new Error("boom")));
    render(<TasksView />);
    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    expect(showError).toHaveBeenCalled();
  });

  it("terminy są te same co w całym module", () => {
    render(<TasksView />);
    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    for (const option of STEP_WHEN) expect(screen.getByRole("button", { name: option.label })).toBeTruthy();
    expect(STEP_WHEN.map((option) => option.days)).toEqual([1, 3, 7, 14, 30]);
  });
});
