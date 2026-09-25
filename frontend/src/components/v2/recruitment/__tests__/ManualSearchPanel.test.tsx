import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getReqs: vi.fn(), list: vi.fn(), getChampion: vi.fn() }));

vi.mock("@/lib/api", () => ({
  championApi: { get: (...a: unknown[]) => mocks.getChampion(...a) },
}));

vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: (...a: unknown[]) => mocks.getReqs(...a) },
  // Uproszczone lustro: etykiety pozycji `must`.
  requirementLabels: (data: { must: string[] }) => data.must,
}));
vi.mock("@/components/v2/pages/CandidatesListV2", () => ({
  CandidatesListV2: (props: unknown) => {
    mocks.list(props);
    return <div data-testid="candidates-list" />;
  },
}));

import { jobListFilters, ManualSearchPanel } from "@/components/v2/recruitment/ManualSearchPanel";
import type { CandidatesListEmbed } from "@/components/v2/pages/CandidatesListV2";

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
    // tytuł bez klienta i numeru szuka po znaczeniu, miasto i kategoria z rekrutacji.
    expect(embed.initialFilters.skillsPreferred).toEqual(["SQL", "UML"]);
    expect(embed.initialFilters.q).toBe("Analityk Systemowy");
    expect(embed.initialFilters.textMode).toBe("semantic");
    expect(embed.initialFilters.location).toBe("Warszawa");
    expect(embed.initialFilters.competenceCategoryIds).toEqual([5]);
    expect(embed.initialFilters.status).toEqual(["active", "passive"]);
  });

  it("błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca do kolumn rekrutacji", async () => {
    mocks.getReqs.mockRejectedValue(new Error("boom"));
    renderPanel();
    await screen.findByTestId("candidates-list");
    expect(lastEmbed().initialFilters.skillsPreferred).toEqual(["Java"]);
    expect(lastEmbed().readOnly).toBe(false);
  });

  it("wymagania z Championa: wiersze i wykluczenia na start, bez tytułu po znaczeniu", async () => {
    mocks.getReqs.mockResolvedValue({ must: ["SQL"] });
    mocks.getChampion.mockResolvedValue({
      data: {
        champion_profile: {
          search: { requirements: [["Java"], ["Kafka", "RabbitMQ"], []], exclude: ["junior"] },
        },
      },
    });
    renderPanel();
    await screen.findByTestId("candidates-list");
    const embed = lastEmbed();
    expect(mocks.getChampion).toHaveBeenCalledWith(7);
    expect(embed.initialFilters.qAny).toEqual([["Java"], ["Kafka", "RabbitMQ"]]);
    expect(embed.initialFilters.qNone).toEqual(["junior"]);
    expect(embed.initialFilters.q).toBe("");
    // Must-have zostają w rankingu jak dotąd.
    expect(embed.initialFilters.skillsPreferred).toEqual(["SQL"]);
    expect(embed.keywordsNote).toMatch(/ustawione przy tworzeniu rekrutacji/);
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
    expect(lastEmbed().initialFilters.qAny).toEqual([["Python"]]);
  });

  it("rekrutacja zdalna nie zawęża po mieście", () => {
    const filters = jobListFilters({ ...JOB, remote_policy: "remote" }, null);
    expect(filters.location).toBe("");
  });
});
