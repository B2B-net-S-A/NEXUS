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
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: () => null }));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({ CvGeneratorDialog: () => null }));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({ CVShareLinkModal: () => null }));
vi.mock("@/components/CandidatePipelinesWidget", () => ({
  candidatePipelinesQueryKey: (id: number) => ["candidate-pipelines", id],
}));

import { RecruitmentsTab } from "../RecruitmentsTab";
import { useAuthStore } from "@/store/auth";

/**
 * Rekrutacje (04.10.2026): w toku jako karty, zakończone jako tabela tylko do
 * odczytu (D2) — rozwinięcie pokazuje ścieżkę, bez stawek do uzupełnienia
 * i bez generowania CV; „Usuń z rekrutacji” tylko admin.
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

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecruitmentsTab
        candidateId={121}
        candidateName="Grzegorz Żebrowski"
        history={HISTORY}
        isPending={false}
        error={null}
        refetch={vi.fn()}
        refreshing={false}
        focusedJobId={null}
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
  it("w toku zostaje kartą, zatrudnienie i odrzucenie idą do tabeli z wynikiem", async () => {
    const user = userEvent.setup();
    renderTab();
    expect(screen.getByText(/W toku · 1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Programista Python" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zakończone (2)" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("Doszedł do")).toBeInTheDocument();
    const lead = within(table).getByText("Java Lead").closest("tr")!;
    expect(lead).toHaveTextContent("Telekom B");
    expect(lead).toHaveTextContent("Rozmowa u klienta");
    expect(lead).toHaveTextContent("Odrzucony");
    const hired = within(table).getByText("Backend Dev").closest("tr")!;
    expect(hired).toHaveTextContent("Zatrudniony");
  });

  it("rozwinięty wiersz jest tylko do odczytu, a rekruter nie usuwa z zakończonej", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByRole("button", { name: "Zakończone (2)" }));
    await user.click(screen.getByRole("button", { name: /Java Lead/ }));

    const path = await screen.findByRole("list", { name: "Ścieżka etapów" });
    expect(path).toHaveTextContent(/Zweryfikowany.*Rozmowa u klienta/);
    // Jedyna karta z „Generuj CV” to proces w toku — zakończony go nie ma.
    expect(screen.queryAllByRole("button", { name: "Generuj CV" }).length).toBeLessThanOrEqual(1);
    expect(screen.queryByRole("button", { name: /Więcej akcji: Java Lead/ })).toBeNull();
  });
});
