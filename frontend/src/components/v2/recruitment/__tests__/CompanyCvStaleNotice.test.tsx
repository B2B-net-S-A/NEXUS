import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const selectGenerated = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => apiGet(...a) },
  candidateStageCvApi: { branded: { selectGenerated: (...a: unknown[]) => selectGenerated(...a) } },
}));
const toastSuccess = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: (...a: unknown[]) => toastSuccess(...a), showError: vi.fn() }),
}));
const generatorDialog = vi.fn();
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: (props: { onEnqueued?: (id: number) => void }) => {
    generatorDialog(props);
    return (
      <button type="button" onClick={() => props.onEnqueued?.(31)}>
        zleć generację
      </button>
    );
  },
}));

import { CompanyCvStaleNotice } from "@/components/v2/recruitment/CompanyCvStaleNotice";
import type { CVBrandedState } from "@/lib/api";
import { dockOriginalCv } from "@/lib/dock-cv-summary";

const uploaded = dockOriginalCv({
  snapshot: {
    has_snapshot: true,
    original_snapshot_at: "2026-10-13T13:10:00Z",
    original_cv_filename: "Anna_CV_2026.pdf",
    original_snapshot_source: "manual_upload",
  },
  snapshotLoading: false,
  profileDocs: undefined,
  profileDocsFailed: false,
});

const draft = {
  status: "draft",
  from_generator: true,
  generated_document_id: 20,
  edit_revision: 3,
  updated_at: "2026-10-13T11:20:00Z",
} as unknown as CVBrandedState;

function renderNotice(branded: CVBrandedState = draft) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyCvStaleNotice
        stageId={900}
        candidateId={41}
        candidateName="Anna Nowak"
        jobId={7}
        branded={branded}
        original={uploaded}
      />
    </QueryClientProvider>,
  );
  return client;
}

describe("CompanyCvStaleNotice — CV firmowe z poprzedniego CV (D3)", () => {
  beforeEach(() => {
    apiGet.mockReset();
    selectGenerated.mockReset();
    toastSuccess.mockReset();
    generatorDialog.mockReset();
    window.localStorage.clear();
  });

  it("szkic starszy niż wgrane CV: ostrzeżenie, „Wygeneruj od nowa” otwiera generator z osobą i rekrutacją", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    renderNotice();
    const user = userEvent.setup();

    expect(await screen.findByText("CV firmowe powstało z poprzedniego CV.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Wygeneruj od nowa/ }));

    expect(generatorDialog).toHaveBeenCalledWith(
      expect.objectContaining({ candidateId: 41, jobId: 7, candidateName: "Anna Nowak" }),
    );
  });

  it("gotowa nowa wersja z nowego CV → „Użyj nowej wersji” podpina ją do etapu", async () => {
    apiGet.mockResolvedValue({
      data: [
        { id: 31, status: "ready", created_at: "2026-10-13T13:20:00Z" },
        { id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" },
      ],
    });
    selectGenerated.mockResolvedValue({ data: { ...draft, generated_document_id: 31 } });
    renderNotice();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Użyj nowej wersji" }));

    await waitFor(() => expect(selectGenerated).toHaveBeenCalledWith(900, 31, 3));
    expect(toastSuccess).toHaveBeenCalledWith("CV firmowe z nowego CV podpięte do tej rekrutacji.");
  });

  it("„Zostaw obecne” chowa ramkę dla tej kopii CV", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    renderNotice();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Zostaw obecne" }));

    expect(screen.queryByTestId("company-cv-stale")).toBeNull();
    expect(window.localStorage.getItem("nexus:company-cv-stale-dismissed:900")).toBe("2026-10-13T13:10:00Z");
  });

  it("zatwierdzone CV firmowe — bez ramki", () => {
    renderNotice({ ...draft, status: "finalized" } as CVBrandedState);
    expect(screen.queryByTestId("company-cv-stale")).toBeNull();
  });
});
