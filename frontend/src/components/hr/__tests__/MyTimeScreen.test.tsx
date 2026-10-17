/**
 * „Mój czas”: przejście z „Przeglądu” do zakładki raportu godzin zapisuje
 * zakładkę i miesiąc w adresie (`?tab=month&year=&month=`), z którego zakładka
 * czyta miesiąc. Zaległy raport z „Do zrobienia” otwiera swój miesiąc, a
 * „Uzupełnij dzień” — bieżący, także gdy w adresie został wcześniejszy.
 * Dane fikcyjne.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { YearMonth } from "@/lib/date-pl";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/my-time",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/lib/api/hr", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/hr")>("@/lib/api/hr");
  return {
    ...actual,
    useMyHrProfile: () => ({
      data: { has_profile: true, employment_type: "b2b", name: "Ola Przykładowa" },
      isLoading: false,
      isError: false,
      error: null,
      isSuccess: true,
      refetch: vi.fn(),
    }),
  };
});
vi.mock("../me/MyOverviewTab", () => ({
  MyOverviewTab: ({ onOpenTab }: { onOpenTab: (value: string, month?: YearMonth) => void }) => (
    <div>
      <button type="button" onClick={() => onOpenTab("month", { year: 2026, month: 8 })}>
        Wyślij raport godzin za sierpień 2026
      </button>
      <button type="button" onClick={() => onOpenTab("month")}>
        Uzupełnij dzień
      </button>
    </div>
  ),
}));
vi.mock("../time/MyMonthTab", () => ({
  MyMonthTab: ({ initialMonth }: { initialMonth?: YearMonth }) => (
    <p>Miesiąc: {initialMonth ? `${initialMonth.year}-${initialMonth.month}` : "brak"}</p>
  ),
}));
vi.mock("../leave/MyLeaveTab", () => ({ MyLeaveTab: () => null }));
vi.mock("../payroll/MyBonusesTab", () => ({ MyBonusesTab: () => null }));
vi.mock("@/components/equipment/PersonEquipmentPanel", () => ({ PersonEquipmentPanel: () => null }));

import { hrConfig } from "@/app/preview/hr-fixtures";

import { MyTimeScreen } from "../MyTimeScreen";
import { currentYearMonth } from "../time/time-format";

afterEach(() => {
  window.history.replaceState(null, "", "/");
  vi.clearAllMocks();
});

describe("MyTimeScreen — przejście z Przeglądu do raportu godzin", () => {
  it("zaległy miesiąc z „Do zrobienia” trafia do adresu i do zakładki", () => {
    window.history.replaceState(null, "", "/my-time");
    render(<MyTimeScreen config={hrConfig()} />);

    fireEvent.click(screen.getByRole("button", { name: "Wyślij raport godzin za sierpień 2026" }));

    expect(screen.getByRole("tab", { name: "Raport godzin", selected: true })).toBeInTheDocument();
    expect(screen.getByText("Miesiąc: 2026-8")).toBeInTheDocument();
    const params = new URLSearchParams(window.location.search);
    expect([params.get("tab"), params.get("year"), params.get("month")]).toEqual(["month", "2026", "8"]);
    expect(router.replace).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("„Uzupełnij dzień” otwiera bieżący miesiąc, nie ten, który został w adresie", () => {
    window.history.replaceState(null, "", "/my-time?year=2026&month=8");
    render(<MyTimeScreen config={hrConfig()} />);

    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij dzień" }));

    const now = currentYearMonth();
    expect(screen.getByText(`Miesiąc: ${now.year}-${now.month}`)).toBeInTheDocument();
    const params = new URLSearchParams(window.location.search);
    expect([params.get("tab"), params.get("year"), params.get("month")]).toEqual([
      "month",
      String(now.year),
      String(now.month),
    ]);
  });
});
