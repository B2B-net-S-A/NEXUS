import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pipelines = vi.fn();
const stageUpload = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: (...a: unknown[]) => post(...a) },
  phase3Api: { candidatePipelines: (...a: unknown[]) => pipelines(...a) },
  candidateStageCvApi: {
    original: { upload: (...a: unknown[]) => stageUpload(...a) },
    branded: { get: vi.fn().mockResolvedValue({ data: { status: "none", edit_revision: 0 } }) },
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { AddCvDialog, cvAlreadyAtClient, openRecruitments } from "@/components/v2/candidate-profile/AddCvDialog";
import type { CandidatePipelineRow } from "@/lib/api";

function row(jobId: number, column: string, title: string): CandidatePipelineRow {
  return {
    candidate_stage_id: jobId * 10,
    job_id: jobId,
    job_title: title,
    client_id: 1,
    stage_name: null,
    stage_category: null,
    is_terminal: false,
    board_column: column,
    moved_at: null,
    days_in_stage: 1,
    rating: null,
    has_scorecard: false,
  };
}

const rows = [
  row(42856, "screening", "Ops person – Hadoop Data Ingestion"),
  row(42883, "cv_sent", "Retail Technology Services – CICD Engineer"),
  row(40000, "closed", "Zamknięta karta"),
  { ...row(41000, "new", "Zamknięta rekrutacja"), job_status: "closed" },
];

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCvDialog open onOpenChange={vi.fn()} candidateId={225577} candidateName="Anna Nowak" />
    </QueryClientProvider>,
  );
}

const pdf = () => new File(["%PDF-1.4"], "Anna_CV_2026.pdf", { type: "application/pdf" });

describe("AddCvDialog — reguły", () => {
  it("rekrutacje w toku bez zamkniętych; po „CV wysłane” CV jest u klienta", () => {
    expect(openRecruitments(rows).map((r) => r.job_id)).toEqual([42856, 42883]);
    expect(cvAlreadyAtClient(rows[0])).toBe(false);
    expect(cvAlreadyAtClient(rows[1])).toBe(true);
  });
});

describe("AddCvDialog", () => {
  beforeEach(() => {
    pipelines.mockReset().mockResolvedValue({ data: { pipelines: rows } });
    stageUpload.mockReset().mockResolvedValue({
      data: { uploaded_filename: "Anna_CV_2026.pdf", uploaded_document_id: 5, company_cv: "confirm", company_cv_stage_id: 428560 },
    });
    post.mockReset().mockResolvedValue({ data: {} });
  });

  it("wgrywa CV w zaznaczonej rekrutacji, a tej po „CV wysłane” nie rusza", async () => {
    renderDialog();
    expect(await screen.findByText("Ops person – Hadoop Data Ingestion")).toBeInTheDocument();
    expect(screen.getByText("CV jest już u klienta — tu zostaje wysłana wersja.")).toBeInTheDocument();
    expect(screen.queryByText("Zamknięta rekrutacja")).toBeNull();
    expect(screen.queryByText("Zamknięta karta")).toBeNull();

    await userEvent.upload(screen.getByLabelText(/Wybierz albo upuść plik CV/), pdf());
    await userEvent.click(screen.getByRole("button", { name: "Dodaj CV" }));

    await waitFor(() => expect(stageUpload).toHaveBeenCalledTimes(1));
    expect(stageUpload.mock.calls[0][0]).toBe(428560);
    expect(stageUpload.mock.calls[0][2]).toEqual({ mode: "candidate" });
    expect(post).not.toHaveBeenCalled();
    expect(await screen.findByText(/Plik jest już potwierdzony/)).toBeInTheDocument();
  });

  it("bez rekrutacji — samo główne CV w profilu", async () => {
    pipelines.mockResolvedValue({ data: { pipelines: [] } });
    renderDialog();
    expect(await screen.findByText("Ta osoba nie jest teraz w żadnej rekrutacji.")).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText(/Wybierz albo upuść plik CV/), pdf());
    await userEvent.click(screen.getByRole("button", { name: "Dodaj CV" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const form = post.mock.calls[0][1] as FormData;
    expect(post.mock.calls[0][0]).toBe("/api/candidates/225577/documents");
    expect(form.get("is_primary")).toBe("true");
    expect(stageUpload).not.toHaveBeenCalled();
  });
});
