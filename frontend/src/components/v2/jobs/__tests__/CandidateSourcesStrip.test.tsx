import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const countsApi = vi.fn();
const championGet = vi.fn();
const listPage = vi.fn();
const similarState: { data: unknown; isError: boolean; isSuccess: boolean } = {
  data: undefined,
  isError: false,
  isSuccess: false,
};
const similarEnabled = vi.fn();

vi.mock("@/lib/job-proposals-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: { ...actual.jobProposalsApi, counts: (...a: unknown[]) => countsApi(...a) },
  };
});
vi.mock("@/lib/similar-jobs-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/similar-jobs-api")>();
  return {
    ...actual,
    useSimilarJobs: (_jobId: number, enabled: boolean) => {
      similarEnabled(enabled);
      return similarState;
    },
  };
});
vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: () => Promise.resolve({ all_of: [] }) },
  requirementLabels: () => [],
}));
vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
  api: { get: vi.fn() },
  championApi: { get: (...a: unknown[]) => championGet(...a) },
}));
vi.mock("@/components/v2/pages/candidate-list-query", () => ({
  fetchCandidateListPage: (...a: unknown[]) => listPage(...a),
}));

import { jobProposalsKeys } from "@/lib/job-proposals-api";
import {
  CandidateSourcesStrip,
  CandidateSourcesStripView,
  similarTileDescription,
  type CandidateSourceTile,
} from "@/components/v2/jobs/CandidateSourcesStrip";

const JOB = { id: 5, title: "Analityk KYC", remote_policy: "remote", champion_profile: null };

const TILES: CandidateSourceTile[] = [
  { tab: "similar", count: 25, description: "19 wysłanych do klienta" },
  { tab: "postings", count: "loading", description: "Z ostatnich 7 dni" },
  { tab: "base", count: null, description: "Wybrane przez nocny przegląd bazy" },
  { tab: "search", count: 0, description: "Po słowach z Championa" },
];

function renderStrip(props: Partial<React.ComponentProps<typeof CandidateSourcesStrip>> = {}) {
  const onOpen = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CandidateSourcesStrip jobId={5} job={JOB} canSeeSimilar onOpen={onOpen} {...props} />
    </QueryClientProvider>,
  );
  return { onOpen };
}

const count = (tab: string) => screen.getByTestId(`source-tile-${tab}-count`);

describe("CandidateSourcesStripView — pasek „Kandydaci do dodania”", () => {
  it("cztery kafle w stałej kolejności; klik otwiera okno na zakładce kafla", async () => {
    const onOpen = vi.fn();
    render(<CandidateSourcesStripView tiles={TILES} onOpen={onOpen} />);
    const strip = screen.getByRole("region", { name: "Kandydaci do dodania" });
    expect(strip).toHaveAttribute("data-help", "jobs.board.sources");
    expect(
      screen.getAllByRole("button").map((b) => b.getAttribute("data-testid")),
    ).toEqual(["source-tile-similar", "source-tile-postings", "source-tile-base", "source-tile-search"]);
    await userEvent.click(screen.getByTestId("source-tile-postings"));
    expect(onOpen).toHaveBeenCalledWith("postings");
    await userEvent.click(screen.getByTestId("source-tile-search"));
    expect(onOpen).toHaveBeenLastCalledWith("search");
  });

  it("liczba, „liczę” i „nie policzono” to trzy różne stany — brak liczby nigdy nie jest zerem", () => {
    render(<CandidateSourcesStripView tiles={TILES} onOpen={vi.fn()} />);
    expect(count("similar")).toHaveTextContent("25");
    expect(count("postings")).toHaveTextContent("…");
    expect(count("base")).toHaveTextContent("—");
    expect(count("base")).not.toHaveTextContent("0");
    // Prawdziwe zero zostaje zerem.
    expect(count("search")).toHaveTextContent("0");
  });

  it("„Dodaj po nazwisku” i „z pliku CV” tylko dla roli z prawem dodawania", async () => {
    const onAddByName = vi.fn();
    const onAddFromCv = vi.fn();
    const { rerender } = render(<CandidateSourcesStripView tiles={TILES} onOpen={vi.fn()} />);
    expect(screen.queryByTestId("sources-add-by-name")).toBeNull();
    expect(screen.queryByTestId("sources-add-from-cv")).toBeNull();
    rerender(
      <CandidateSourcesStripView
        tiles={TILES}
        onOpen={vi.fn()}
        onAddByName={onAddByName}
        onAddFromCv={onAddFromCv}
        trailing={<span data-testid="view-controls" />}
      />,
    );
    await userEvent.click(screen.getByTestId("sources-add-by-name"));
    await userEvent.click(screen.getByTestId("sources-add-from-cv"));
    expect(onAddByName).toHaveBeenCalled();
    expect(onAddFromCv).toHaveBeenCalled();
    expect(screen.getByTestId("view-controls")).toBeTruthy();
  });
});

