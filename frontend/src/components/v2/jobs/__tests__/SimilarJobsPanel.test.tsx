import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SentPerson, SimilarJobItem } from "@/lib/similar-jobs-api";

const people = vi.fn();
const search = vi.fn();
const unlinkApi = vi.fn();
const reassign = vi.fn();
const removeFromRecruitment = vi.fn();
const showActionToast = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const facts = vi.fn();
const matchScores = vi.fn();
const apiGet = vi.fn();
let canOpenProfile = true;

let similarState: { isLoading: boolean; isError: boolean; isSuccess: boolean } = {
  isLoading: false,
  isError: false,
  isSuccess: true,
};
let payload: {
  job_id: number;
  reassigned_count: number;
  linked: SimilarJobItem[];
  suggestions: SimilarJobItem[];
};

vi.mock("@/lib/similar-jobs-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/similar-jobs-api")>();
  return {
    ...actual,
    similarJobsApi: {
      ...actual.similarJobsApi,
      people: (...a: unknown[]) => people(...a),
      search: (...a: unknown[]) => search(...a),
      unlink: (...a: unknown[]) => unlinkApi(...a),
    },
    useSimilarJobs: () => ({
      data: similarState.isError ? undefined : payload,
      ...similarState,
      refetch: vi.fn(),
    }),
    useUnlinkSimilarJob: () => ({ mutate: vi.fn(), isPending: false }),
    useReassignFromSimilar: () => ({ mutateAsync: reassign, isPending: false }),
  };
});

vi.mock("@/lib/api", () => {
  const api = { get: (...a: unknown[]) => apiGet(...a), post: vi.fn(), delete: vi.fn() };
  return {
    default: api,
    api,
    candidatesApi: {
      removeFromRecruitment: (...a: unknown[]) => removeFromRecruitment(...a),
    },
  };
});

// Karta osoby (podgląd obok panelu) czyta trzy istniejące trasy.
vi.mock("@/lib/job-proposals-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: { ...actual.jobProposalsApi, facts: (...a: unknown[]) => facts(...a) },
  };
});
vi.mock("@/lib/candidate-search-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/candidate-search-api")>();
  return {
    ...actual,
    candidateSearchApi: {
      ...actual.candidateSearchApi,
      matchScores: (...a: unknown[]) => matchScores(...a),
    },
  };
});
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => canOpenProfile }));
vi.mock("@/components/v2/candidates/CandidateCvCell", () => ({
  useCandidateCvPreview: () => ({ open: vi.fn(), loading: false, modal: null }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast, showSuccess, showError, showToast: vi.fn() }),
}));

import { SimilarJobsPanel } from "@/components/v2/jobs/SimilarJobsPanel";

function job(overrides: Partial<SimilarJobItem> & { id: number }): SimilarJobItem {
  return {
    title: `Analityk ${overrides.id}`,
    reference_number: `ZOB-${overrides.id}`,
    status: "closed",
    closed_at: null,
    client_name: "PKO BP",
    similarity: 60,
    sent_count: 3,
    linked: false,
    ...overrides,
  };
}

function person(overrides: Partial<SentPerson> & { candidate_id: number }): SentPerson {
  return {
    name: `Osoba ${overrides.candidate_id}`,
    furthest_stage: "cv_sent",
    sent_at: "2026-09-12",
    outcome: "in_progress",
    already_in_job: false,
    selectable: true,
    ...overrides,
  };
}

function renderPanel(onOpenChange: (open: boolean) => void = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SimilarJobsPanel jobId={5} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
}

/** Zaznacza rekrutację 1725 i czeka na jej osoby. */
async function openGroup() {
  fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));
  await screen.findByLabelText("Przepnij Ewa Marczak");
}

