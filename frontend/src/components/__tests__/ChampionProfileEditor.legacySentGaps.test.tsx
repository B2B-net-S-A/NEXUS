/**
 * Ostrzeżenie „nie ma nikt z wysłanych” przy starym profilu, bez wierszy
 * (zgłoszenie Testera z 03.11.2026, rekrutacja na starych polach: serwer zwracał
 * 2 wiersze, a edytor ich nie pokazywał, bo ostrzeżenie wisiało tylko na edytorze wierszy).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { useAuthStore, type User } from "@/store/auth";

const getMock = vi.fn();
const putMock = vi.fn();
const askMock = vi.fn();
const gapsMock = vi.fn();
const hintsMock = vi.fn();

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
vi.mock("@/lib/requirement-sent-gaps-api", () => ({
  useRequirementSentGaps: () => gapsMock(),
  useRequirementWordHints: () => hintsMock(),
}));
vi.mock("@/lib/requirement-rows-api", () => ({
  // Podpowiedź słownika (06.11.2026) ma własny test (DictionaryHintCallout).
  useDictionaryHints: () => ({ byWord: {}, canCurate: false }),
  dictionaryHintsKey: ["dictionary-hints"],
  useTalkItemReadings: () => null,
  useWordCounts: () => ({}),
  useRowCriticalInfo: () => ({ info: {}, isLoading: false, isError: false, retry: () => undefined }),
  useRowCounts: () => ({ perRow: {}, required: undefined, critical: undefined, failed: false }),
  fetchRowsFromLegacy: vi.fn(),
}));
vi.mock("@/components/ChampionProfileSourcesPanel", () => ({
  ChampionProfileSourcesPanel: () => null,
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: () => null,
}));

const admin = {
  id: 7,
  name: "Ola Przykładowa",
  email: "ola@example.com",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} satisfies User;

const LEGACY_PROFILE = {
  stack: {
    must: [{ name: "Java" }, { name: "Trunk-based" }, { name: "Kafka lub RabbitMQ" }],
    nice: [{ name: "Selenium" }],
    critical: ["Java"],
    notes: "",
  },
  search: { requirements: [["Java"], ["Trunk-based"], ["Kafka", "RabbitMQ"]], exclude: [] },
};

function renderLegacy(canEdit = true) {
  getMock.mockResolvedValue({ data: { job_id: 91, champion_profile: LEGACY_PROFILE } });
  putMock.mockResolvedValue({ data: { job_id: 91, champion_profile: LEGACY_PROFILE } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChampionProfileEditor jobId={91} canEdit={canEdit} clientId={null} />
    </QueryClientProvider>,
  );
}

const lastPut = () => putMock.mock.calls[0][1] as Record<string, any>;

beforeEach(() => {
  getMock.mockReset();
  putMock.mockReset();
  askMock.mockReset();
  gapsMock.mockReturnValue({
    data: {
      sent: 20,
      rows: [
        { label: "trunk-based", words: ["trunk-based"] },
        { label: "kafka", words: ["kafka", "rabbitmq"] },
        { label: "spoza listy", words: ["spoza listy"] },
      ],
      can_ask_hints: true,
    },
  });
  hintsMock.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    mutate: askMock,
  });
  useAuthStore.setState({ user: admin, realUser: null, token: "token", hydrated: true });
});

describe("stary profil bez wierszy — wiersze bez nikogo z wysłanych", () => {
  it("pokazuje ostrzeżenie przy pozycjach „Musi mieć”, także tej z wariantem", async () => {
    renderLegacy();
    const notes = await screen.findAllByTestId("requirement-row-sent-gap");
    expect(notes.map((note) => note.querySelector("strong")?.textContent)).toEqual([
      "„Trunk-based” nie ma nikt z 20 wysłanych.",
      "„Kafka lub RabbitMQ” nie ma nikt z 20 wysłanych.",
    ]);
    await userEvent.click(within(notes[0]).getByRole("button", { name: "Podpowiedz słowa" }));
    expect(askMock).toHaveBeenCalledTimes(1);
  });

  it("bez prawa edycji ostrzeżenia nie ma", async () => {
    renderLegacy(false);
    await screen.findAllByText(/Musi mieć/);
    expect(screen.queryByTestId("requirement-row-sent-gap")).toBeNull();
  });

  it("„Do rozmowy” zdejmuje pozycję z obu list i dopisuje ją do rozmowy", async () => {
    renderLegacy();
    const [first] = await screen.findAllByTestId("requirement-row-sent-gap");
    await userEvent.click(within(first).getByRole("button", { name: "Do rozmowy" }));
    expect(screen.getAllByTestId("requirement-row-sent-gap")).toHaveLength(1);

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const saved = lastPut();
    expect(saved.stack.must.map((item: { name: string }) => item.name)).toEqual([
      "Java",
      "Kafka lub RabbitMQ",
    ]);
    expect(saved.search.requirements).toEqual([["Java"], ["Kafka", "RabbitMQ"]]);
    expect(saved.experience.skills.map((item: { name: string }) => item.name)).toEqual(["Trunk-based"]);
  });

  it("słowo z podpowiedzi dochodzi jako wariant w obu listach, a ostrzeżenie czeka na zapis", async () => {
    hintsMock.mockReturnValue({
      data: {
        available: true,
        rows: [{ label: "trunk-based", words: [{ word: "GitFlow", hits: 5 }] }],
      },
      isPending: false,
      isError: false,
      error: null,
      mutate: askMock,
    });
    renderLegacy();
    const [first] = await screen.findAllByTestId("requirement-row-sent-gap");
    await userEvent.click(within(first).getByRole("button", { name: /\+ lub GitFlow/ }));
    expect(screen.getAllByTestId("requirement-row-sent-gap")).toHaveLength(1);

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const saved = lastPut();
    expect(saved.stack.must.map((item: { name: string }) => item.name)).toEqual([
      "Java",
      "Trunk-based lub GitFlow",
      "Kafka lub RabbitMQ",
    ]);
    expect(saved.search.requirements).toEqual([
      ["Java"],
      ["Trunk-based", "GitFlow"],
      ["Kafka", "RabbitMQ"],
    ]);
  });

  it("„Zostaw” chowa samo ostrzeżenie i niczego nie zmienia", async () => {
    renderLegacy();
    const [first] = await screen.findAllByTestId("requirement-row-sent-gap");
    await userEvent.click(within(first).getByRole("button", { name: "Zostaw" }));
    const left = screen.getAllByTestId("requirement-row-sent-gap");
    expect(left).toHaveLength(1);
    expect(left[0]).toHaveTextContent("Kafka lub RabbitMQ");
    expect(screen.getByText("Musi mieć · 3")).toBeInTheDocument();
  });
});
