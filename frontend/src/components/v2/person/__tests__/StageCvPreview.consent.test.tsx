/**
 * Brak zgody przy CV etapu (05.11.2026): podgląd pokazywał sam komunikat serwera
 * bez przycisków, a Delivery Lead nie wiedział, co z nim zrobić.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), load: vi.fn(), attach: null as null | Record<string, unknown> }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));
vi.mock("@/lib/docx-preview-safe", () => ({ renderDocxSafely: async () => undefined }));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/docx-fit", () => ({ observeDocxFit: () => undefined }));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({
  ConsentAttachButton: (props: Record<string, unknown>) => {
    mocks.attach = props;
    return <button type="button">Wgraj zrzut maila</button>;
  },
}));
vi.mock("@/components/v2/recruitment/ConsentRequestButton", () => ({
  ConsentRequestButton: () => <button type="button">Poproś kandydata o zgodę</button>,
}));

import { StageCvPreview } from "../StageCvPreview";

function mount(branded: Record<string, unknown>, props: { readOnly?: boolean } = {}) {
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/cv/branded") ? { data: branded } : { data: [] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StageCvPreview candidateId={7} jobId={3} cvStageId={5} loadStageCvFile={mocks.load} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.attach = null;
  mocks.load.mockRejectedValue(new Error("409"));
});

describe("StageCvPreview: brak zgody przy CV etapu", () => {
  it("pokazuje prośbę i wgranie zrzutu do dokumentu generatora, bez przycisku pobrania", async () => {
    mount({ status: "draft", consent_missing: true, generated_document_id: 41 });
    await screen.findByTestId("dl-review-consent-missing");
    expect(screen.getByRole("button", { name: /Poproś kandydata o zgodę/ })).toBeInTheDocument();
    expect(mocks.attach).toMatchObject({ generatedId: 41, hasConsent: false });
    expect(screen.queryByRole("button", { name: /Pobierz DOCX/ })).not.toBeInTheDocument();
  });

  it("CV bez dokumentu generatora dostaje zgodę na etap, na którym leży", async () => {
    mount({ status: "draft", consent_missing: true, generated_document_id: null });
    await screen.findByTestId("dl-review-consent-missing");
    expect(mocks.attach).toMatchObject({ stageCopy: { candidateId: 7, stageId: 5 } });
  });

  it("bez prawa zapisu zostaje sama informacja", async () => {
    mount({ status: "draft", consent_missing: true, generated_document_id: 41 }, { readOnly: true });
    await screen.findByTestId("dl-review-consent-missing");
    expect(screen.queryByRole("button", { name: /Poproś kandydata o zgodę/ })).not.toBeInTheDocument();
    expect(mocks.attach).toBeNull();
  });

  it("zgoda jest: zwykły podgląd pliku", async () => {
    mocks.load.mockResolvedValue({ blob: new Blob(["x"]) });
    mount({ status: "draft", consent_missing: false, generated_document_id: 41 });
    await waitFor(() => expect(mocks.load).toHaveBeenCalled());
    expect(screen.queryByTestId("dl-review-consent-missing")).not.toBeInTheDocument();
  });
});
