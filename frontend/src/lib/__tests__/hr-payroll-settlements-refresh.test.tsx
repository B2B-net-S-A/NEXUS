import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

// Zamknięcie miesiąca zakłada rozliczenia, ponowne otwarcie anuluje nieopłacone,
// a decyzja w rozliczeniu zmienia listę „Dla Finansów” — każdy z tych zapisów
// musi odświeżyć rozliczenia i przelewy, nie tylko płace (audyt A2, 19.10.2026).

const post = vi.hoisted(() => vi.fn(async () => ({ data: {} })));
vi.mock("@/lib/api", () => ({ __esModule: true, api: { get: vi.fn(), post, delete: vi.fn() } }));

import { payrollKeys, useCloseMonth, useReopenMonth } from "@/lib/api/hr-payroll";
import { paymentKeys } from "@/lib/api/hr-payments";
import { settlementKeys, useApproveSettlement } from "@/lib/api/hr-settlements";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () => ({
      close: useCloseMonth(2026, 10),
      reopen: useReopenMonth(2026, 10),
      approve: useApproveSettlement(),
    }),
    { wrapper },
  );
  const keys = () => spy.mock.calls.map(([filters]) => filters?.queryKey);
  return { ...hook, spy, keys };
}

describe("odświeżanie po zapisach płac i rozliczeń", () => {
  it("zamknięcie miesiąca odświeża płace, rozliczenia i przelewy (z Symfonią)", async () => {
    const { result, keys } = setup();
    await act(async () => {
      await result.current.close.mutateAsync(false);
    });
    expect(keys()).toEqual(
      expect.arrayContaining([payrollKeys.all, settlementKeys.all, paymentKeys.all]),
    );
  });

  it("ponowne otwarcie miesiąca odświeża rozliczenia i przelewy", async () => {
    const { result, keys } = setup();
    await act(async () => {
      await result.current.reopen.mutateAsync("Korekta godzin");
    });
    expect(keys()).toEqual(
      expect.arrayContaining([payrollKeys.all, settlementKeys.all, paymentKeys.all]),
    );
  });

  it("zatwierdzenie rozliczenia odświeża „Przelewy”", async () => {
    const { result, keys } = setup();
    await act(async () => {
      await result.current.approve.mutateAsync(5003);
    });
    expect(keys()).toEqual(
      expect.arrayContaining([settlementKeys.all, payrollKeys.all, paymentKeys.all]),
    );
  });
});
