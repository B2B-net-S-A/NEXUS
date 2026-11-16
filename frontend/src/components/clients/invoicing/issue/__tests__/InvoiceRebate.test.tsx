import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ClientRebateEditor } from "@/components/clients/invoicing/issue/ClientRebateEditor";
import { InvoiceRebateBox, rebateTiersText } from "@/components/clients/invoicing/issue/InvoiceRebateBox";
import type { InvoiceRebate, RebateTerms } from "@/lib/api/issued-invoices";

const REBATE: InvoiceRebate = {
  year: 2026,
  threshold_currency: "EUR",
  tiers: [
    { up_to: "1000000.00", rate: "2.5" },
    { up_to: null, rate: "3" },
  ],
  turnover: "999000.00",
  rate: "2.5",
  next_rate: "3",
  to_next: "1000.00",
  totals: [{ currency: "PLN", net: "4000000.00", rebate: "100000.00" }],
  this_invoice: "250.00",
  currency: "PLN",
  invoices: 120,
  excluded: 2,
  missing_fx: 0,
  settle_by: "2027-01-31",
};

describe("rabat roczny na karcie faktury", () => {
  it("opisuje progi od całego obrotu", () => {
    expect(rebateTiersText(REBATE)).toMatch(/^do 1\s?000\s?000,00\sEUR 2,5%, powyżej 3%$/);
    expect(rebateTiersText({ ...REBATE, tiers: [{ up_to: null, rate: "2.5" }] })).toBe("2,5%");
  });

  it("pokazuje stan roku, udział faktury i termin korekty, bez pozycji na fakturze", () => {
    render(<InvoiceRebateBox rebate={REBATE} />);
    const box = screen.getByRole("region", { name: "Rabat roczny" });
    expect(within(box).getByText("Rabat roczny 2026 · 2,5%")).toBeInTheDocument();
    expect(within(box).getByText("Do progu 3%")).toBeInTheDocument();
    expect(within(box).getByText("Z tej faktury")).toBeInTheDocument();
    expect(within(box).getByText("Rabat narastająco")).toBeInTheDocument();
    expect(box).toHaveTextContent("zbiorcza korekta do 31.01.2027");
    expect(box).toHaveTextContent("Poza obrotem (podróże, refaktury): 2 fakt.");
    expect(within(box).queryByText(/Bez kursu NBP/)).toBeNull();
  });

  it("po przekroczeniu progu nie pokazuje „do progu”, a brak kursu ostrzega", () => {
    render(
      <InvoiceRebateBox
        rebate={{
          ...REBATE,
          rate: "3",
          next_rate: null,
          to_next: null,
          missing_fx: 3,
          this_invoice: null,
          totals: [
            { currency: "EUR", net: "25000.00", rebate: "750.00" },
            { currency: "PLN", net: "4000000.00", rebate: "120000.00" },
          ],
        }}
      />,
    );
    expect(screen.queryByText(/Do progu/)).toBeNull();
    expect(screen.queryByText("Z tej faktury")).toBeNull();
    expect(screen.getByText(/Bez kursu NBP do progu: 3 fakt\./)).toBeInTheDocument();
    // Dwie waluty faktur: osobny wiersz rabatu na walutę.
    expect(screen.getByText("Rabat w EUR")).toBeInTheDocument();
    expect(screen.getByText("Rabat w PLN")).toBeInTheDocument();
  });
});

function Harness({ initial }: { initial?: RebateTerms }) {
  const [value, setValue] = useState<RebateTerms | undefined>(initial);
  return (
    <>
      <ClientRebateEditor label="Bank Testowy" value={value} onChange={setValue} />
      <output data-testid="json">{JSON.stringify(value ?? null)}</output>
    </>
  );
}

describe("edycja rabatu przy kliencie", () => {
  it("dodaje rabat, próg i okres z aneksu jako dane", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Rabat roczny od obrotu/ }));
    await user.selectOptions(screen.getByLabelText("Waluta progu rabatu — Bank Testowy"), "EUR");
    const year = screen.getByLabelText("Rabat od roku — Bank Testowy");
    await user.clear(year);
    await user.type(year, "2024");
    const rate = screen.getByLabelText("Próg 1: stawka % — Bank Testowy");
    await user.clear(rate);
    await user.type(rate, "2,5");
    await user.click(screen.getByRole("button", { name: "Nowe progi od roku (aneks)" }));
    const bounds = screen.getAllByLabelText("Próg 1: obrót do (EUR) — Bank Testowy");
    await user.type(bounds[1], "1000000");
    await user.click(screen.getAllByRole("button", { name: "Próg" })[1]);
    const rates = screen.getAllByLabelText("Próg 2: stawka % — Bank Testowy");
    await user.clear(rates[0]);
    await user.type(rates[0], "3");
    await user.type(screen.getByLabelText("Słowa wyłączające z rabatu — Bank Testowy"), "podróż, refaktura");

    const saved = JSON.parse(screen.getByTestId("json").textContent ?? "null") as RebateTerms;
    expect(saved.threshold_currency).toBe("EUR");
    expect(saved.periods).toEqual([
      { from_year: 2024, tiers: [{ up_to: null, rate: 2.5 }] },
      {
        from_year: 2025,
        tiers: [
          { up_to: 1000000, rate: 2.5 },
          { up_to: null, rate: 3 },
        ],
      },
    ]);
    expect(saved.exclude_words).toEqual(["podróż", "refaktura"]);

    await user.click(screen.getByRole("button", { name: "Usuń rabat" }));
    expect(screen.getByTestId("json")).toHaveTextContent("null");
  });
});
