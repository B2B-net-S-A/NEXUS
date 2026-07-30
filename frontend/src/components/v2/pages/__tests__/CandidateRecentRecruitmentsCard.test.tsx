import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateRecentRecruitmentsCard } from "../CandidateRecentRecruitmentsCard";
import { candidateFactsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  candidateFactsApi: {
    getRecentRecruitments: vi.fn(),
  },
}));

const mockedApi = vi.mocked(candidateFactsApi);
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

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function cardUi(client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <CandidateRecentRecruitmentsCard candidateId={7} />
    </QueryClientProvider>
  );
}

function renderCard() {
  const client = createQueryClient();
  return render(
    cardUi(client),
  );
}

const recruitment = {
  job_id: 42,
  job_title: "Senior Java Developer",
  client_id: 9,
  client_name: "Acme",
  latest_stage_id: 88,
  stage: "client_interview",
  stage_label: "Rozmowa z klientem",
  last_activity_at: "2026-07-29T10:00:00Z",
};

describe("CandidateRecentRecruitmentsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user = {
      id: 101,
      role: "recruiter",
      roles: ["recruiter"],
    };
  });

  it("renders a safe internal link and no financial or note content", async () => {
    mockedApi.getRecentRecruitments.mockResolvedValue({
      candidate_id: 7,
      items: [recruitment],
    });

    renderCard();

    const link = await screen.findByRole("link", {
      name: /Otwórz rekrutację Senior Java Developer/,
    });
    expect(link).toHaveAttribute(
      "href",
      "/candidates/7?tab=recruitments&focusJobId=42",
    );
    expect(link.classList.contains("min-h-11")).toBe(true);
    expect(screen.getByText("Rozmowa z klientem")).toBeInTheDocument();
    expect(screen.queryByText(/PLN|stawka|notatka/i)).not.toBeInTheDocument();
    expect(mockedApi.getRecentRecruitments).toHaveBeenCalledWith(7, 5);
  });

  it("renders a distinct empty state", async () => {
    mockedApi.getRecentRecruitments.mockResolvedValue({
      candidate_id: 7,
      items: [],
    });

    renderCard();

    expect(
      await screen.findByText(/nie ma widocznej historii rekrutacji/i),
    ).toBeInTheDocument();
  });

  it("does not create a link for an invalid recruitment identifier", async () => {
    mockedApi.getRecentRecruitments.mockResolvedValue({
      candidate_id: 7,
      items: [{ ...recruitment, job_id: -1 }],
    });

    renderCard();

    expect(
      await screen.findByText("Senior Java Developer"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("uses a deterministic fallback title in the link's accessible name", async () => {
    mockedApi.getRecentRecruitments.mockResolvedValue({
      candidate_id: 7,
      items: [{ ...recruitment, job_title: "" }],
    });

    renderCard();

    expect(
      await screen.findByRole("link", {
        name: "Otwórz rekrutację Rekrutacja #42",
      }),
    ).toBeInTheDocument();
  });

  it("renders a forbidden state instead of pretending the list is empty", async () => {
    mockedApi.getRecentRecruitments.mockRejectedValue({
      response: { status: 403 },
    });

    renderCard();

    expect(
      await screen.findByText(/Nie masz dostępu do rekrutacji/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/nie ma widocznej historii/i),
    ).not.toBeInTheDocument();
  });

  it("renders at most five recruitments even if the response is oversized", async () => {
    mockedApi.getRecentRecruitments.mockResolvedValue({
      candidate_id: 7,
      items: Array.from({ length: 6 }, (_, index) => ({
        ...recruitment,
        job_id: 100 + index,
        latest_stage_id: 200 + index,
        job_title: `Rekrutacja ${index + 1}`,
      })),
    });

    renderCard();

    expect(await screen.findAllByRole("link")).toHaveLength(5);
    expect(screen.queryByText("Rekrutacja 6")).not.toBeInTheDocument();
  });

  it("keeps the retry touch target at least 44px", async () => {
    mockedApi.getRecentRecruitments.mockRejectedValue({
      response: { status: 500 },
    });

    renderCard();

    const retry = await screen.findByRole("button", {
      name: "Spróbuj ponownie",
    });
    expect(retry.classList.contains("min-h-11")).toBe(true);
    expect(retry.classList.contains("min-w-11")).toBe(true);
  });

  it("drops cached rows when the same viewer's role scope changes", async () => {
    let resolveSecond:
      | ((value: {
          candidate_id: number;
          items: Array<typeof recruitment>;
        }) => void)
      | undefined;
    const secondResponse = new Promise<{
      candidate_id: number;
      items: Array<typeof recruitment>;
    }>((resolve) => {
      resolveSecond = resolve;
    });
    mockedApi.getRecentRecruitments
      .mockResolvedValueOnce({
        candidate_id: 7,
        items: [{ ...recruitment, job_title: "Tylko stary scope" }],
      })
      .mockReturnValueOnce(secondResponse);
    const queryClient = createQueryClient();
    const view = render(cardUi(queryClient));

    expect(await screen.findByText("Tylko stary scope")).toBeInTheDocument();

    auth.user = {
      id: 101,
      role: "recruiter",
      roles: ["recruiter", "delivery_lead"],
    };
    view.rerender(cardUi(queryClient));

    expect(screen.queryByText("Tylko stary scope")).not.toBeInTheDocument();
    expect(screen.getByText("Ładowanie rekrutacji…")).toBeInTheDocument();

    resolveSecond?.({
      candidate_id: 7,
      items: [{ ...recruitment, job_title: "Nowy scope" }],
    });
    expect(await screen.findByText("Nowy scope")).toBeInTheDocument();
  });
});
