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
      data: payload,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    }),
    useUnlinkSimilarJob: () => ({ mutate: vi.fn(), isPending: false }),
    useReassignFromSimilar: () => ({ mutateAsync: reassign, isPending: false }),
  };
});

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  candidatesApi: {
    removeFromRecruitment: (...a: unknown[]) => removeFromRecruitment(...a),
  },
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

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SimilarJobsPanel jobId={5} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
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
