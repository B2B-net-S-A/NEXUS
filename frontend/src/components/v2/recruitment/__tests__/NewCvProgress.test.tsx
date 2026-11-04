import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const brandedGet = vi.fn();
const regenerate = vi.fn();
const restorePrevious = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  candidateStageCvApi: {
    branded: {
      get: (...a: unknown[]) => brandedGet(...a),
      regenerateFromOriginal: (...a: unknown[]) => regenerate(...a),
      restorePrevious: (...a: unknown[]) => restorePrevious(...a),
    },
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { NewCvProgress } from "@/components/v2/recruitment/NewCvProgress";
import { newCvUploadKey, type NewCvUpload } from "@/lib/new-cv-upload";

const base: NewCvUpload = {
  at: Date.now(),
  filename: "Anna_CV_2026.pdf",
  documentId: 55,
  plan: "ask",
  companyStageId: 880,
  companyStatus: "finalized",
  regeneratingId: null,
  snapshotAt: "2026-10-29T10:00:00Z",
};

function renderBlock(upload: NewCvUpload | null, readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(newCvUploadKey(41, 7), upload);
  render(
    <QueryClientProvider client={client}>
      <NewCvProgress candidateId={41} jobId={7} readOnly={readOnly} />
    </QueryClientProvider>,
  );
  return client;
}

describe("NewCvProgress", () => {
  beforeEach(() => {
    brandedGet.mockReset();
    regenerate.mockReset();
    restorePrevious.mockReset();
    brandedGet.mockResolvedValue({ data: { status: "finalized", edit_revision: 6, generated_document_id: 20 } });
  });

  it("bez wgrania nic nie pokazuje", () => {
    renderBlock(null);
    expect(screen.queryByTestId("new-cv-progress")).toBeNull();
  });

  it("zatwierdzone CV: pyta, a „Generuj z nowego CV” zleca generację z bieżącą rewizją", async () => {
    regenerate.mockResolvedValue({ data: { generated_document_id: 31, company_cv_stage_id: 880 } });
    const client = renderBlock(base);

    expect(screen.getByText(/CV do klienta jest już zatwierdzone/)).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: "Generuj z nowego CV" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    await waitFor(() => expect(regenerate).toHaveBeenCalledWith(880, 6));
    expect(client.getQueryData<NewCvUpload>(newCvUploadKey(41, 7))).toMatchObject({
      plan: "regenerating",
      regeneratingId: 31,
    });
    expect(await screen.findByText(/generuje się z nowego CV/)).toBeInTheDocument();
  });

  it("„Zostaw obecne” zamyka blok bez generacji", async () => {
    const client = renderBlock(base);
    await userEvent.click(screen.getByRole("button", { name: "Zostaw obecne" }));
    expect(regenerate).not.toHaveBeenCalled();
    expect(client.getQueryData(newCvUploadKey(41, 7))).toBeNull();
  });

  it("nowa wersja podpięta: „Cofnij” przywraca poprzednie CV", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft", edit_revision: 9, generated_document_id: 31 } });
    restorePrevious.mockResolvedValue({ data: { status: "draft", edit_revision: 10, generated_document_id: 20 } });
    renderBlock({ ...base, plan: "regenerating", companyStatus: "draft", regeneratingId: 31 });

    expect(await screen.findByText(/CV do klienta z nowego CV/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cofnij" }));
    await waitFor(() => expect(restorePrevious).toHaveBeenCalledWith(880, 9));
  });

  it("bez prawa zapisu nie ma przycisków", () => {
    renderBlock(base, true);
    expect(screen.queryByRole("button", { name: "Generuj z nowego CV" })).toBeNull();
  });

  it("brak CV do klienta: mówi, że plik jest potwierdzony", () => {
    renderBlock({ ...base, plan: "confirm", companyStatus: "none" });
    expect(screen.getByText(/Plik jest już potwierdzony/)).toBeInTheDocument();
    expect(brandedGet).toHaveBeenCalled();
  });
});
