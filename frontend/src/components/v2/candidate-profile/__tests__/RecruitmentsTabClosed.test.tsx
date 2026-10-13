import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const brandedGet = vi.fn();

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  candidatesApi: {
    setRecruitmentExpectedRate: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
    removeFromRecruitment: vi.fn(),
  },
  candidateStageCvApi: {
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
    original: {
      get: vi.fn(async () => ({ data: { has_snapshot: true } })),
      refresh: vi.fn(),
    },
  },
}));
// Edytor CV (TipTap) ładuje się dynamicznie — w teście zaślepka mówi, który
// wiersz etapu dostał.
vi.mock("next/dynamic", () => ({
  default: () =>
    function EditorStub(props: { stageId?: number }) {
      return <div data-testid="editor-stub">{`editor:${props.stageId}`}</div>;
    },
}));
vi.mock("@/components/feedback/CandidateInterviewFeedbackPanel", () => ({
  CandidateInterviewFeedbackPanel: () => null,
}));
vi.mock("@/components/SuggestedJobsWidget", () => ({ SuggestedJobsWidget: () => null }));
vi.mock("@/components/candidates/SuggestedPoolsWidget", () => ({ SuggestedPoolsWidget: () => null }));
vi.mock("@/components/v2/candidate-profile/RateHistoryDialog", () => ({
  RateHistorySummary: () => null,
}));
vi.mock("@/components/ConflictsWidget", () => ({ ConflictsWidget: () => null }));
vi.mock("@/components/HiringManagerVetoesWidget", () => ({ HiringManagerVetoesWidget: () => null }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({
  DopasowanieTab: (props: { jobId?: number }) => (
    <div data-testid="match-score">{`ocena:${props.jobId}`}</div>
  ),
}));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({ CvGeneratorDialog: () => null }));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({ CVShareLinkModal: () => null }));
vi.mock("@/components/CandidatePipelinesWidget", () => ({
  candidatePipelinesQueryKey: (id: number) => ["candidate-pipelines", id],
}));

import { RecruitmentsTab } from "../RecruitmentsTab";
import { useAuthStore } from "@/store/auth";

/**
 * Rekrutacje (04.10.2026): zakończone jako tabela tylko do odczytu (D2) —
 * rozwinięcie pokazuje ścieżkę, bez stawek do uzupełnienia i bez generowania
 * CV; „Usuń z rekrutacji” tylko admin. Od 13.10.2026 (E3) „Zakończone” są
 * otwarte od wejścia, z 5 ostatnimi i „Pokaż wszystkie”, a rozwinięty wiersz
 * ma też zwiniętą ocenę dopasowania.
 */
const HISTORY = [
  {
    job_id: 7,
    job_title: "Programista Python",
    client_name: "Bank A",
    job_status: "published",
    latest_stage: "cv_sent",
    latest_stage_id: 21,
    stages: [{ stage: "cv_sent", moved_at: "2026-09-20T10:00:00Z" }],
  },
  {
    job_id: 8,
    job_title: "Java Lead",
    client_name: "Telekom B",
    job_status: "closed",
    latest_stage: "rejected",
    latest_stage_id: 31,
    last_seen: "2026-06-26T10:00:00Z",
    stages: [
      { stage: "rejected", moved_at: "2026-06-26T10:00:00Z" },
      { stage: "client_interview", moved_at: "2026-06-20T10:00:00Z" },
      { stage: "verified", moved_at: "2026-06-10T10:00:00Z" },
    ],
  },
  {
    job_id: 9,
    job_title: "Backend Dev",
    client_name: "Logistyka C",
    job_status: "published",
    latest_stage: "hired",
    latest_stage_id: 41,
    last_seen: "2026-03-13T10:00:00Z",
    stages: [{ stage: "hired", moved_at: "2026-03-13T10:00:00Z" }],
  },
];

function renderTab({
  history = HISTORY,
  focusedJobId = null,
}: { history?: unknown[]; focusedJobId?: number | null } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecruitmentsTab
        candidateId={121}
        candidateName="Grzegorz Żebrowski"
        history={history as never[]}
        isPending={false}
        error={null}
        refetch={vi.fn()}
        refreshing={false}
        focusedJobId={focusedJobId}
        defaultJobId={null}
        view={"overview" as never}
        readOnly={false}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  brandedGet.mockReset();
  brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 1 } });
  useAuthStore.setState({ user: { id: 5, role: "recruiter" } } as never);
});