beforeEach(() => {
  vi.clearAllMocks();
  similarState = { isLoading: false, isError: false, isSuccess: true };
  canOpenProfile = true;
  facts.mockResolvedValue({ job_id: 5, items: [] });
  matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
  apiGet.mockResolvedValue({ data: { recent_notes: [] } });
  payload = {
    job_id: 5,
    reassigned_count: 0,
    linked: [],
    suggestions: [job({ id: 1725 })],
  };
  people.mockResolvedValue({
    job_id: 5,
    jobs: [
      {
        job_id: 1725,
        people: [
          person({ candidate_id: 10, name: "Ewa Marczak" }),
          person({ candidate_id: 11, name: "Marek Zając", outcome: "rejected_by_client" }),
          person({ candidate_id: 12, name: "Oskar Pietrzak", outcome: "hired", selectable: false }),
        ],
      },
    ],
  });
});

describe("Panel „Podobne rekrutacje” — przepięcie jednym kliknięciem", () => {
  it("awaria podpowiedzi → komunikat błędu, bez „System nie znalazł” (R8-N14-4)", () => {
    similarState = { isLoading: false, isError: true, isSuccess: false };
    renderPanel();
    expect(screen.getByText(/Nie udało się wczytać podobnych rekrutacji/)).toBeTruthy();
    expect(screen.queryByText(/System nie znalazł podobnych rekrutacji/)).toBeNull();
  });

  it("podobieństwo z wektora ma „≈”, zapas leksykalny — sam procent (30.09)", () => {
    payload = {
      ...payload,
      suggestions: [
        job({ id: 1725, similarity: 72, similarity_kind: "vector" }),
        job({ id: 1726, similarity: 58, similarity_kind: "lexical" }),
      ],
    };
    renderPanel();
    expect(screen.getByText("≈ 72%")).toBeTruthy();
    expect(screen.getByText("58%")).toBeTruthy();
    expect(screen.queryByText("≈ 58%")).toBeNull();
  });

  it("nic nie jest zaznaczone samo (incydent 23.09)", () => {
    renderPanel();
    expect(screen.getByLabelText("Przepnij z: Analityk 1725")).not.toBeChecked();
    expect(screen.getByTestId("similar-panel-submit")).toBeDisabled();
    expect(people).not.toHaveBeenCalled();
  });

  it("kliknięcie rekrutacji zaznacza wysłanych poza zatrudnionymi i przepina ich", async () => {
    reassign.mockResolvedValue({
      added: [10, 11],
      skipped: [],
      warnings: [],
      total_added: 2,
      total_skipped: 0,
      linked_now: [1725],
    });
    renderPanel();
    fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));

    expect(await screen.findByLabelText("Przepnij Ewa Marczak")).toBeChecked();
    expect(screen.getByLabelText("Przepnij Marek Zając")).toBeChecked();
    const hired = screen.getByLabelText("Przepnij Oskar Pietrzak");
    expect(hired).not.toBeChecked();
    expect(hired).toBeDisabled();
    expect(people).toHaveBeenCalledWith(5, [1725]);

    const submit = screen.getByTestId("similar-panel-submit");
    expect(submit).toHaveTextContent("Przepnij 2 osoby do Nowych");
    fireEvent.click(submit);

    await waitFor(() =>
      expect(reassign).toHaveBeenCalledWith({ jobIds: [1725], candidateIds: [10, 11] }),
    );
    expect(showActionToast).toHaveBeenCalledWith(
      expect.stringContaining("Przepięto 2 osoby do Nowych."),
      expect.objectContaining({ actionLabel: "Cofnij" }),
    );

    // „Cofnij” zdejmuje dodanych z rekrutacji i rozłącza nowe połączenie.
    removeFromRecruitment.mockResolvedValue({});
    unlinkApi.mockResolvedValue({});
    await showActionToast.mock.calls[0][1].onAction();
    expect(removeFromRecruitment).toHaveBeenCalledWith(10, 5);
    expect(removeFromRecruitment).toHaveBeenCalledWith(11, 5);
    expect(unlinkApi).toHaveBeenCalledWith(5, 1725);
    expect(showSuccess).toHaveBeenCalledWith("Cofnięto przepięcie.");
  });

  it("odznaczona osoba nie jedzie; bez nikogo zostaje „Tylko połącz”", async () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));
    fireEvent.click(await screen.findByLabelText("Przepnij Ewa Marczak"));
    expect(screen.getByTestId("similar-panel-submit")).toHaveTextContent(
      "Przepnij 1 osobę do Nowych",
    );
    fireEvent.click(screen.getByLabelText("Przepnij Marek Zając"));
    expect(screen.getByTestId("similar-panel-submit")).toHaveTextContent("Tylko połącz");
  });

  it("wpisana rekrutacja dochodzi do panelu z zaznaczonymi ludźmi", async () => {
    search.mockResolvedValue([job({ id: 1837, title: "Analityk Systemowy", sent_count: 4 })]);
    people.mockImplementation((_jobId: number, ids: number[]) =>
      Promise.resolve({
        job_id: 5,
        jobs: [{ job_id: ids[0], people: [person({ candidate_id: 20, name: "Piotr Lis" })] }],
      }),
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Szukaj rekrutacji do przepięcia"), {
      target: { value: "analityk pko" },
    });
    const results = await screen.findByLabelText("Wyniki wyszukiwania rekrutacji");
    fireEvent.click(await within(results).findByText("Analityk Systemowy"));

    expect(await screen.findByLabelText("Przepnij Piotr Lis")).toBeChecked();
    expect(screen.getByLabelText("Przepnij z: Analityk Systemowy")).toBeChecked();
    expect(search).toHaveBeenCalledWith(5, "analityk pko");
  });

  it("błąd wczytania ludzi: „Ponów” zamiast wiecznego ładowania i brak przepięcia", async () => {
    people.mockRejectedValueOnce(new Error("500"));
    renderPanel();
    fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));
    expect(await screen.findByText(/Nie wczytano osób\./)).toBeInTheDocument();
    expect(screen.queryByText(/Wczytuję osoby/)).not.toBeInTheDocument();
    expect(screen.getByTestId("similar-panel-submit")).toBeDisabled();
    expect(screen.getByTestId("similar-panel-summary")).toHaveTextContent("Ponów");

    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByLabelText("Przepnij Ewa Marczak")).toBeChecked();
    expect(screen.getByTestId("similar-panel-submit")).toBeEnabled();
  });

  it("więcej niż 100 osób naraz — przycisk wyłączony z wyjaśnieniem", async () => {
    people.mockResolvedValue({
      job_id: 5,
      jobs: [
        {
          job_id: 1725,
          people: Array.from({ length: 101 }, (_, i) => person({ candidate_id: 100 + i })),
        },
      ],
    });
    renderPanel();
    fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));
    await screen.findByLabelText("Przepnij Osoba 100");
    expect(screen.getByTestId("similar-panel-submit")).toBeDisabled();
    expect(screen.getByTestId("similar-panel-summary")).toHaveTextContent(
      "najwyżej 100 osób — zaznaczonych jest 101",
    );
  });
});

