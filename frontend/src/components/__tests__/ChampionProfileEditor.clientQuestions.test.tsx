/**
 * Profil Championa × pytania klienta z debriefów: „Dodaj do …” zmienia tylko
 * SZKIC, a zwykłe „Zapisz” wysyła dopisane pytanie screeningowe i historyczne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { useAuthStore, type User } from "@/store/auth";

const getMock = vi.fn();
const putMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: {
      ...actual.championApi,
      get: (...args: unknown[]) => getMock(...args),
      put: (...args: unknown[]) => putMock(...args),
    },
  };
});
vi.mock("@/components/ChampionProfileSourcesPanel", () => ({
  ChampionProfileSourcesPanel: () => null,
}));
vi.mock("@/lib/api/interviewCycle", () => ({
  useClientQuestionPool: () => ({
    isPending: false,
    isError: false,
    isSuccess: true,
    data: [{ id: 5, text: "Jak skalujesz Kafkę?", created_at: null }],
    refetch: vi.fn(),
  }),
  useClientQuestionArchive: () => ({
    isPending: false,
    isError: false,
    isSuccess: false,
    data: undefined,
    refetch: vi.fn(),
  }),
}));

const dl = {
  id: 9,
  name: "Dorota DL",
  email: "dl@example.com",
  role: "delivery_lead",
  roles: ["delivery_lead"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} satisfies User;

beforeEach(() => {
  getMock.mockReset();
  putMock.mockReset();
  useAuthStore.setState({ user: dl, realUser: null, token: "token", hydrated: true });
});

describe("ChampionProfileEditor — pytania klienta z rozmów", () => {
  it("dopisuje pytanie do pytań screeningowych i historycznych, zapis je wysyła", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 3, champion_profile: { client: { historical_questions: "Stare pytanie" } } },
    });
    putMock.mockResolvedValue({ data: { job_id: 3, champion_profile: {} } });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ChampionProfileEditor jobId={3} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    const row = await screen.findByTestId("champion-client-question-5");
    expect(putMock).not.toHaveBeenCalled();
    await userEvent.click(within(row).getByRole("button", { name: "Dodaj do pytań screeningowych" }));
    // Sekcja 5 była zwinięta w grupie 2·4·5 — dopisane pytanie musi być widać.
    expect(await screen.findByTestId("screening-q-0")).toBeInTheDocument();
    expect(within(screen.getByTestId("screening-q-0")).getByDisplayValue("Jak skalujesz Kafkę?")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Dodaj do historycznych pytań" }));
    expect(within(row).getByText("już w profilu")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Dodaj do/ })).not.toBeInTheDocument();
    expect(putMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const [jobId, payload] = putMock.mock.calls[0];
    expect(jobId).toBe(3);
    expect(payload.screening_questions).toEqual([
      expect.objectContaining({ question: "Jak skalujesz Kafkę?", ideal_answer: "", deal_breaker: "" }),
    ]);
    expect(payload.client.historical_questions).toBe("Stare pytanie\nJak skalujesz Kafkę?");
  });
});
