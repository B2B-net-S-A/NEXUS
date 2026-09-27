/**
 * „Meetingi bez powiązania” w Źródłach AI Championa (UAT M03-B13 / M04-B04):
 * lista brała każdą notatkę „meeting” — także rozmowy z kandydatami innych
 * klientów z importu Traffita, z surowym HTML-em w tytule — i oferowała
 * „Powiąż + AI” na tej rekrutacji.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { get, post: vi.fn() },
  championSuggestionsApi: {
    list: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
}));
vi.mock("../ChampionHistoricalMatchesPanel", () => ({
  ChampionHistoricalMatchesPanel: () => null,
}));
vi.mock("../ChampionProfileSuggestionReview", () => ({
  ChampionProfileSuggestionReview: () => null,
}));

import { ChampionProfileSourcesPanel, noteTitle } from "../ChampionProfileSourcesPanel";
import { EMPTY_CHAMPION_PROFILE } from "@/lib/api";

function note(id: number, content: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    note_type: "meeting",
    content,
    job_id: null,
    candidate_id: null,
    created_at: "2026-09-01T10:00:00Z",
    ...extra,
  };
}

beforeEach(() => {
  get.mockReset();
});

describe("noteTitle", () => {
  it("zdejmuje znaczniki HTML i dekoduje encje", () => {
    expect(noteTitle("<p>Spotkanie&nbsp;z&nbsp;klientem &oacute;smego dnia</p><p>reszta</p>")).toBe(
      "Spotkanie z klientem ósmego dnia",
    );
  });

  it("zostawia tytuł markdown z Fireflies", () => {
    expect(noteTitle("# Briefing roli\nTranskrypt…")).toBe("Briefing roli");
  });
});

describe("ChampionProfileSourcesPanel — meetingi bez powiązania", () => {
  it("pyta serwer wyłącznie o spotkania bez rekrutacji i bez kandydata, i nie pokazuje notatek kandydatów", async () => {
    get.mockImplementation(async (url: string) => {
      if (url.includes("unattached=true")) {
        return {
          data: {
            items: [
              note(1, "# Briefing z klientem"),
              // Obrona w głąb: nawet gdyby serwer zwrócił notatkę kandydata,
              // panel nie może oferować jej do powiązania.
              note(2, "<p>Rozmowa z kandydatem</p>", { candidate_id: 77 }),
            ],
            total: 2,
          },
        };
      }
      return { data: { items: [], total: 0 } };
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ChampionProfileSourcesPanel jobId={5} currentProfile={EMPTY_CHAMPION_PROFILE} clientId={3} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Briefing z klientem")).toBeInTheDocument();
    expect(screen.queryByText("Rozmowa z kandydatem")).toBeNull();
    const urls = get.mock.calls.map((c) => String(c[0]));
    expect(urls).toContain("/api/notes?note_type=meeting&unattached=true&limit=10");
    expect(urls.some((u) => u === "/api/notes?note_type=meeting")).toBe(false);
  });
});

// Runda 8 (R8-N14-5): pusta lista z `.map()` jest truthy, więc sekcje nigdy
// nie pokazywały pustego stanu, a awaria zapytania dawała pustą sekcję.
describe("ChampionProfileSourcesPanel — pusty stan i awaria", () => {
  function renderPanel() {
    return render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ChampionProfileSourcesPanel jobId={5} currentProfile={EMPTY_CHAMPION_PROFILE} clientId={3} />
      </QueryClientProvider>,
    );
  }

  it("puste listy → komunikaty pustego stanu we wszystkich trzech sekcjach", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });
    renderPanel();
    expect(await screen.findByText("Brak pending draftów.")).toBeInTheDocument();
    expect(await screen.findByText("Żadne meetingi nie są powiązane z tą rekrutacją.")).toBeInTheDocument();
    expect(await screen.findByText("Wszystkie meetingi zostały już powiązane.")).toBeInTheDocument();
  });

  it("awaria zapytania → komunikat błędu z „Ponów”, nie pusty stan", async () => {
    let calls = 0;
    get.mockImplementation(async (url: string) => {
      if (url === "/api/notes?job_id=5") {
        calls += 1;
        if (calls === 1) throw new Error("boom");
        return { data: { items: [note(9, "# Briefing roli", { job_id: 5 })], total: 1 } };
      }
      return { data: { items: [], total: 0 } };
    });
    renderPanel();
    const retry = await screen.findByRole("button", { name: "Ponów" });
    expect(screen.getByText(/Nie udało się wczytać/)).toBeInTheDocument();
    expect(screen.queryByText("Żadne meetingi nie są powiązane z tą rekrutacją.")).toBeNull();
    await userEvent.click(retry);
    expect(await screen.findByText("Briefing roli")).toBeInTheDocument();
  });
});