describe("Panel „Podobne rekrutacje” — podgląd osoby obok panelu", () => {
  it("klik w nazwisko otwiera kartę i nie zmienia zaznaczenia", async () => {
    facts.mockResolvedValue({
      job_id: 5,
      items: [
        {
          candidate_id: 10,
          title: "Analityk Systemowy",
          company: null,
          years_experience: 7,
          city: "Kraków",
          max_onsite_days_per_week: null,
          remote_modes: [],
          availability_status: null,
          availability_date: null,
          expected_rate_hourly: null,
          expected_rate_currency: null,
          expected_rate_redacted: false,
          client_history: null,
        },
      ],
    });
    renderPanel();
    await openGroup();
    expect(screen.queryByTestId("similar-person-preview")).toBeNull();

    const name = screen.getByRole("link", { name: "Ewa Marczak" });
    expect(name).toHaveAttribute("href", "/candidates/10?from=job&jobId=5");
    fireEvent.click(name);

    const card = screen.getByTestId("similar-person-preview");
    expect(within(card).getByRole("heading", { name: "Ewa Marczak" })).toBeInTheDocument();
    expect(await within(card).findByText("Kraków")).toBeInTheDocument();
    expect(within(card).getByText("1 z 3")).toBeInTheDocument();
    expect(facts).toHaveBeenCalledWith(5, [10], expect.anything());
    expect(matchScores).toHaveBeenCalledWith(5, [10], expect.anything());
    // Karta siedzi w oknie panelu — inaczej fokus i kliknięcia by nie działały.
    expect(within(screen.getByRole("dialog")).getByTestId("similar-person-preview")).toBe(card);

    expect(screen.getByLabelText("Przepnij Ewa Marczak")).toBeChecked();
    expect(screen.getByTestId("similar-panel-submit")).toHaveTextContent(
      "Przepnij 2 osoby do Nowych",
    );
  });

  it("Ctrl-klik zostaje przy linku (profil w nowej karcie) i nie otwiera karty", async () => {
    renderPanel();
    await openGroup();
    const name = screen.getByRole("link", { name: "Ewa Marczak" });
    // jsdom nie nawiguje — sprawdzamy tylko, że panel nie przejął kliknięcia.
    name.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(name, { ctrlKey: true });
    expect(screen.queryByTestId("similar-person-preview")).toBeNull();
  });

  it("Esc zamyka najpierw kartę — panel i zaznaczenia zostają", async () => {
    const onOpenChange = vi.fn();
    renderPanel(onOpenChange);
    await openGroup();
    fireEvent.click(screen.getByLabelText("Przepnij Marek Zając"));
    fireEvent.click(screen.getByRole("link", { name: "Ewa Marczak" }));
    expect(screen.getByTestId("similar-person-preview")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("similar-person-preview")).toBeNull();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Przepnij Marek Zając")).not.toBeChecked();
    expect(screen.getByRole("link", { name: "Ewa Marczak" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("‹ › przechodzi po osobach w kolejności wierszy, także po zablokowanych", async () => {
    renderPanel();
    await openGroup();
    fireEvent.click(screen.getByRole("button", { name: "Podgląd: Marek Zając" }));
    let card = screen.getByTestId("similar-person-preview");
    expect(within(card).getByText("2 z 3")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Następna osoba" }));
    card = screen.getByTestId("similar-person-preview");
    expect(within(card).getByRole("heading", { name: "Oskar Pietrzak" })).toBeInTheDocument();
    expect(within(card).getByRole("checkbox")).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Następna osoba" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Podgląd: Oskar Pietrzak" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("pole „Przepnij” w karcie to to samo zaznaczenie co w wierszu", async () => {
    renderPanel();
    await openGroup();
    fireEvent.click(screen.getByRole("link", { name: "Ewa Marczak" }));
    const card = screen.getByTestId("similar-person-preview");
    fireEvent.click(within(card).getByRole("checkbox"));
    expect(screen.getByLabelText("Przepnij Ewa Marczak")).not.toBeChecked();
    expect(screen.getByTestId("similar-panel-submit")).toHaveTextContent(
      "Przepnij 1 osobę do Nowych",
    );
  });

  it("odznaczenie rekrutacji zamyka kartę jej osoby", async () => {
    renderPanel();
    await openGroup();
    fireEvent.click(screen.getByRole("link", { name: "Ewa Marczak" }));
    fireEvent.click(screen.getByLabelText("Przepnij z: Analityk 1725"));
    expect(screen.queryByTestId("similar-person-preview")).toBeNull();
  });

  it("rola bez dostępu do profili: nazwisko to przycisk, w karcie nie ma „Otwórz profil”", async () => {
    canOpenProfile = false;
    renderPanel();
    await openGroup();
    expect(screen.queryByRole("link", { name: "Ewa Marczak" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ewa Marczak" }));
    const card = screen.getByTestId("similar-person-preview");
    expect(within(card).queryByRole("link", { name: /Otwórz profil/ })).toBeNull();
  });
});
