import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getReqs: vi.fn(),
  list: vi.fn(),
  mounts: 0,
  getChampion: vi.fn(),
  classify: vi.fn(),
}));

vi.mock("@/lib/keyword-suggest", () => ({
  classifyKeywords: (...a: unknown[]) => mocks.classify(...a),
}));

vi.mock("@/lib/api", () => ({
  championApi: { get: (...a: unknown[]) => mocks.getChampion(...a) },
}));

vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: (...a: unknown[]) => mocks.getReqs(...a) },
  // Uproszczone lustro: etykiety pozycji `must`.
  requirementLabels: (data: { must: string[] }) => data.must,
}));
vi.mock("@/components/v2/pages/CandidatesListV2", () => ({
  CandidatesListV2: function MockList(props: unknown) {
    mocks.list(props);
    useEffect(() => {
      mocks.mounts += 1;
    }, []);
    return <div data-testid="candidates-list" />;
  },
}));

import { jobListFilters, ManualSearchPanel } from "@/components/v2/recruitment/ManualSearchPanel";
import type { CandidatesListEmbed } from "@/components/v2/pages/CandidatesListV2";
import { effectiveSort } from "@/lib/url-filters";

const JOB = {
  id: 7,
  title: "PKO BP: Analityk Systemowy (ZOB-1725)",
  must_skills: ["Java"],
  location: "Warszawa",
  remote_policy: "hybrid",
  competence_category_id: 5,
};

function renderPanel(props: Partial<React.ComponentProps<typeof ManualSearchPanel>> = {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ManualSearchPanel jobId={7} job={JOB} {...props} />
    </QueryClientProvider>,
  );
}

function lastEmbed(): CandidatesListEmbed {
  const props = mocks.list.mock.calls.at(-1)?.[0] as { embed: CandidatesListEmbed };
  return props.embed;
}

