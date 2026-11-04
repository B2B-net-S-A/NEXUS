import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopupsPanel } from "../TopupsPanel";

// „Dopłaty do decyzji”: licznik Akceptacji je dolicza, więc awaria zapytania
// nie może wyglądać jak brak dopłat (audyt 22.10.2026, F86).
const topups = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr-approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/hr-approvals")>();
  return {
    ...actual,
    usePendingTopups: () => topups.current,
    useDecideTopup: () => ({ isPending: false, mutate: vi.fn() }),
  };
});

describe("TopupsPanel", () => {
  beforeEach(() => {
    topups.current = {};
  });

  it("przy awarii pokazuje błąd i „Spróbuj ponownie”, który ponawia zapytanie", async () => {
    const refetch = vi.fn();
    topups.current = { isError: true, isSuccess: false, isPending: false, data: undefined, error: new Error("boom"), refetch };
    render(<TopupsPanel />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać dopłat do decyzji.");
    await userEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(refetch).toHaveBeenCalled();
  });

  it("bez dopłat i w trakcie wczytywania — nic", () => {
    topups.current = { isError: false, isSuccess: true, isPending: false, data: [] };
    const { container, rerender } = render(<TopupsPanel />);
    expect(container).toBeEmptyDOMElement();
    topups.current = { isError: false, isSuccess: false, isPending: true, data: undefined };
    rerender(<TopupsPanel />);
    expect(container).toBeEmptyDOMElement();
  });
});
