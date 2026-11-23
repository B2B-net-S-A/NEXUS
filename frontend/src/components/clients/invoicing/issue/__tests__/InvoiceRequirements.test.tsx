import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ClientBuyersEditor } from "@/components/clients/invoicing/issue/ClientBuyersEditor";
import { InvoiceRequirementsBox } from "@/components/clients/invoicing/issue/InvoiceRequirementsBox";
import { BuyerPicker } from "@/components/clients/invoicing/issue/IssuedInvoiceCardView";
import { ToastProvider } from "@/components/Toast";
import type { ClientBuyer } from "@/lib/api/issued-invoices";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe("wymagania klienta na karcie szkicu (reguły cl.*)", () => {
  it("pokazuje pola do KSeF, uwagi i mail z tematem do skopiowania", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <ToastProvider>
        <InvoiceRequirementsBox
          requirements={[
            { label: "Numer umowy (KSeF)", value: "UR/2020/77" },
            { label: "OSOBA (KSeF, pole dodatkowe)", value: "koordynator@example.com" },
          ]}
          warnings={["Klient wymaga „JIRA” w opisie każdej pozycji — brak w pozycji 2."]}
          mail={{
            email: "einvoice@example.com",
            subject: "Faktura VAT Nr: 7/11/2026",
            attach: "PDF faktury",
          }}
        />
      </ToastProvider>,
    );
    const box = screen.getByRole("region", { name: "Wymagania klienta" });
    expect(within(box).getByText("UR/2020/77")).toBeInTheDocument();
    expect(within(box).getByText("koordynator@example.com")).toBeInTheDocument();
    expect(box).toHaveTextContent("JIRA");
    expect(box).toHaveTextContent("Mail z fakturą obok KSeF (załącz: PDF faktury)");
    await userEvent.click(within(box).getByRole("button", { name: "Kopiuj temat" }));
    expect(writeText).toHaveBeenCalledWith("Faktura VAT Nr: 7/11/2026");
  });

  it("klient bez wymagań nie dostaje pustej ramki", () => {
    render(
      <ToastProvider>
        <InvoiceRequirementsBox requirements={[]} warnings={[]} mail={null} />
      </ToastProvider>,
    );
    expect(screen.queryByRole("region", { name: "Wymagania klienta" })).toBeNull();
  });
});

describe("nabywca per kontrakt", () => {
  const OPTIONS = [
    { code: "b1", name: "Pankki Testi Oyj", number: "FI12345678" },
    { code: "b2", name: "Bank Testowy S.A. Oddział w Polsce", number: "1111111111" },
  ];

  it("wybór nabywcy z listy klienta wysyła jego kod", async () => {
    const onChoose = vi.fn();
    render(<BuyerPicker options={OPTIONS} value="" disabled={false} dirty={false} onChoose={onChoose} />);
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Nabywca z listy klienta" }),
      "b1",
    );
    expect(onChoose).toHaveBeenCalledWith("b1");
  });

  it("niezapisany szkic blokuje zmianę nabywcy", () => {
    render(<BuyerPicker options={OPTIONS} value="b2" disabled dirty onChoose={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Nabywca z listy klienta" })).toBeDisabled();
    expect(screen.getByText("Zapisz szkic przed zmianą nabywcy.")).toBeInTheDocument();
  });

  it("ustawienia: dodanie nabywcy z adresem doręczenia i usunięcie", async () => {
    let latest: ClientBuyer[] = [];
    function Harness() {
      const [buyers, setBuyers] = useState<ClientBuyer[]>([]);
      return (
        <ClientBuyersEditor
          label="Bank Testowy"
          buyers={buyers}
          mappedContracts={3}
          onChange={(next) => {
            latest = next;
            setBuyers(next);
          }}
        />
      );
    }
    render(<Harness />);
    expect(screen.getByText(/Nabywcy per kontrakt · przypisane kontrakty: 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/Nabywcy per kontrakt/));
    await userEvent.click(screen.getByRole("button", { name: "Dodaj nabywcę" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Nazwa nabywcy 1 — Bank Testowy" }), "Pankki Testi Oyj");
    await userEvent.type(
      screen.getByRole("textbox", { name: "Adres doręczenia nabywcy 1 — Bank Testowy" }),
      "Testgatan 1",
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Kraj doręczenia nabywcy 1 — Bank Testowy" }), "se");
    expect(latest).toEqual([
      expect.objectContaining({
        name: "Pankki Testi Oyj",
        delivery_l1: "Testgatan 1",
        delivery_country: "SE",
      }),
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Usuń nabywcę 1 — Bank Testowy" }));
    expect(latest).toEqual([]);
  });
});
