import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ClientRebateEditor } from "@/components/clients/invoicing/issue/ClientRebateEditor";
import { InvoiceRebateBox, rebateTiersText } from "@/components/clients/invoicing/issue/InvoiceRebateBox";
import type { InvoiceRebate, RebateTerms } from "@/lib/api/issued-invoices";

const REBATE: InvoiceRebate = {
  year: 2026,
  month: 10,
  threshold_currency: "EUR",
  tiers: [
    { up_to: "1000000.00", rate: "2.5" },
    { up_to: null, rate: "3" },
  ],
  turnover: "999000.00",
  turnover_before: "990000.00",
  rate: "2.5",
  next_rate: "3",
  to_next: "1000.00",
  due: "24975.00",
  on_invoice: "250.00",
  currency: "PLN",
  corrections: [],
  invoices: 120,
  excluded: 2,
  missing_fx: 0,
  archived: 0,
  unreadable: 0,
};

describe("rabat od obrotu na karcie faktury", () => {
  it("opisuje progi z nadwyżką", () => {
    expect(rebateTiersText(REBATE)).toMatch(/^do 1\s?000\s?000,00\sEUR 2,5%, nadwyżka 3%$/);
    expect(rebateTiersText({ ...REBATE, tiers: [{ up_to: null, rate: "2.5" }] })).toBe("2,5%");
  });

  it("pokazuje stawkę faktury, licznik do progu i kwotę pozycji rabatu", () => {
    render(<InvoiceRebateBox rebate={REBATE} />);
    const box = screen.getByRole("region", { name: "Rabat od obrotu" });
    expect(within(box).getByText("Rabat od obrotu 2026 · 2,5%")).toBeInTheDocument();
    expect(within(box).getByText("Do progu 3%")).toBeInTheDocument();
    expect(within(box).getByText("Rabat na tej fakturze")).toBeInTheDocument();
    expect(box).toHaveTextContent(/−250,00\szł/);
    expect(box).toHaveTextContent("Poza obrotem pozycje podróży i refaktur z 2 fakt.");
    expect(within(box).queryByText(/brak rabatu/)).toBeNull();
    expect(within(box).queryByText(/Korekta za/)).toBeNull();
    expect(within(box).queryByText(/archiwum eBI24/)).toBeNull();
  });

  it("liczy faktury sprzed KSeF z archiwum eBI24 i ostrzega o nieczytelnych plikach", () => {
    render(<InvoiceRebateBox rebate={{ ...REBATE, archived: 300, unreadable: 2 }} />);
    expect(screen.getByText("W obrocie 300 fakt. sprzed KSeF z archiwum eBI24.")).toBeInTheDocument();
    expect(screen.getByText(/Bez czytelnego pliku w archiwum eBI24: 2 fakt\. — obrót może być zaniżony\./)).toHaveClass(
      "text-destructive",
    );
  });

  it("po przekroczeniu: korekta za miesiąc przekroczenia, brak pozycji ostrzega", () => {
    render(
      <InvoiceRebateBox
        rebate={{
          ...REBATE,
          rate: "3",
          next_rate: null,
          to_next: null,
          missing_fx: 3,
          on_invoice: null,
          corrections: [
            { month: 9, rate_diff: "0.5", excess: "200000.00", amounts: [{ currency: "PLN", amount: "4250.00" }], issued: [] },
          ],
        }}
      />,
    );
    expect(screen.queryByText(/Do progu/)).toBeNull();
    expect(screen.getByText("brak rabatu")).toBeInTheDocument();
    expect(screen.getByText(/Żaden wiersz nie ma rabatu %/)).toBeInTheDocument();
    expect(screen.getByText(/Korekta za Wrzesień 2026: 0,5% od/)).toHaveTextContent(/4\s?250,00\szł/);
    expect(screen.getByText(/Bez kursu NBP do progu: 3 fakt\./)).toBeInTheDocument();
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

describe("podgląd netto pozycji z rabatem %", () => {
  it("liczy jak serwer i eBI24: cena po rabacie do grosza × ilość", async () => {
    const { previewNet } = await import("@/components/clients/invoicing/issue/issue-format");
    expect(previewNet({ quantity: "80", unit_price: "157", discount_pct: "2.5" })).toBe("12246.40");
    expect(previewNet({ quantity: "80", unit_price: "157" })).toBe("12560.00");
    expect(previewNet({ quantity: "80", unit_price: "157", discount_pct: "100" })).toBe("12560.00");
  });
});

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
