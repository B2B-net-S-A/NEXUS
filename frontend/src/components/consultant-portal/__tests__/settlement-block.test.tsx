import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PortalMonthSettlement } from "@/lib/api/consultant-portal";

import { SettlementBlock } from "../DocumentsSection";

const base: PortalMonthSettlement = {
  status: "accepted",
  label: "RCP przyjęte: wystaw fakturę",
  fix_reason: null,
  checks: [
    { state: "ok", title: "Podpis elektroniczny ważny, plik bez zmian po podpisie" },
    { state: "none", title: "Czy akceptacja była przed pracą: sprawdza człowiek" },
  ],
  todo: [],
  md_regular: "17.000",
  md_extra: "4.750",
  md_remaining_after: "9.800",
  invoice: { amount_net: "24680.00", sale_date: "2026-10-31", payment_days: 7 },
};

describe("SettlementBlock (panel konsultanta, E3)", () => {
  it("po przyjęciu pokazuje kwotę, datę sprzedaży i termin z reguły klienta", () => {
    render(<SettlementBlock settlement={base} />);
    expect(screen.getByText("RCP przyjęte: wystaw fakturę")).toBeInTheDocument();
    expect(screen.getByText(/24\s680,00 zł/)).toBeInTheDocument();
    expect(screen.getByText("7 dni od nadania numeru KSeF")).toBeInTheDocument();
    expect(screen.getByText(/17 MD i 4,75 MD pracy dodatkowej · na zamówieniu zostanie 9,8 MD/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Sprawdza człowiek" })).toBeInTheDocument();
  });

  it("przed przyjęciem nie ma danych do faktury, przy poprawce jest powód", () => {
    render(
      <SettlementBlock
        settlement={{ ...base, status: "needs_fix", label: "RCP do poprawy", fix_reason: "Brak podpisu klienta", invoice: null, md_remaining_after: null }}
      />,
    );
    expect(screen.getByText("Co poprawić: Brak podpisu klienta")).toBeInTheDocument();
    expect(screen.queryByText("Kwota netto")).not.toBeInTheDocument();
    expect(screen.queryByText(/na zamówieniu zostanie/)).not.toBeInTheDocument();
  });

  it("nie ma paska kroków miesiąca (styl A z 04.11.2026)", () => {
    render(<SettlementBlock settlement={base} />);
    expect(screen.queryByText("Sprawdzenie")).not.toBeInTheDocument();
    expect(screen.queryByText("Przelew")).not.toBeInTheDocument();
  });

  it("po przyjęciu daje dane do skopiowania: nabywca, pozycja, kwota bez „zł”", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <SettlementBlock
        settlement={{
          ...base,
          invoice: {
            ...base.invoice!,
            buyer: { name: "Spółka Testowa S.A.", nip: "9990000001", address: "ul. Próbna 1, 00-001 Warszawa" },
            item: { description: "Usługi zgodnie z umową za październik 2026", quantity: "1", net: "24680.00" },
            ksef: null,
          },
        }}
      />,
    );
    expect(screen.getByText("Usługi zgodnie z umową za październik 2026")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj: Kwota netto" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("24 680,00".replace(" ", "\u00a0")));
    expect(screen.queryByText(/×|1,2|120/)).not.toBeInTheDocument();
  });

  it("faktura w KSeF zastępuje dane do faktury; inna kwota pokazuje obie", () => {
    const ksef = { state: "in_ksef" as const, label: "Faktura w KSeF", invoice_number: "FV 7/10/2026", ksef_number: "X", net_amount: "24680.00", due_date: "2026-11-17" };
    const { rerender } = render(<SettlementBlock settlement={{ ...base, invoice: { ...base.invoice!, ksef } }} />);
    expect(screen.getByText("FV 7/10/2026")).toBeInTheDocument();
    expect(screen.getByText("Płatność do")).toBeInTheDocument();
    expect(screen.queryByText("Dane do faktury")).not.toBeInTheDocument();
    rerender(
      <SettlementBlock
        settlement={{ ...base, invoice: { ...base.invoice!, ksef: { ...ksef, state: "differs", net_amount: "38000.00" } } }}
      />,
    );
    expect(screen.getByText("Z rozliczenia")).toBeInTheDocument();
    expect(screen.queryByText("Płatność do")).not.toBeInTheDocument();
  });
});
