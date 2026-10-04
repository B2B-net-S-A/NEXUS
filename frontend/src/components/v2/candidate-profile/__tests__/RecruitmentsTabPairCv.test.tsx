import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecruitmentsTab
        candidateId={121}
        candidateName="Grzegorz Żebrowski"
        history={[
          {
            job_id: 7,
            job_title: "Programista Python",
            latest_stage: "cv_sent",
            latest_stage_id: 21,
          },
        ]}
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
});

describe("RecruitmentsTab — CV do klienta z wiersza pary (runda 12)", () => {
  it("najnowszy wiersz etapu bez CV: karta edytuje CV z wiersza pary zamiast proponować generację", async () => {
    brandedGet.mockImplementation((stageId: number) =>
      Promise.resolve({
        data:
          stageId === 21
            ? {
                status: "none",
                edit_revision: 0,
                version: 1,
                pair_source_stage_id: 20,
                pair_source_status: "finalized",
              }
            : {
                status: "finalized",
                from_generator: true,
                generated_document_id: 5,
                edit_revision: 4,
                version: 2,
              },
      }),
    );
    renderTab();
    const edit = await screen.findByRole("button", { name: "Edytuj CV" });
    expect(screen.queryByRole("button", { name: "Generuj CV" })).toBeNull();
    expect(brandedGet).toHaveBeenCalledWith(20);
    await userEvent.click(edit);
    expect(await screen.findByTestId("editor-stub")).toHaveTextContent("editor:20");
  });

  it("wiersz z własnym CV zostaje przy sobie", async () => {
    brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, edit_revision: 1, version: 1 },
    });
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: "Edytuj CV" }));
    expect(await screen.findByTestId("editor-stub")).toHaveTextContent("editor:21");
    expect(brandedGet).not.toHaveBeenCalledWith(20);
  });
});
