import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { GeneratedCvItem } from "@/lib/api";

import { CvResultView } from "../CvResult";

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({ CVBrandedEditModal: () => null }));

function item(partial: Partial<GeneratedCvItem> & Pick<GeneratedCvItem, "id">): GeneratedCvItem {
  return {
    candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 5, client_name: "PKO BP", position: "Java Developer",
    language: "pl", blind: false, mode: "new", content_mode: "tailored", filename: `CV_${partial.id}.docx`,
    status: "ready", warnings: [], can_download: true, can_delete: true, created_at: new Date().toISOString(),
    ...partial,
  };
}

const noop = () => undefined;

function view(documents: GeneratedCvItem[], onRetryPackage = vi.fn()) {
  render(
    <CvResultView
      mainId={1} documents={documents} canWrite onPreview={noop} onEdit={noop} onDownload={noop}
      onRetryPackage={onRetryPackage}
    />,
  );
  return onRetryPackage;
}

// Runda 9 (R9-N3-5): generacja urwana przez deploy da się wznowić bez
// ponownego wypełniania formularza.
describe("CvResultView — przerwana generacja", () => {
  it("pokazuje „Ponów generację” dla wersji głównej przerwanej w trakcie", () => {
    const retry = view([item({ id: 1, status: "failed", job_status: "interrupted", error_message: "przerwana" })]);
    fireEvent.click(screen.getByRole("button", { name: "Ponów generację" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("nie proponuje ponowienia zwykłej porażki generacji", () => {
    view([item({ id: 1, status: "failed", job_status: "failed", error_message: "błąd" })]);
    expect(screen.queryByRole("button", { name: /Ponów/ })).toBeNull();
  });
});
