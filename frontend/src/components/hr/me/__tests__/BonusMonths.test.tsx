/** „Premie i stawka” po miesiącach: wybór, podsumowanie i awaria rozliczenia. Dane fikcyjne. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SettlementMonth } from "@/lib/api/hr-payroll";

import { BonusMonths } from "../BonusMonths";
import type { MyBonusItem } from "../overview-format";

function item(key: string, title: string, month: number, overrides: Partial<MyBonusItem> = {}): MyBonusItem {
  return {
    key,
    title,
    subtitle: "Delivery Lead",
    stages: [
      { label: "przyznana", state: "done" },
      { label: "wypłata", state: "current" },
    ],
    amount: "100.00",
    currency: "PLN",
    estimate: false,
    when: "",
    cancelled: false,
    inTransit: false,
    progress: null,
    timeline: "",
    period: { year: 2026, month },
    ...overrides,
  };
}

const september: SettlementMonth = {
  year: 2026,
  month: 9,
  label: "wrzesień 2026",
  final: false,
  hours: "160.00",
  hours_source: "approved",
  timesheet_status: "approved",
  rate_missing: false,
  lines: [{ currency: "PLN", hourly_rate: "90.00", hours_amount: "14400.00", bonus_total: "100.00", total: "14500.00" }],
};

const november: SettlementMonth = {
  ...september,
  month: 11,
  label: "listopad 2026",
  hours: "0",
  hours_source: "none",
  lines: [{ currency: "PLN", hourly_rate: "90.00", hours_amount: "0.00", bonus_total: "0.00", total: "0.00" }],
};

const items = [
  item("wrzesniowa", "Placement: Wrześniowy", 9),
  item("listopadowa", "Placement: Listopadowy", 11, { inTransit: true, amount: "700.00" }),
];

const nbsp = (value: string | null) => (value ?? "").replace(/\s/g, " ");

function renderMonths(props: Partial<React.ComponentProps<typeof BonusMonths>> = {}) {
  return render(
    <BonusMonths
      items={items}
      settlement={{ months: [september, november] }}
      settlementState="ready"
      today="2026-11-03"
      form="b2b"
      {...props}
    />,
  );
}

const summary = (name: RegExp) => screen.getByRole("region", { name });

describe("BonusMonths", () => {
  it("na start pokazuje najnowszy miesiąc z kwotą, z podstawą i sumą", () => {
    renderMonths();
    expect(screen.getByRole("button", { name: /wrzesień/ })).toHaveAttribute("aria-pressed", "true");
    const box = summary(/wrzesień 2026/);
    expect(nbsp(box.textContent)).toContain("~ 14 400,00 zł");
    expect(nbsp(box.textContent)).toContain("160 h × 90,00 zł");
    expect(nbsp(box.textContent)).toContain("~ 14 500,00 zł");
    expect(screen.getByText("Placement: Wrześniowy")).toBeInTheDocument();
    expect(screen.queryByText("Placement: Listopadowy")).not.toBeInTheDocument();
  });

  it("pusty bieżący miesiąc: kreski zamiast zer, kwoty w drodze osobno", () => {
    renderMonths();
    fireEvent.click(screen.getByRole("button", { name: /listopad · teraz/ }));
    const box = summary(/listopad 2026/);
    expect(box.textContent).toContain("jeszcze bez godzin");
    const total = within(box).getByText(/Razem za listopad/).parentElement;
    expect(total?.textContent).toContain("—");
    expect(total?.textContent).not.toContain("zł");
    expect(within(box).getByText(/w drodze \(1\) · poza sumą/)).toBeInTheDocument();
    expect(nbsp(box.textContent)).toContain("~ 700,00 zł");
    expect(screen.getByText("Placement: Listopadowy")).toBeInTheDocument();
  });

  it("„Wszystkie” przywraca pełną listę i chowa podsumowanie miesiąca", () => {
    renderMonths();
    fireEvent.click(screen.getByRole("button", { name: "Wszystkie" }));
    expect(screen.getByText("Placement: Wrześniowy")).toBeInTheDocument();
    expect(screen.getByText("Placement: Listopadowy")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Podsumowanie/ })).not.toBeInTheDocument();
  });

  it("awaria rozliczenia nie udaje zera ani zaniżonej sumy, a lista działa", () => {
    renderMonths({ settlement: undefined, settlementState: "error" });
    const box = summary(/wrzesień 2026/);
    expect(box.textContent).toContain("nie udało się policzyć");
    const total = within(box).getByText(/Razem za wrzesień/).parentElement;
    expect(total?.textContent).toContain("—");
    expect(total?.textContent).not.toContain("zł");
    expect(screen.getByText("Placement: Wrześniowy")).toBeInTheDocument();
  });

  it("umowa o pracę mówi „premie”, B2B „wynagrodzenie dodatkowe”", () => {
    const { unmount } = renderMonths({ form: "uop" });
    expect(within(summary(/wrzesień/)).getByText("Premie")).toBeInTheDocument();
    unmount();
    renderMonths({ form: "b2b" });
    expect(within(summary(/wrzesień/)).getByText("Wynagrodzenie dodatkowe")).toBeInTheDocument();
  });

  it("etap w wierszu to bieżący krok, a cała ścieżka zostaje dla czytnika", () => {
    renderMonths();
    expect(screen.getByText("wypłata")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Cała ścieżka: przyznana › wypłata")).toBeInTheDocument();
  });
});
