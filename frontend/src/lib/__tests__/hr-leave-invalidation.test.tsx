import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

// Nieobecność zmienia więcej niż listy urlopów: zatwierdzony (albo zgłoszony)
// urlop wpisuje i zdejmuje godziny w timesheecie (`time_hooks.py`), zmienia
// dane Płac, „Mój zespół” i kafelek zastępstw. Domyślne `staleTime` to 30 s —
// bez unieważnienia „Mój miesiąc” po zgłoszeniu pokazywał stare godziny.

const post = vi.hoisted(() => vi.fn(async () => ({ data: { id: "r1", status: "approved" } })));
vi.mock("@/lib/api", () => ({ __esModule: true, api: { post, get: vi.fn(), put: vi.fn() } }));

import { SUBSTITUTION_QUERY_KEY } from "@/lib/api/hr-dashboard";
import {
  leaveKeys,
  useCancelMyLeave,
  useCancelTeamLeave,
  useDecideLeave,
  useEnterOnBehalf,
  useReportConflict,
  useSubmitLeave,
} from "@/lib/api/hr-leave";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { teamKeys } from "@/lib/api/hr-team";
import { timeKeys } from "@/lib/api/hr-time";

const AFFECTED: [string, QueryKey][] = [
  ["moje urlopy", leaveKeys.mine],
  ["„Mój miesiąc”", timeKeys.month(2026, 11)],
  ["timesheet osoby z zespołu", timeKeys.member(7, 2026, 11)],
  ["moje Płace", payrollKeys.me],
  ["miesiąc Płac", payrollKeys.month(2026, 11)],
  ["„Mój zespół”", teamKeys.team(null)],
  ["kafelek zastępstw", SUBSTITUTION_QUERY_KEY],
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

const INPUT = {
  leave_type: "vacation" as const,
  start_date: "2026-11-02",
  end_date: "2026-11-04",
};

const MUTATIONS: [string, () => { mutateAsync: (arg: never) => Promise<unknown> }, unknown][] = [
  ["zgłoszenie własnego wniosku", useSubmitLeave, INPUT],
  ["anulowanie własnego wniosku", useCancelMyLeave, "r1"],
  ["decyzja akceptującego", useDecideLeave, { id: "r1", decision: "approve" }],
  ["anulowanie urlopu w zespole", useCancelTeamLeave, { id: "r1" }],
  ["wpis za pracownika", useEnterOnBehalf, { ...INPUT, user_id: 7 }],
  ["kolizja zgłoszona przez koordynatora", useReportConflict, { id: "r1", note: "termin" }],
];

describe("po zmianie nieobecności", () => {
  it.each(MUTATIONS)("%s odświeża godziny, Płace, zespół i kafelki", async (_, useHook, arg) => {
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
