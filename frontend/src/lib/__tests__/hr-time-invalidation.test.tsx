import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

// Godziny i decyzje o timesheecie widać też w Płacach (godziny, status
// timesheetu w miesiącu) i w „Moim zespole”. Domyślne `staleTime` to 30 s —
// bez unieważnienia oba ekrany pokazywały stan sprzed akceptacji albo wpisu.

const ok = vi.hoisted(() => vi.fn(async () => ({ data: { id: 1, status: "approved" } })));
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { post: ok, patch: ok, put: ok, delete: ok, get: vi.fn() },
}));

import { payrollKeys } from "@/lib/api/hr-payroll";
import { teamKeys } from "@/lib/api/hr-team";
import {
  timeKeys,
  useDecideTimesheet,
  useDeleteTeamEntry,
  useSaveMyEntry,
  useSaveTeamEntry,
  useSubmitMonth,
} from "@/lib/api/hr-time";

const AFFECTED: [string, QueryKey][] = [
  ["„Mój miesiąc”", timeKeys.month(2026, 11)],
  ["moje Płace", payrollKeys.me],
  ["miesiąc Płac", payrollKeys.month(2026, 11)],
  ["„Mój zespół”", teamKeys.team(null)],
];

const UNRELATED: QueryKey = ["candidates", "list"];

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  for (const [, key] of AFFECTED) client.setQueryData(key, { seeded: true });
  client.setQueryData(UNRELATED, { seeded: true });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

const ENTRY = { day: "2026-11-03", hours: 8 };

const MUTATIONS: [string, () => { mutateAsync: (arg: never) => Promise<unknown> }, unknown][] = [
  ["decyzja o timesheecie", useDecideTimesheet, { id: 1, decision: "approve" }],
  ["własny wpis godzin", () => useSaveMyEntry(2026, 11), ENTRY],
  ["wysłanie miesiąca", () => useSubmitMonth(2026, 11), undefined],
  ["wpis za osobę z zespołu", () => useSaveTeamEntry(7, 2026, 11), ENTRY],
  ["usunięcie wpisu w zespole", useDeleteTeamEntry, 1],
];

describe("po zmianie godzin albo decyzji o timesheecie", () => {
  it.each(MUTATIONS)("%s odświeża Płace i „Mój zespół”", async (_, useHook, arg) => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useHook(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(arg as never);
    });

    for (const [label, key] of AFFECTED) {
      expect(client.getQueryState(key)?.isInvalidated, label).toBe(true);
    }
    expect(client.getQueryState(UNRELATED)?.isInvalidated).toBe(false);
  });
});
