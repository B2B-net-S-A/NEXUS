/**
 * Audyt 48 h (13.10.2026), pkt 20–21: „Uprość do słów kluczowych”.
 *
 * Zdania z „mile widziane” szły do „Rekruter sprawdza w rozmowie” jako „Musi”,
 * a zapis zostawiał z listy 20 zdań i resztę gubił bez ostrzeżenia. Teraz
 * poziom idzie za listą, a nadmiar trafia do opisu wymagań (`stack.notes`).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { useAuthStore, type User } from "@/store/auth";

const getMock = vi.fn();
const putMock = vi.fn();
const legacyRowsMock = vi.fn();

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

vi.mock("@/components/v2/pages/candidate-list-query", () => ({
  fetchCandidateListPage: () => Promise.resolve({ items: [], total: 0 }),
}));

vi.mock("@/lib/requirement-rows-api", () => ({
  // Podpowiedź „To słowo do szukania?” ma własny test (TalkSearchWordHints).
  useTalkItemReadings: () => null,
  useWordCounts: () => ({}),
  useRowCriticalInfo: (rows: { key: string; words: string[]; level: string }[]) => ({
    info: Object.fromEntries(
      rows
        .filter((row) => row.level !== "nice")
        .map((row) => [row.key, { label: row.words[0], eligible: true, suggested: false }]),
    ),
    isLoading: false,
    isError: false,
    retry: () => undefined,
  }),
  useRowCounts: () => ({ perRow: {}, required: undefined, critical: undefined, failed: false }),
  fetchRowsFromLegacy: (...args: unknown[]) => legacyRowsMock(...args),
}));

vi.mock("@/components/ChampionProfileSourcesPanel", () => ({
  ChampionProfileSourcesPanel: () => null,
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: () => null,
}));

const admin = {
  id: 1,
  name: "Anna Testowa",
  email: "anna@example.com",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} as unknown as User;

beforeEach(() => {
  getMock.mockReset();
  putMock.mockReset();
  legacyRowsMock.mockReset();
  useAuthStore.setState({ user: admin, realUser: null, token: "token", hydrated: true });
});

function renderAdmin(jobId: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChampionProfileEditor jobId={jobId} canEdit clientId={null} />
    </QueryClientProvider>,
  );
}

describe("ChampionProfileEditor — „Uprość do słów kluczowych” nic nie gubi", () => {
  it("poziom z „mile widziane” zostaje, a zdania ponad 20 idą do opisu wymagań", async () => {
    const sentences = Array.from({ length: 24 }, (_, i) => `Zdanie klienta numer ${i}`);
    getMock.mockResolvedValue({
      data: {
        job_id: 31,
        champion_profile: {
          stack: {
            must: [{ name: "Java" }, ...sentences.map((name) => ({ name }))],
            nice: [{ name: "doświadczenie w sektorze bankowym" }],
            notes: "Projekt dla banku.",
          },
        },
      },
    });
    legacyRowsMock.mockResolvedValue({
      rows: [{ words: ["Java"], level: "must" }],
      descriptive: [...sentences, "doświadczenie w sektorze bankowym"],
      descriptive_nice: ["doświadczenie w sektorze bankowym"],
      no_critical: false,
    });
    putMock.mockResolvedValue({ data: { job_id: 31, champion_profile: {} } });
    renderAdmin(31);
    await userEvent.click(await screen.findByTestId("champion-simplify-requirements"));
    expect(await screen.findByTestId("champion-requirement-rows")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      stack: { notes: string };
      experience: { skills: { name: string; level: string }[] };
    };
    expect(payload.experience.skills).toHaveLength(20);
    expect(payload.experience.skills.map((i) => i.name)).toEqual(sentences.slice(0, 20));
    // Nic nie znika: cztery zdania i to z „mile widziane” są w opisie wymagań.
    expect(payload.stack.notes).toBe(
      "Projekt dla banku.\nDo sprawdzenia w rozmowie: Zdanie klienta numer 20; Zdanie klienta numer 21; Zdanie klienta numer 22; Zdanie klienta numer 23; doświadczenie w sektorze bankowym.",
    );
  });

  it("zdanie z „mile widziane” idzie do rozmowy jako „Mile”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 32,
        champion_profile: {
          stack: {
            must: [{ name: "Java 17+" }],
            nice: [{ name: "doświadczenie w sektorze bankowym" }],
            notes: "",
          },
        },
      },
    });
    legacyRowsMock.mockResolvedValue({
      rows: [{ words: ["Java"], level: "must" }],
      descriptive: ["Java 17+", "doświadczenie w sektorze bankowym"],
      descriptive_nice: ["doświadczenie w sektorze bankowym"],
      no_critical: false,
    });
    putMock.mockResolvedValue({ data: { job_id: 32, champion_profile: {} } });
    renderAdmin(32);
    await userEvent.click(await screen.findByTestId("champion-simplify-requirements"));
    await screen.findByTestId("champion-requirement-rows");
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      stack: { notes: string };
      experience: { skills: { name: string; level: string }[] };
    };
    expect(payload.experience.skills.map((i) => [i.name, i.level])).toEqual([
      ["Java 17+", "must"],
      ["doświadczenie w sektorze bankowym", "nice"],
    ]);
    expect(payload.stack.notes).toBe("");
  });
});