describe("RecruitmentsTab — zakończone rekrutacje jako tabela", () => {
  it("zatrudnienie i odrzucenie idą do otwartej tabeli „Zakończone” z wynikiem", async () => {
    const user = userEvent.setup();
    renderTab();
    expect(screen.getByText(/W toku · 1/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: "Rekrutacje w toku" })).getByRole("button", {
        name: /^Programista Python/,
      }),
    ).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Zakończone · 2" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const table = screen.getByRole("table", { name: "Zakończone rekrutacje" });
    expect(within(table).getByText("Doszedł do")).toBeInTheDocument();
    const lead = within(table).getByText("Java Lead").closest("tr")!;
    expect(lead).toHaveTextContent("Telekom B");
    expect(lead).toHaveTextContent("Rozmowa u klienta");
    expect(lead).toHaveTextContent("Odrzucony");
    const hired = within(table).getByText("Backend Dev").closest("tr")!;
    expect(hired).toHaveTextContent("Zatrudniony");

    await user.click(toggle);
    expect(screen.queryByRole("table", { name: "Zakończone rekrutacje" })).toBeNull();
  });

  it("rozwinięty wiersz jest tylko do odczytu, a rekruter nie usuwa z zakończonej", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByRole("button", { name: /Java Lead/ }));

    const path = await screen.findByRole("list", { name: "Ścieżka etapów" });
    expect(path).toHaveTextContent(/Zweryfikowany.*Rozmowa u klienta/);
    // Jedyna karta z „Generuj CV” to proces w toku — zakończony go nie ma.
    expect(screen.queryAllByRole("button", { name: "Generuj CV" }).length).toBeLessThanOrEqual(1);
    expect(screen.queryByRole("button", { name: /Więcej akcji: Java Lead/ })).toBeNull();
  });
});

describe("RecruitmentsTab — zakończone: 5 ostatnich i ocena dopasowania", () => {
  const many = Array.from({ length: 7 }, (_, i) => ({
    job_id: 100 + i,
    job_title: `Zakończona ${i + 1}`,
    client_name: "Klient",
    job_status: "closed",
    latest_stage: "rejected",
    latest_stage_id: 200 + i,
    // Ostatnio zakończona ma największy numer — lista ma ją na górze.
    last_seen: `2026-0${i + 1}-15T10:00:00Z`,
    stages: [{ stage: "rejected", moved_at: `2026-0${i + 1}-15T10:00:00Z` }],
  }));

  it("pokazuje 5 ostatnich, resztę po „Pokaż wszystkie (N)”", async () => {
    const user = userEvent.setup();
    renderTab({ history: many });
    const table = screen.getByRole("table", { name: "Zakończone rekrutacje" });
    const titles = () =>
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell")[0].textContent);
    expect(titles()).toEqual([
      "Zakończona 7",
      "Zakończona 6",
      "Zakończona 5",
      "Zakończona 4",
      "Zakończona 3",
    ]);
    await user.click(screen.getByRole("button", { name: "Pokaż wszystkie (7)" }));
    expect(titles()).toHaveLength(7);
    expect(screen.queryByRole("button", { name: /Pokaż wszystkie/ })).toBeNull();
  });

  it("wiersz z adresu spoza piątki: od razu cała lista i rozwinięty wiersz", () => {
    renderTab({ history: many, focusedJobId: 100 });
    expect(document.getElementById("candidate-recruitment-100")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Zakończona 1" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.queryByRole("button", { name: /Pokaż wszystkie/ })).toBeNull();
  });

  it("rozwinięty zakończony wiersz ma zwiniętą ocenę dopasowania tej rekrutacji", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByRole("button", { name: /Java Lead/ }));
    const details = document.getElementById("candidate-closed-recruitment-8-details")!;
    expect(within(details).queryByTestId("match-score")).toBeNull();
    await user.click(within(details).getByRole("button", { name: /Ocena dopasowania/ }));
    expect(within(details).getByTestId("match-score")).toHaveTextContent("ocena:8");
  });
});
