import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KindBars } from "../ApprovedExpensesTab";

// „Według rodzaju” w Finansach → Wydatki ze zgodą: pusty stan tylko po udanym
// zapytaniu — awaria i wczytywanie nie mogą mówić „nic nie zatwierdzono”
// (audyt 22.10.2026, F22).
const summary = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("@/lib/api/approved-expenses", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/approved-expenses")>();
  return { ...actual, useExpensesSummary: () => summary.current };
});

const EMPTY = "W tym miesiącu nic nie zatwierdzono.";

describe("KindBars — suma miesiąca według rodzaju", () => {
  beforeEach(() => {
    summary.current = {};
  });

  it("przy awarii zapytania nie twierdzi, że nic nie zatwierdzono", () => {
    summary.current = { isError: true, isSuccess: false, isPending: false, data: undefined };
    render(<KindBars year={2026} month={10} />);
    expect(screen.queryByText(EMPTY)).toBeNull();
  });

  it("w trakcie wczytywania pokazuje „Wczytywanie…”, nie pusty stan", () => {
    summary.current = { isError: false, isSuccess: false, isPending: true, data: undefined };
    render(<KindBars year={2026} month={10} />);
    expect(screen.queryByText(EMPTY)).toBeNull();
    expect(screen.getByText("Wczytywanie…")).toBeInTheDocument();
  });

  it("po udanym zapytaniu bez kwot — pusty stan", () => {
    summary.current = {
      isError: false,
      isSuccess: true,
      isPending: false,
      data: { by_kind: [], other_currency_count: 0 },
    };
    render(<KindBars year={2026} month={10} />);
    expect(screen.getByText(EMPTY)).toBeInTheDocument();
  });
});
