import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CandidateBulkBar } from "../CandidateBulkBar";

function open(onDownloadCvs?: () => void) {
  render(
    <CandidateBulkBar
      count={2}
      onAddToRecruitment={vi.fn()}
      onCompare={vi.fn()}
      onDownloadCvs={onDownloadCvs}
      downloadingCvs={false}
      onAddToPool={vi.fn()}
      addingToPool={false}
      onClear={vi.fn()}
    />,
  );
  fireEvent.pointerDown(screen.getByRole("button", { name: /Więcej/ }), { button: 0, ctrlKey: false });
}

describe("CandidateBulkBar — paczka ZIP", () => {
  it("bez akcji pobrania nie ma pozycji ZIP (sama rola rekrutera)", async () => {
    open();
    await screen.findByRole("menuitem", { name: /Na listę albo do puli/ });
    expect(screen.queryByRole("menuitem", { name: /ZIP/ })).toBeNull();
  });

  it("z akcją pobrania pozycja zostaje", async () => {
    open(vi.fn());
    expect(await screen.findByRole("menuitem", { name: /Pobierz CV \(ZIP\)/ })).toBeInTheDocument();
  });
});
