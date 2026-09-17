import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { useCandidateHistoryQuery } from "../candidate-history-query";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
  },
}));

const auth = vi.hoisted(() => ({
  user: {
    id: 101,
    role: "recruiter",
    roles: ["recruiter"],
  } as { id: number; role: string; roles: string[] },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: { user: typeof auth.user }) => unknown,
  ) => selector({ user: auth.user }),
}));

const mockedGet = vi.mocked(api.get);

function HistoryProbe() {
  const query = useCandidateHistoryQuery(7);
  const data = query.visibleData;
  const jobs = (
    Array.isArray(data)
      ? data
      : ((data?.jobs ?? []) as Array<{ job_title?: string }>)
  ) as Array<{ job_title?: string }>;

  if (query.isFetching) return <p>Ładowanie historii…</p>;
  return <p>{jobs[0]?.job_title ?? "Brak historii"}</p>;
}

function RefreshProbe() {
  const query = useCandidateHistoryQuery(7);
  const data = query.visibleData;
  const jobs = (
    Array.isArray(data) ? data : ((data?.jobs ?? []) as Array<{ job_title?: string }>)
  ) as Array<{ job_title?: string }>;
  if (query.isPending) return <p>Ładowanie historii…</p>;
  return (
    <div>
      <p>{jobs[0]?.job_title ?? "Brak historii"}</p>
      {query.isRefreshing ? <p>Odświeżam…</p> : null}
    </div>
  );
}

function historyUi(queryClient: QueryClient, mountKey: string) {
  return (
    <QueryClientProvider client={queryClient}>
      <HistoryProbe key={mountKey} />
    </QueryClientProvider>
  );
}

describe("useCandidateHistoryQuery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user = {
      id: 101,
      role: "recruiter",
      roles: ["recruiter"],
    };
  });

  it("never exposes cached history across membership revalidation or a viewer switch", async () => {
    let resolveMembership:
      | ((value: { data: { jobs: Array<{ job_title: string }> } }) => void)
      | undefined;
    let resolveViewer:
      | ((value: { data: { jobs: Array<{ job_title: string }> } }) => void)
      | undefined;
    const membershipResponse = new Promise<{
      data: { jobs: Array<{ job_title: string }> };
    }>((resolve) => {
      resolveMembership = resolve;
    });
    const viewerResponse = new Promise<{
      data: { jobs: Array<{ job_title: string }> };
    }>((resolve) => {
      resolveViewer = resolve;
    });

    mockedGet
      .mockResolvedValueOnce({
        data: { jobs: [{ job_title: "Widoczne w starym membershipie" }] },
      })
      .mockReturnValueOnce(membershipResponse)
      .mockReturnValueOnce(viewerResponse);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const view = render(historyUi(queryClient, "membership-1"));

    expect(
      await screen.findByText("Widoczne w starym membershipie"),
    ).toBeInTheDocument();

    // Remount represents returning to the profile after backend membership
    // changed. staleTime=0 + refetchOnMount=always must hide the cached rows.
    view.rerender(historyUi(queryClient, "membership-2"));
    expect(
      screen.queryByText("Widoczne w starym membershipie"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ładowanie historii…")).toBeInTheDocument();

    resolveMembership?.({
      data: { jobs: [{ job_title: "Widoczne po zmianie membershipu" }] },
    });
    expect(
      await screen.findByText("Widoczne po zmianie membershipu"),
    ).toBeInTheDocument();

    auth.user = {
      id: 202,
      role: "sourcer",
      roles: ["sourcer"],
    };
    view.rerender(historyUi(queryClient, "viewer-2"));

    expect(
      screen.queryByText("Widoczne po zmianie membershipu"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ładowanie historii…")).toBeInTheDocument();

    resolveViewer?.({
      data: { jobs: [{ job_title: "Historia drugiego użytkownika" }] },
    });
    expect(
      await screen.findByText("Historia drugiego użytkownika"),
    ).toBeInTheDocument();
  });

  it("keeps the same viewer's history visible while it revalidates (window focus)", async () => {
    let resolveRefresh:
      | ((value: { data: { jobs: Array<{ job_title: string }> } }) => void)
      | undefined;
    mockedGet
      .mockResolvedValueOnce({ data: { jobs: [{ job_title: "Rekrutacja A" }] } })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveRefresh = resolve;
        }),
      );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RefreshProbe />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Rekrutacja A")).toBeInTheDocument();

    await act(async () => {
      void queryClient.invalidateQueries();
    });
    // Brak migotania: poprzednie dane zostają, z podpowiedzią odświeżania —
    // nie „Brak historii” (UAT: znikająca zakładka Rekrutacje).
    expect(await screen.findByText("Odświeżam…")).toBeInTheDocument();
    expect(screen.getByText("Rekrutacja A")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Brak historii")).not.toBeInTheDocument();

    resolveRefresh?.({ data: { jobs: [{ job_title: "Rekrutacja B" }] } });
    expect(await screen.findByText("Rekrutacja B")).toBeInTheDocument();
    expect(screen.queryByText("Odświeżam…")).not.toBeInTheDocument();
  });

  it("never shows the previous viewer's history after a scope switch in the same instance", async () => {
    let resolveSecond:
      | ((value: { data: { jobs: Array<{ job_title: string }> } }) => void)
      | undefined;
    mockedGet
      .mockResolvedValueOnce({ data: { jobs: [{ job_title: "Tylko rekruter" }] } })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
      );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const ui = (
      <QueryClientProvider client={queryClient}>
        <RefreshProbe />
      </QueryClientProvider>
    );
    const view = render(ui);
    expect(await screen.findByText("Tylko rekruter")).toBeInTheDocument();

    auth.user = { id: 303, role: "sourcer", roles: ["sourcer"] };
    view.rerender(
      <QueryClientProvider client={queryClient}>
        <RefreshProbe />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("Tylko rekruter")).not.toBeInTheDocument();
    expect(screen.getByText("Ładowanie historii…")).toBeInTheDocument();

    resolveSecond?.({ data: { jobs: [{ job_title: "Zakres sourcera" }] } });
    expect(await screen.findByText("Zakres sourcera")).toBeInTheDocument();
  });
});
