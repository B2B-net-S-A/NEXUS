import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMentionableUsers, type MentionScope } from "@/hooks/useMentionableUsers";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("useMentionableUsers", () => {
  it.each<[string, MentionScope, boolean, Record<string, unknown>]>([
    ["job", { kind: "job", jobId: 12 }, false, { job_id: 12 }],
    ["candidate", { kind: "candidate", candidateId: 34 }, false, { candidate_id: 34 }],
    ["global", { kind: "global" }, false, {}],
    ["global + nieaktywni", { kind: "global" }, true, { include_inactive: "true" }],
  ])("scope %s → parametry zapytania", async (_label, scope, includeInactive, params) => {
    mocks.get.mockResolvedValue({ data: [] });
    const { wrapper } = setup();

    const { result } = renderHook(() => useMentionableUsers(scope, { includeInactive }), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mocks.get).toHaveBeenCalledWith("/api/users/mentionable", { params });
  });

  it("mapuje użytkowników, a brak imienia zastępuje emailem", async () => {
    mocks.get.mockResolvedValue({
      data: [
        { id: 1, name: "Anna Nowak", email: "anna@example.com", role: "recruiter" },
        { id: 2, name: null, email: "bez.imienia@example.com", role: "tac" },
      ],
    });
    const { wrapper } = setup();

    const { result } = renderHook(() => useMentionableUsers({ kind: "job", jobId: 1 }), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([
      { id: 1, name: "Anna Nowak", email: "anna@example.com", role: "recruiter" },
      { id: 2, name: "bez.imienia@example.com", email: "bez.imienia@example.com", role: "tac" },
    ]);
  });

  it("klucz cache rozróżnia scope i nieaktywnych — nie miesza list", async () => {
    mocks.get.mockImplementation((_url: string, { params }: { params: Record<string, unknown> }) =>
      Promise.resolve({
        data: [{ id: Number(params.job_id ?? 0), name: `job-${params.job_id}`, email: "x@example.com", role: "r" }],
      }),
    );
    const { wrapper, client } = setup();

    const a = renderHook(() => useMentionableUsers({ kind: "job", jobId: 1 }), { wrapper });
    const b = renderHook(() => useMentionableUsers({ kind: "job", jobId: 2 }), { wrapper });
    await waitFor(() => expect(a.result.current.isSuccess && b.result.current.isSuccess).toBe(true));

    expect(a.result.current.data?.[0].name).toBe("job-1");
    expect(b.result.current.data?.[0].name).toBe("job-2");
    expect(client.getQueryData(["mentionable-users", "job:1", false])).toBeDefined();
    expect(client.getQueryData(["mentionable-users", "job:1", true])).toBeUndefined();

    // Drugi konsument tego samego scope korzysta z cache (staleTime 60 s).
    const c = renderHook(() => useMentionableUsers({ kind: "job", jobId: 1 }), { wrapper });
    await waitFor(() => expect(c.result.current.isSuccess).toBe(true));
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it("błąd API jest błędem zapytania, nie pustą listą", async () => {
    mocks.get.mockRejectedValue(new Error("403"));
    const { wrapper } = setup();

    const { result } = renderHook(() => useMentionableUsers({ kind: "global" }), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
