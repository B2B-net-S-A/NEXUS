import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMentionableUsers, type MentionScope } from "@/hooks/useMentionableUsers";
import { useAuthStore, type User } from "@/store/auth";

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
        { id: 2, name: null, email: "bez.imienia@example.com", role: "delivery_lead" },
      ],
    });
    const { wrapper } = setup();

    const { result } = renderHook(() => useMentionableUsers({ kind: "job", jobId: 1 }), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([
      { id: 1, name: "Anna Nowak", email: "anna@example.com", role: "recruiter" },
      { id: 2, name: "bez.imienia@example.com", email: "bez.imienia@example.com", role: "delivery_lead" },
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

describe("useMentionableUsers — nieobecni (withAbsences)", () => {
  const people = [
    { id: 1, name: "Ola Przykładowa", email: "ola@example.com", role: "recruiter" },
    { id: 2, name: "Kamil Testowy", email: "kamil@example.com", role: "delivery_lead" },
  ];
  const away = {
    user_id: 2,
    until: "2099-10-23",
    half_day: null,
    substitute_user_id: 1,
    substitute_name: "Ola Przykładowa",
  };

  function routes(leaveOpen: boolean, absence: () => Promise<unknown>) {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/users/mentionable") return Promise.resolve({ data: people });
      if (url === "/api/hr/config") {
        return Promise.resolve({ data: { open_modules: { leave: leaveOpen }, me: {} } });
      }
      if (url === "/api/hr/leave/absence") return absence();
      return Promise.reject(new Error(`nieoczekiwany adres ${url}`));
    });
  }

  beforeEach(() => {
    useAuthStore.setState({
      user: { id: 9, email: "ja@example.com", name: "Ja", role: "recruiter", roles: ["recruiter"] } as User,
    });
  });

  it("jedno zapytanie o nieobecności całej listy przy otwartym module urlopów", async () => {
    routes(true, () => Promise.resolve({ data: { on: "2099-10-20", items: [away] } }));
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useMentionableUsers({ kind: "global" }, { withAbsences: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.absences.get(2)).toEqual(away));
    const absenceCalls = mocks.get.mock.calls.filter(([url]) => url === "/api/hr/leave/absence");
    expect(absenceCalls).toEqual([["/api/hr/leave/absence", { params: { user_ids: "1,2" } }]]);
    expect(result.current.data).toHaveLength(2);
  });

  it("moduł urlopów zamknięty: bez zapytania, pusta mapa", async () => {
    routes(false, () => Promise.resolve({ data: { on: "2099-10-20", items: [away] } }));
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useMentionableUsers({ kind: "global" }, { withAbsences: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() =>
      expect(mocks.get.mock.calls.some(([url]) => url === "/api/hr/config")).toBe(true),
    );
    expect(mocks.get.mock.calls.some(([url]) => url === "/api/hr/leave/absence")).toBe(false);
    expect(result.current.absences.size).toBe(0);
  });

  it("awaria zapytania o nieobecności nie psuje listy osób", async () => {
    routes(true, () => Promise.reject(new Error("500")));
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useMentionableUsers({ kind: "global" }, { withAbsences: true }),
      { wrapper },
    );
    await waitFor(() =>
      expect(mocks.get.mock.calls.some(([url]) => url === "/api/hr/leave/absence")).toBe(true),
    );
    expect(result.current.isSuccess).toBe(true);
    expect(result.current.absences.size).toBe(0);
  });

  it("bez withAbsences nie pyta ani o moduły, ani o nieobecności", async () => {
    routes(true, () => Promise.resolve({ data: { on: "2099-10-20", items: [away] } }));
    const { wrapper } = setup();
    const { result } = renderHook(() => useMentionableUsers({ kind: "global" }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mocks.get.mock.calls.map(([url]) => url)).toEqual(["/api/users/mentionable"]);
  });
});
