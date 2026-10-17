import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaymentSettings } from "@/lib/api/hr-payments";

const saveMutate = vi.fn();
const query: { value: Record<string, unknown> } = { value: {} };

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr-payments", () => ({
  usePaymentSettings: () => query.value,
  useSavePaymentSettings: () => ({ mutate: saveMutate, isPending: false }),
}));

import {
  PaymentSettingsCard,
  isValidPlAccount,
  paymentSettingsPayload,
} from "@/components/hr/settings/PaymentSettingsCard";

// Fikcyjne rachunki: bank 9999xxxx nie istnieje, suma kontrolna poprawna.
const COMPANY = "72999900010000000000001234";

function settings(overrides: Partial<PaymentSettings> = {}): PaymentSettings {
  return {
    payout_day: 10,
    transfer_batch: { enabled: false, format: "elixir", sender_account: null, sender_name: "" },
    symfonia: {
      leave_events: { vacation: "Urlop wypoczynkowy", sick_leave: "Choroba zwykła" },
      export_sick_leave: false,
      overtime_event: "Nadgodziny",
      work_start: "08:00",
      bonus_components: { sales: "Premia sprzedażowa" },
      contract_kind: "zlecenie",
      payment_form: "przelew",
    },
    ...overrides,
  };
}

beforeEach(() => {
  saveMutate.mockClear();
  query.value = { data: settings(), isLoading: false, isError: false, error: null, isSuccess: true };
});

describe("Ustawienia → Płace → Płatności i Symfonia", () => {
  it("rachunek PL: suma kontrolna IBAN jak na serwerze", () => {
    expect(isValidPlAccount(COMPANY)).toBe(true);
    expect(isValidPlAccount(`PL${COMPANY}`)).toBe(true);
    expect(isValidPlAccount("PL72 9999 0001 0000 0000 0000 1234")).toBe(true);
    expect(isValidPlAccount("72999900010000000000001235")).toBe(false);
    expect(isValidPlAccount("123")).toBe(false);
  });

  it("walidacja przed zapisem: dzień, rachunek, paczka bez nadawcy, godzina", () => {
    expect(paymentSettingsPayload(settings({ payout_day: 0 }))).toEqual({
      error: "Dzień wypłaty: liczba od 1 do 31.",
    });
    const batch = (changes: Partial<PaymentSettings["transfer_batch"]>) =>
      settings({ transfer_batch: { ...settings().transfer_batch, ...changes } });
    expect(paymentSettingsPayload(batch({ sender_account: "72999900010000000000001235" }))).toEqual(
      expect.objectContaining({ error: expect.stringMatching(/sumą kontrolną/) }),
    );
    expect(paymentSettingsPayload(batch({ enabled: true }))).toEqual({
      error: "Paczka przelewów wymaga rachunku i nazwy nadawcy (firmy).",
    });
    expect(
      paymentSettingsPayload(
        settings({ symfonia: { ...settings().symfonia, work_start: "17:00" } }),
      ),
    ).toEqual(expect.objectContaining({ error: expect.stringMatching(/Początek dnia/) }));
  });

  it("puste nazwy znikają z ciała (ten rodzaj trafia do listy „do zrobienia”)", () => {
    const parsed = paymentSettingsPayload(
      settings({
        symfonia: {
          ...settings().symfonia,
          leave_events: { vacation: " Urlop wypoczynkowy ", training: "  " },
        },
      }),
    );
    expect("payload" in parsed && parsed.payload.symfonia.leave_events).toEqual({
      vacation: "Urlop wypoczynkowy",
    });
  });

  it("zmiana pola i zapis wysyłają cały formularz", () => {
    render(<PaymentSettingsCard />);
    expect(screen.getByText("Płatności i Symfonia")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Zapisz ustawienia" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Zdarzenie w Symfonii: Urlop szkoleniowy"), {
      target: { value: "Urlop szkoleniowy" },
    });
    fireEvent.click(save);
    expect(saveMutate).toHaveBeenCalledTimes(1);
    const body = saveMutate.mock.calls[0][0] as PaymentSettings;
    expect(body.payout_day).toBe(10);
    expect(body.symfonia.leave_events.training).toBe("Urlop szkoleniowy");
  });

  it("brak uprawnienia albo wyłączony moduł — karty nie ma", () => {
    query.value = {
      data: undefined,
      isLoading: false,
      isError: true,
      isSuccess: false,
      error: { response: { status: 403 } },
    };
    const { container } = render(<PaymentSettingsCard />);
    expect(container).toBeEmptyDOMElement();
  });
});
