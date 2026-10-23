import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const check = vi.fn();
const matchScores = vi.fn();
const bulkAdd = vi.fn();
const jobsList = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api/similarCandidates", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/similarCandidates")>(
    "@/lib/api/similarCandidates",
  );
  return {
    ...actual,
    similarCandidatesApi: { list: vi.fn(), check: (...args: unknown[]) => check(...args) },
  };
});
vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: { matchScores: (...args: unknown[]) => matchScores(...args) },
  proposalsBulkApi: { add: (...args: unknown[]) => bulkAdd(...args) },
}));
vi.mock("@/lib/api", () => ({
  jobsApi: { list: (...args: unknown[]) => jobsList(...args) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showToast: vi.fn() }),
}));

import { SimilarAssignSheet } from "../SimilarAssignSheet";
import type { SimilarCandidate } from "@/lib/api/similarCandidates";
import type { PickableJob } from "@/lib/similar-candidates-view";

/**
 * „Przypisz” z zakładki „Podobni” (22.10.2026, decyzje Artura): przy każdej
 * rekrutacji wynik sprawdzenia, brak krytycznej = ostrzeżenie z powodem;
 * osoba domyślnie odznaczona, a zaznaczona wymaga zdania, które idzie do
 * serwera w `reasons`.
 */

const PAWEL: SimilarCandidate = {
  id: 7,
  name: "Paweł",
  lastname: "Testowy",
  title: "Administrator Windows",
  company: null,
  city: "Warszawa",
  location: null,
  years_it_experience: 9,
  competence_category: null,
  rate_hourly: 70,
  rate_currency: "PLN",
  availability_status: "actively_looking",
  availability_date: null,
  active_processes: 0,
  score: 0.86,
  level: "very",
  shared_skills: ["active directory", "windows server"],
  only_source_skills: ["microsoft 365"],
  only_candidate_skills: [],
  duplicate_signals: [],
};

const job = (id: number, title: string, group: PickableJob["group"]): PickableJob => ({
  id,
  names: { id, title, working_title: null, client_reference: `ZOB-${id}` },
  clientName: "Klient Przykładowy",
  group,
});

const CHECKS = [
  {
    job_id: 3011,
    critical_labels: ["Microsoft 365", "Active Directory"],
    candidates: [
      {
        candidate_id: 7,
        critical: [
          { label: "Microsoft 365", status: "missing", sources: [] },
          { label: "Active Directory", status: "met", sources: ["cv"] },
        ],
        missing: ["Microsoft 365"],
        in_job: null,
      },
    ],
  },
  {
    job_id: 2990,
    critical_labels: ["VMware"],
    candidates: [
      {
        candidate_id: 7,
        critical: [{ label: "VMware", status: "met", sources: ["cv", "note"] }],
        missing: [],
        in_job: null,
      },
    ],
  },
];

function renderSheet() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <SimilarAssignSheet
      sourceCandidateId={1}
      sourceName="Adam Testowy"
      people={[PAWEL]}
      sourceJobs={[job(3011, "Administrator M365", "source")]}
      myJobs={[job(2990, "Administrator VMware", "mine")]}
      initialJobId={null}
      onClose={vi.fn()}
      onAdded={vi.fn()}
    />,
    { wrapper },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  check.mockResolvedValue(CHECKS);
  matchScores.mockResolvedValue({ scores: { "7": 61 }, breakdowns: {} });
  jobsList.mockResolvedValue({ data: { items: [] } });
  bulkAdd.mockResolvedValue({ added: [7], skipped: [], warnings: [], total_added: 1, total_skipped: 0 });
});

describe("SimilarAssignSheet", () => {
  it("pokazuje przy rekrutacjach osoby i moich wynik sprawdzenia", async () => {
    renderSheet();
    expect(await screen.findByText("Brak krytycznej: Microsoft 365")).toBeInTheDocument();
    expect(screen.getByText("Spełnia krytyczne 1/1")).toBeInTheDocument();
    expect(check).toHaveBeenCalledWith(1, [3011, 2990], [7]);
  });

  it("brak krytycznej: osoba odznaczona, „Dodaj mimo to” czeka na zdanie i wysyła je", async () => {
    renderSheet();
    fireEvent.click(await screen.findByRole("button", { name: /Administrator M365/ }));
    const panel = await screen.findByRole("region", { name: "Kogo dodać" });
    expect(within(panel).getByText(/nie ma w CV, profilu ani notatkach/)).toBeInTheDocument();
    const box = within(panel).getByRole("checkbox", { name: "Dodaj: Paweł Testowy" });
    expect(box).toHaveAttribute("data-state", "unchecked");

    fireEvent.click(box);
    const submit = screen.getByRole("button", { name: "Dodaj mimo to" });
    expect(submit).toBeDisabled();

    fireEvent.change(within(panel).getByLabelText(/Dlaczego mimo to/), {
      target: { value: "Exchange Online u klienta — dopytam" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(bulkAdd).toHaveBeenCalledTimes(1));
    expect(bulkAdd).toHaveBeenCalledWith(3011, {
      candidate_ids: [7],
      source: "similar_candidates",
      reasons: { 7: "Exchange Online u klienta — dopytam" },
    });
    await waitFor(() => expect(showSuccess).toHaveBeenCalled());
  });

  it("spełniający krytyczne jest zaznaczony od razu i dodaje się bez zdania", async () => {
    renderSheet();
    fireEvent.click(await screen.findByRole("button", { name: /Administrator VMware/ }));
    const panel = await screen.findByRole("region", { name: "Kogo dodać" });
    await waitFor(() =>
      expect(within(panel).getByRole("checkbox", { name: "Dodaj: Paweł Testowy" })).toHaveAttribute(
        "data-state",
        "checked",
      ),
    );
    expect(within(panel).getByText(/jest: CV, notatka/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    await waitFor(() =>
      expect(bulkAdd).toHaveBeenCalledWith(2990, {
        candidate_ids: [7],
        source: "similar_candidates",
        reasons: {},
      }),
    );
  });
});
