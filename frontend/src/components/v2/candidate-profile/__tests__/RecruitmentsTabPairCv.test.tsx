import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const brandedGet = vi.fn();
const stageCvPdf = vi.fn();

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
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvPdf: (...a: unknown[]) => stageCvPdf(...a),
  fetchStageCvFile: vi.fn(async () => ({ blob: new Blob() })),
}));
// Edytor CV (TipTap) i podgląd pliku ładują się dynamicznie — zaślepka mówi,
// który wiersz etapu dostał edytor, a podgląd pokazuje tytuł i czyta PDF.
vi.mock("next/dynamic", () => ({
  default: () =>
    function DynamicStub(props: { stageId?: number; title?: string; loadPdf?: () => unknown }) {
      if (props.title) {
        return (
          <div data-testid="cv-preview">
            {props.title}
            <button type="button" onClick={() => props.loadPdf?.()}>
              wczytaj
            </button>
          </div>
        );
      }
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

function renderTab({
  stage = "cv_sent",
  readOnly = false,
}: { stage?: string; readOnly?: boolean } = {}) {
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
            latest_stage: stage,
            latest_stage_id: 21,
            stages: [{ stage }],
          },
        ]}
        isPending={false}
        error={null}
        refetch={vi.fn()}
        refreshing={false}
        focusedJobId={null}
        defaultJobId={null}
        view={"overview" as never}
        readOnly={readOnly}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  brandedGet.mockReset();
  stageCvPdf.mockReset();
  stageCvPdf.mockResolvedValue({ blob: new Blob() });
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
    // Dwa kolejne odczyty (wiersz etapu, potem wiersz pary) — w pełnym biegu
    // kolejki merge'ów domyślna sekunda `findBy` nie wystarczała (13.10.2026: 1,9 s).
    const edit = await screen.findByRole("button", { name: "Edytuj CV" }, { timeout: 5000 });
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

describe("RecruitmentsTab — podgląd CV do klienta (prośba Igora 23.10.2026)", () => {
  const pairCv = (stageId: number) =>
    Promise.resolve({
      data:
        stageId === 21
          ? { status: "none", edit_revision: 0, version: 1, pair_source_stage_id: 20 }
          : { status: "finalized", from_generator: true, edit_revision: 4, version: 2 },
    });

  it("po wysyłce: „CV wysłane do klienta” pokazuje plik z wiersza pary", async () => {
    brandedGet.mockImplementation(pairCv);
    renderTab();
    const button = await screen.findByRole(
      "button",
      { name: "CV wysłane do klienta" },
      { timeout: 5000 },
    );
    await userEvent.click(button);
    expect(await screen.findByTestId("cv-preview")).toHaveTextContent(
      "CV wysłane do klienta — Grzegorz Żebrowski",
    );
    await userEvent.click(screen.getByRole("button", { name: "wczytaj" }));
    expect(stageCvPdf).toHaveBeenCalledWith(20);
  });

  it("przed wysyłką ten sam podgląd nazywa się „Podgląd CV do klienta”", async () => {
    brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, edit_revision: 1, version: 1 },
    });
    renderTab({ stage: "verified" });
    expect(await screen.findByRole("button", { name: "Podgląd CV do klienta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CV wysłane do klienta" })).toBeNull();
  });

  it("bez prawa zapisu: zatwierdzone CV tak, szkic nie (serwer czyta szkic tylko z zapisem)", async () => {
    brandedGet.mockImplementation(pairCv);
    const { unmount } = renderTab({ readOnly: true });
    expect(
      await screen.findByRole("button", { name: "CV wysłane do klienta" }, { timeout: 5000 }),
    ).toBeInTheDocument();
    unmount();

    brandedGet.mockReset();
    brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, edit_revision: 1, version: 1 },
    });
    renderTab({ readOnly: true });
    await waitFor(() => expect(brandedGet).toHaveBeenCalledWith(21));
    expect(await screen.findByRole("button", { name: "Pokaż CV oryginalne" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CV wysłane do klienta" })).toBeNull();
  });

  it("brak CV do klienta: nie ma czego pokazać", async () => {
    brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 1 } });
    renderTab();
    expect(await screen.findByRole("button", { name: "Generuj CV" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CV wysłane do klienta" })).toBeNull();
  });
});
