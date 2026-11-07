import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";

describe("QcStatusBadge — trzy stany QC (R1, 07.11.2026)", () => {
  it("zdane bez „sprawdź ręcznie” = „QC: sprawdzone”", () => {
    render(<QcStatusBadge row={{ qc_status: "passed", qc_blocking_failed: 0, qc_manual: [] }} />);
    expect(screen.getByText("QC: sprawdzone")).toBeInTheDocument();
  });

  it("zdane z blokującym „sprawdź ręcznie” mówi, czego nikt nie sprawdził", () => {
    render(
      <QcStatusBadge
        row={{
          qc_status: "passed",
          qc_blocking_failed: 0,
          qc_manual: ["Umiejętności krytyczne są w CV i opisane w rolach"],
        }}
      />,
    );
    const badge = screen.getByText("QC: sprawdź ręcznie · 1");
    expect(badge).toHaveAttribute("title", "Sprawdź ręcznie: Umiejętności krytyczne są w CV i opisane w rolach");
  });

  it("luka kandydata (R2) mówi, czego kandydat nie ma", () => {
    render(<QcStatusBadge row={{ qc_status: "passed", qc_blocking_failed: 0, qc_gaps: ["FastAPI"] }} />);
    expect(screen.getByText("QC: luka kandydata · 1")).toHaveAttribute(
      "title",
      "Kandydat nie ma: FastAPI — o wysyłce decyduje Delivery Lead",
    );
  });

  it("do poprawy z liczbą; brak statusu = nic", () => {
    const { container, rerender } = render(<QcStatusBadge row={{ qc_status: "failed", qc_blocking_failed: 2 }} />);
    expect(screen.getByText("QC: 2 do poprawy")).toBeInTheDocument();
    rerender(<QcStatusBadge row={{ qc_status: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
