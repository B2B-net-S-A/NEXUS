/**
 * Zapisy opieki odświeżają ekrany, które pokazują ich skutek (audyt 22.10.2026):
 * przekazanie do front office (F7), rytm i opiekun hurtem oraz „Wskaż menedżera”
 * (F8), opinia menedżera z popytem (F91) — tablica „Do zrobienia”, Konsultanci
 * i Klienci nie mogą zostać nieaktualne pod zamkniętym oknem.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ __esModule: true, api: { post }, default: { post } }));

import { useAssignOwners, useHandOffToFrontOffice, useSetContractCadence } from "@/lib/api/care";
import { useSaveClientFeedbackWithDemand } from "@/lib/api/care-clients";
import { useSaveClientFeedback } from "@/lib/api/client-people";
import { useApplyManagers } from "@/lib/api/structure-proposals";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const invalidated = () => spy.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { wrapper, invalidated };
}

/** Klucz `key` albo jego prefiks został unieważniony. */
function covers(invalidated: string[], key: readonly unknown[]): boolean {
  return invalidated.some((raw) => {
    const prefix = JSON.parse(raw) as unknown[];
    return prefix.every((part, index) => JSON.stringify(part) === JSON.stringify(key[index]));
  });
}

const BOARD = ["care", "board", "mine"];
const CLIENTS = ["care", "clients", "mine"];
const CONSULTANTS = ["care", "consultants"];

beforeEach(() => {
  post.mockReset();
});

describe("odświeżanie po zapisach opieki", () => {
  it("F7: przekazanie do front office odświeża tablicę, kartę, Konsultantów i Klientów", async () => {
    post.mockResolvedValue({ data: {} });
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useHandOffToFrontOffice(10), { wrapper });
    await act(() => result.current.mutateAsync([1]));
    const keys = invalidated();
    expect(covers(keys, BOARD)).toBe(true);
    expect(covers(keys, ["care", "contract", 10, "card"])).toBe(true);
    expect(covers(keys, CONSULTANTS)).toBe(true);
    expect(covers(keys, CLIENTS)).toBe(true);
  });

  it("F8: zmiana rytmu i opiekuna hurtem odświeża tablicę i Klientów", async () => {
    post.mockResolvedValue({ data: {} });
    const { wrapper, invalidated } = setup();
    const cadence = renderHook(() => useSetContractCadence(10), { wrapper });
    await act(() => cadence.result.current.mutateAsync({ level: "paused" } as never));
    expect(covers(invalidated(), BOARD)).toBe(true);
    expect(covers(invalidated(), CLIENTS)).toBe(true);

    const second = setup();
    const owners = renderHook(() => useAssignOwners(), { wrapper: second.wrapper });
    await act(() =>
      owners.result.current.mutateAsync({ contract_ids: [10], owner_user_id: 5, reason: "other" } as never),
    );
    expect(covers(second.invalidated(), BOARD)).toBe(true);
    expect(covers(second.invalidated(), CLIENTS)).toBe(true);
  });

  it("F8: „Wskaż menedżera” odświeża Konsultantów, tablicę i Klientów", async () => {
    post.mockResolvedValue({ data: { client: { client_id: 30 }, conflicts: [] } });
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useApplyManagers(30), { wrapper });
    await act(() => result.current.mutateAsync([{ contract_id: 10, contact_id: 3 }] as never));
    expect(covers(invalidated(), CONSULTANTS)).toBe(true);
    expect(covers(invalidated(), BOARD)).toBe(true);
    expect(covers(invalidated(), CLIENTS)).toBe(true);
  });

  it("F91: zapis opinii menedżera (z popytem i bez) odświeża listę Klientów", async () => {
    post.mockResolvedValue({ data: { id: 1, contract_ids: [], demand_keys: [] } });
    const first = setup();
    const withDemand = renderHook(() => useSaveClientFeedbackWithDemand(30), { wrapper: first.wrapper });
    await act(() => withDemand.result.current.mutateAsync({ held_on: "2026-10-22" } as never));
    expect(covers(first.invalidated(), CLIENTS)).toBe(true);

    const second = setup();
    const plain = renderHook(() => useSaveClientFeedback(30), { wrapper: second.wrapper });
    await act(() => plain.result.current.mutateAsync({ contact_id: 3, held_on: "2026-10-22" } as never));
    expect(covers(second.invalidated(), CLIENTS)).toBe(true);
  });
});