describe("ManualSearchPanel — lista Kandydatów osadzona w rekrutacji", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getChampion.mockResolvedValue({ data: { champion_profile: {} } });
    // Technologie ze słownika: „Java”, „Kafka RabbitMQ”, „Python”.
    mocks.classify.mockImplementation(async (text: string) => ({
      skills: [],
      as_requirements: ["Java", "Kafka RabbitMQ", "Python"].includes(text),
    }));
  });

  it("montuje listę dopiero PO odczycie wymagań i zasila ją rekrutacją", async () => {
    mocks.getReqs.mockResolvedValue({ must: ["SQL", "UML"] });
    const onBulkAdded = vi.fn();
    renderPanel({ onBulkAdded, readOnly: true });
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
    expect(screen.queryByTestId("candidates-list")).not.toBeInTheDocument();

    await screen.findByTestId("candidates-list");
    expect(mocks.getReqs).toHaveBeenCalledWith(7);
    const embed = lastEmbed();
    expect(embed).toMatchObject({
      jobId: 7,
      jobTitle: JOB.title,
      readOnly: true,
      onAdded: onBulkAdded,
    });
    // Must-have z kontraktu rekrutacji podnoszą w kolejności (jak dotąd),
    // miasto i kategoria z rekrutacji. Tytuł NIE idzie jako tekst po znaczeniu
    // (limit 200 osób) — bez wymagań w Championie lista pokazuje całą bazę
    // według dopasowania do rekrutacji (decyzja 25.09.2026).
    expect(embed.initialFilters.skillsPreferred).toEqual(["SQL", "UML"]);
    expect(embed.initialFilters.q).toBe("");
    expect(embed.initialFilters.textMode).toBe("auto");
    expect(
      effectiveSort({ ...embed.initialFilters, recruitmentIds: [7], recruitmentMatch: "not_assigned" }),
    ).toBe("match");
    // Miasto i kategoria rekrutacji tylko podnoszą — jako filtry wycinały
    // 55,6% osób wybranych potem przez zespół (audyt 26.09.2026).
    expect(embed.initialFilters.location).toBe("");
    expect(embed.initialFilters.competenceCategoryIds).toEqual([]);
    expect(embed.initialFilters.locationPreferred).toEqual(["Warszawa"]);
    expect(embed.initialFilters.competenceCategoryPreferred).toEqual([5]);
    expect(embed.initialFilters.status).toEqual(["active", "passive"]);
  });

  it("błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca do kolumn rekrutacji", async () => {
    mocks.getReqs.mockRejectedValue(new Error("boom"));
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(lastEmbed().initialFilters.skillsPreferred).toEqual(["Java"]);
    expect(lastEmbed().readOnly).toBe(false);
  });

  it("wymagania z Championa: obowiązkowe tylko krytyczne z serwera, z wariantami (D1/W1/W4)", async () => {
    mocks.getReqs.mockResolvedValue({ must: ["SQL"] });
    mocks.getChampion.mockResolvedValue({
      data: {
        champion_profile: {
          search: {
            requirements: [["Java"], ["Kafka", "RabbitMQ"], [], ["bankowość"], ["bankow*"]],
            exclude: ["junior"],
          },
        },
        critical_resolution: {
          stored: ["Kafka lub RabbitMQ"],
          decided: true,
          effective: ["Kafka lub RabbitMQ"],
          source: "dl",
          suggested: [],
          search_rows: [["Kafka", "Apache Kafka", "RabbitMQ"]],
        },
      },
    });
    renderPanel();
    await screen.findByTestId("candidates-list");
    const embed = lastEmbed();
    expect(mocks.getChampion).toHaveBeenCalledWith(7);
    // Wiersz z krytyczną dostaje warianty z serwera; reszta tylko podnosi.
    expect(embed.initialFilters.qAny).toEqual([["Kafka", "RabbitMQ", "Apache Kafka"]]);
    expect(embed.initialFilters.qPreferred).toEqual([["Java"], ["bankowość"], ["bankow*"]]);
    expect(embed.initialFilters.qNone).toEqual(["junior"]);
    // Klasyfikacja „technologia / nie” nie decyduje już o obowiązkowości.
    expect(mocks.classify).not.toHaveBeenCalled();
    expect(embed.initialFilters.q).toBe("");
    // D2: przy wierszach must-have nie liczą się drugi raz w „Umiejętnościach”.
    expect(embed.initialFilters.skillsPreferred).toEqual([]);
    expect(embed.keywordsNote).toMatch(/wybrane przez Delivery Leada: Kafka lub RabbitMQ/);
  });

  it("podpowiedź z historii — ekran mówi, że DL nie wybrał krytycznych (W2)", async () => {
    mocks.getReqs.mockResolvedValue({ must: [] });
    mocks.getChampion.mockResolvedValue({
      data: {
        champion_profile: { search: { requirements: [["Java"], ["Spring"]] } },
        critical_resolution: {
          stored: null,
          decided: false,
          effective: ["Java"],
          source: "suggested",
          suggested: ["Java"],
          search_rows: [["Java", "j2ee"]],
        },
      },
    });
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(lastEmbed().initialFilters.qAny).toEqual([["Java", "j2ee"]]);
    expect(lastEmbed().initialFilters.qPreferred).toEqual([["Spring"]]);
    expect(lastEmbed().keywordsNote).toMatch(/podpowiedzi z historii/);
  });

  it("„Brak krytycznych” — nic nie wycina, ekran mówi to wprost", async () => {
    mocks.getReqs.mockResolvedValue({ must: [] });
    mocks.getChampion.mockResolvedValue({
      data: {
        champion_profile: { search: { requirements: [["Java"]] } },
        critical_resolution: {
          stored: [],
          decided: true,
          effective: [],
          source: "none",
          suggested: ["Java"],
          search_rows: [],
        },
      },
    });
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(lastEmbed().initialFilters.qAny).toEqual([]);
    expect(lastEmbed().initialFilters.qPreferred).toEqual([["Java"]]);
    expect(lastEmbed().keywordsNote).toMatch(/nic nie jest obowiązkowe/);
  });

  it("powrót do karty po >10 min nie przemontowuje listy (R8-N14-7)", async () => {
    mocks.mounts = 0;
    mocks.getReqs.mockResolvedValue({ must: [] });
    mocks.getChampion.mockResolvedValue({
      data: { champion_profile: { search: { requirements: [["bankowość"]] } } },
    });
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(mocks.mounts).toBe(1);
    const realNow = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(realNow + 11 * 60 * 1000);
    try {
      await act(async () => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
        await new Promise((r) => setTimeout(r, 50));
      });
    } finally {
      clock.mockRestore();
      focusManager.setFocused(undefined);
    }
    expect(mocks.mounts).toBe(1);
  });

  it("bez wymagań w Championie — start jak dotąd, bez odniesienia do Championa", async () => {
    mocks.getReqs.mockResolvedValue({ must: [] });
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(lastEmbed().initialFilters.qAny).toEqual([]);
    expect(lastEmbed().keywordsNote).toBeUndefined();
  });

  it("błąd odczytu Championa — wiersze z profilu w odczycie rekrutacji", async () => {
    mocks.getReqs.mockResolvedValue({ must: [] });
    mocks.getChampion.mockRejectedValue(new Error("boom"));
    renderPanel({
      job: { ...JOB, champion_profile: { search: { requirements: [["Python"]] } } },
    });
    await screen.findByTestId("candidates-list");
    // Bez odpowiedzi serwera nie wiemy, co krytyczne — nic nie wycina.
    expect(lastEmbed().initialFilters.qAny).toEqual([]);
    expect(lastEmbed().initialFilters.qPreferred).toEqual([["Python"]]);
    expect(lastEmbed().keywordsNote).toMatch(/Nie udało się wczytać/);
  });

  it("wiersze „mile widziane” ze stack.rows tylko podnoszą (W6)", () => {
    const champion_profile = {
      stack: {
        rows: [
          { words: ["Java"], level: "must" },
          { words: ["Kafka", "RabbitMQ"], level: "must" },
          { words: ["Grafana"], level: "nice" },
        ],
        critical: ["Kafka lub RabbitMQ"],
      },
      search: { requirements: [["Java"], ["Kafka", "RabbitMQ"]] },
    };
    const filters = jobListFilters({ ...JOB, champion_profile }, null, {
      stored: ["Kafka lub RabbitMQ"],
      decided: true,
      effective: ["Kafka lub RabbitMQ"],
      source: "dl",
      suggested: [],
    });
    // Odpowiedź bez `search_rows` (sprzed zmiany) — opcje etykiety.
    expect(filters.qAny).toEqual([["Kafka", "RabbitMQ"]]);
    expect(filters.qPreferred).toEqual([["Java"], ["Grafana"]]);
  });

  it("krytyczna spoza wierszy (profil bez stack.rows) dochodzi jako nowy wiersz (W3)", () => {
    const champion_profile = { search: { requirements: [["bankowość"]] } };
    const filters = jobListFilters({ ...JOB, champion_profile }, null, {
      stored: null,
      decided: false,
      effective: ["Java"],
      source: "suggested",
      suggested: ["Java"],
      search_rows: [["Java"]],
    });
    expect(filters.qAny).toEqual([["Java"]]);
    expect(filters.qPreferred).toEqual([["bankowość"]]);
  });

  it("bez wierszy w Championie krytyczne i tak obowiązują, must zostaje w rankingu", () => {
    const filters = jobListFilters(JOB, ["Java", "SQL"], {
      stored: null,
      decided: false,
      effective: ["Java"],
      source: "suggested",
      suggested: ["Java"],
      search_rows: [["Java"]],
    });
    expect(filters.qAny).toEqual([["Java"]]);
    expect(filters.skillsPreferred).toEqual(["Java", "SQL"]);
  });

  it("rekrutacja zdalna nie zawęża po mieście", () => {
    const filters = jobListFilters({ ...JOB, remote_policy: "remote" }, null);
    expect(filters.location).toBe("");
    expect(filters.locationPreferred).toEqual([]);
  });
});