describe("similarTileDescription", () => {
  it.each([
    [{ sent: 1, other: 0 }, "1 wysłana do klienta w podobnych rekrutacjach"],
    [{ sent: 3, other: 1 }, "3 wysłane do klienta, 1 pozostała z tych rekrutacji"],
    [{ sent: 19, other: 6 }, "19 wysłanych do klienta, 6 pozostałych z tych rekrutacji"],
    [{ sent: 22, other: 3 }, "22 wysłane do klienta, 3 pozostałe z tych rekrutacji"],
    [{ sent: 12, other: 0 }, "12 wysłanych do klienta w podobnych rekrutacjach"],
  ])("%j → %s", (total, expected) => {
    expect(similarTileDescription(total)).toBe(expected);
  });

  it("bez danych mówi, co jest w kaflu", () => {
    expect(similarTileDescription(null)).toBe(
      "Osoby z podobnych rekrutacji — najpierw wysłane do klienta",
    );
  });
});

describe("CandidateSourcesStrip — liczby kafli", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    similarState.data = undefined;
    similarState.isError = false;
    similarState.isSuccess = false;
    countsApi.mockResolvedValue({
      job_id: 5,
      days: 7,
      postings_recent: 4,
      base: 12,
      screened_out: 2,
      not_searchable_must: [],
    });
    championGet.mockResolvedValue({ data: { champion_profile: null } });
    listPage.mockResolvedValue({ items: [], total: 86 });
  });

  it("ogłoszenia i baza z jednego zapytania o liczniki; podobne = wysłani + pozostali", async () => {
    similarState.data = { reassignable_people: 19, other_people: 6 };
    similarState.isSuccess = true;
    renderStrip();
    await waitFor(() => expect(count("postings")).toHaveTextContent("4"));
    expect(count("base")).toHaveTextContent("12");
    expect(count("similar")).toHaveTextContent("25");
    expect(screen.getByTestId("source-tile-similar")).toHaveTextContent(
      "19 wysłanych do klienta, 6 pozostałych z tych rekrutacji",
    );
    expect(screen.getByTestId("source-tile-postings")).toHaveTextContent("2 odłożonych przez AI");
    expect(countsApi).toHaveBeenCalledTimes(1);
  });

  it("po otwarciu okna kafle mówią to samo co zakładki (wszystkie źródła), nie samą skrzynkę", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(jobProposalsKeys.visibleSplit(5), { postings: 6, base: 31 });
    render(
      <QueryClientProvider client={qc}>
        <CandidateSourcesStrip jobId={5} job={JOB} canSeeSimilar onOpen={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(count("postings")).toHaveTextContent("6");
    expect(count("base")).toHaveTextContent("31");
    // Odpowiedź serwera (4 / 12) nie cofa liczb z okna.
    await waitFor(() => expect(countsApi).toHaveBeenCalled());
    expect(count("base")).toHaveTextContent("31");
  });

  it("awaria liczników to „—”, nie zero; kafle dalej otwierają okno", async () => {
    countsApi.mockRejectedValue({ response: { status: 500 } });
    similarState.isError = true;
    const { onOpen } = renderStrip();
    await waitFor(() => expect(count("postings")).toHaveTextContent("—"));
    expect(count("base")).toHaveTextContent("—");
    expect(count("similar")).toHaveTextContent("—");
    await userEvent.click(screen.getByTestId("source-tile-base"));
    expect(onOpen).toHaveBeenCalledWith("base");
  });

  it("rola bez wglądu w podobne rekrutacje nie pyta o nie", async () => {
    renderStrip({ canSeeSimilar: false });
    await waitFor(() => expect(count("postings")).toHaveTextContent("4"));
    expect(similarEnabled).toHaveBeenCalledWith(false);
    expect(count("similar")).toHaveTextContent("—");
  });

  it("„Szukaj w bazie” liczy osoby po słowach z Championa i pokazuje te słowa", async () => {
    championGet.mockResolvedValue({
      data: { champion_profile: { search: { requirements: [["KYC", "AML"], ["bankow*"]], exclude: [] } } },
    });
    renderStrip();
    await waitFor(() => expect(count("search")).toHaveTextContent("86"));
    expect(screen.getByTestId("source-tile-search")).toHaveTextContent("Po słowach z Championa: KYC");
    // Sam licznik: jedna osoba na stronie, bez pobierania listy.
    expect(listPage.mock.calls[0][0]).toMatchObject({ page_size: 1, recruitment_match: "not_assigned" });
    // Liczba nie zależy od kolejności — „Dopasowanie” układałoby całą listę
    // przy każdym wejściu na rekrutację.
    expect((listPage.mock.calls[0][0] as { sort?: string }).sort).not.toBe("match");
  });

  it("bez słów w Championie kafel nie szuka i mówi dlaczego", async () => {
    renderStrip();
    await waitFor(() =>
      expect(screen.getByTestId("source-tile-search")).toHaveTextContent(
        "W Championie nie ma jeszcze słów do wyszukiwania",
      ),
    );
    expect(count("search")).toHaveTextContent("—");
    expect(listPage).not.toHaveBeenCalled();
  });
});
