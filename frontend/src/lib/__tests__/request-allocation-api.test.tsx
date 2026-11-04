import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import {
  acceptProposals,
  categoryRecruitersQueryKey,
  decideProposal,
  removeBoardPerson,
  useCategoryRecruiters,
  useRequestBoard,
} from "@/lib/api/requestAllocation";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const apiGet = vi.mocked(api.get);
const apiPost = vi.mocked(api.post);
const apiDelete = vi.mocked(api.delete);

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("decyzja o propozycji automatu", () => {
  it("akceptacja i odrzucenie idą na trasę propozycji tej osoby", async () => {
    apiPost.mockResolvedValue({ data: { decision: "accept", assigned_user_id: 7 } } as never);

    await expect(decideProposal(12, 7, { decision: "accept" })).resolves.toEqual({
      decision: "accept",
      assigned_user_id: 7,
    });
    await decideProposal(12, 7, { decision: "reject" });

    expect(apiPost).toHaveBeenNthCalledWith(1, "/api/request-board/jobs/12/proposals/7", {
      decision: "accept",
    });
    expect(apiPost).toHaveBeenNthCalledWith(2, "/api/request-board/jobs/12/proposals/7", {
      decision: "reject",
    });
  });

  it("zmiana niesie osobę, która ma pracować zamiast proponowanej", async () => {
    apiPost.mockResolvedValue({ data: { decision: "replace", assigned_user_id: 9 } } as never);

    await decideProposal(12, 7, {
      decision: "replace",
      replacement_user_id: 9,
    });

    expect(apiPost).toHaveBeenCalledWith("/api/request-board/jobs/12/proposals/7", {
      decision: "replace",
      replacement_user_id: 9,
    });
  });

  it("409 (propozycja nieaktualna) wraca do wołającego jako błąd", async () => {
    const gone = { response: { status: 409, data: { detail: "Ta propozycja jest już nieaktualna." } } };
    apiPost.mockRejectedValue(gone as never);
    await expect(decideProposal(12, 7, { decision: "accept" })).rejects.toBe(gone);
  });
});

describe("acceptProposals", () => {
  it("wysyła same pary request–osoba i oddaje wynik każdej", async () => {
    apiPost.mockResolvedValue({
      data: {
        results: [
          { job_id: 12, user_id: 7, status: "accepted" },
          { job_id: 13, user_id: 8, status: "gone" },
        ],
      },
    } as never);
    // Wiersze z kolejki „Czeka na Ciebie” niosą więcej pól — do serwera idą tylko id.
    const rows = [
      { job_id: 12, user_id: 7, title: "Java Developer", user_name: "Anna Przykładowa" },
      { job_id: 13, user_id: 8, title: "Tester", user_name: "Bartek Testowy" },
    ];

    await expect(acceptProposals(rows)).resolves.toEqual([
      { job_id: 12, user_id: 7, status: "accepted" },
      { job_id: 13, user_id: 8, status: "gone" },
    ]);
    expect(apiPost).toHaveBeenCalledWith("/api/request-board/proposals/accept", {
      items: [
        { job_id: 12, user_id: 7 },
        { job_id: 13, user_id: 8 },
      ],
    });
  });

  it("pusta lista niczego nie wysyła", async () => {
    await expect(acceptProposals([])).resolves.toEqual([]);
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("odpowiedź bez wyników to pusta lista, nie wyjątek", async () => {
    apiPost.mockResolvedValue({ data: {} } as never);
    await expect(acceptProposals([{ job_id: 12, user_id: 7 }])).resolves.toEqual([]);
  });
});

describe("removeBoardPerson", () => {
  it("zdejmuje osobę trasą pulpitu", async () => {
    apiDelete.mockResolvedValue({ data: { removed: true } } as never);
    await removeBoardPerson(12, 7);
    expect(apiDelete).toHaveBeenCalledWith("/api/request-board/jobs/12/people/7");
  });
});

describe("useCategoryRecruiters", () => {
  it("pyta o osoby wskazanej kategorii", async () => {
    const people = [
      { user_id: 7, name: "Anna Przykładowa", email: "anna@example.com", role: "recruiter", is_primary: true, priority: 1 },
    ];
    apiGet.mockResolvedValue({ data: people } as never);

    const { result } = renderHook(() => useCategoryRecruiters(4), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.data).toEqual(people));
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith("/api/competence-categories/4/recruiters");
  });

  it("bez kategorii albo przy enabled=false nie wysyła zapytania", () => {
    const { result: none } = renderHook(() => useCategoryRecruiters(null), { wrapper: wrapper() });
    const { result: off } = renderHook(() => useCategoryRecruiters(4, { enabled: false }), {
      wrapper: wrapper(),
    });

    expect(none.current.fetchStatus).toBe("idle");
    expect(off.current.fetchStatus).toBe("idle");
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("klucz zaczyna się od stałego prefiksu i niesie id kategorii", () => {
    expect(categoryRecruitersQueryKey(4)).toEqual(["competence-category-recruiters", 4]);
  });
});

describe("useRequestBoard", () => {
  it("domyślnie pobiera pulpit, a enabled=false wstrzymuje zapytanie", async () => {
    apiGet.mockResolvedValue({ data: { mode: "off" } } as never);

    const { result: off } = renderHook(() => useRequestBoard({ enabled: false }), {
      wrapper: wrapper(),
    });
    expect(off.current.fetchStatus).toBe("idle");
    expect(apiGet).not.toHaveBeenCalled();

    const { result: on, unmount } = renderHook(() => useRequestBoard(), { wrapper: wrapper() });
    await waitFor(() => expect(on.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/api/request-board");
    // Pulpit odpytuje w tle — odmontowanie zatrzymuje interwał.
    unmount();
  });
});
