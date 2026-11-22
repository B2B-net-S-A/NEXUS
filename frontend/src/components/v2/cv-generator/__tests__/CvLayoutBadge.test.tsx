/**
 * Odznaka układu tam, gdzie ocenia się CV przed wysyłką (22.11.2026): DL
 * i QC widzą, czy do klienta pójdzie PDF „Nowego CV”, czy plik Word.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CvLayoutBadge, QcLayoutBadge } from "@/components/v2/cv-generator/CvLayoutBadge";
import type { CVBrandedState } from "@/lib/api";

const branded = (over: Partial<CVBrandedState>): CVBrandedState =>
  ({ status: "finalized", version: 2, new_layout_enabled: true, cv_layout: "classic", ...over }) as CVBrandedState;

describe("CvLayoutBadge", () => {
  it("Nowe CV · PDF przy układzie „Nowe CV”", () => {
    render(<CvLayoutBadge branded={branded({ cv_layout: "new" })} />);
    expect(screen.getByTestId("cv-layout-badge")).toHaveTextContent("Nowe CV · PDF");
  });

  it("Klasyczne · Word przy układzie klasycznym", () => {
    render(<CvLayoutBadge branded={branded({ cv_layout: "classic" })} />);
    expect(screen.getByTestId("cv-layout-badge")).toHaveTextContent("Klasyczne · Word");
  });

  it("bez flagi, bez CV i przed odczytem — nic", () => {
    const { container, rerender } = render(
      <CvLayoutBadge branded={branded({ cv_layout: "new", new_layout_enabled: false })} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<CvLayoutBadge branded={branded({ status: "none", cv_layout: "new" })} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<CvLayoutBadge branded={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("w oknie QC układ przychodzi z wyniku QC; brak pola = bez odznaki", () => {
    const { container, rerender } = render(<QcLayoutBadge layout="new" />);
    expect(screen.getByTestId("cv-layout-badge")).toHaveTextContent("Nowe CV · PDF");
    rerender(<QcLayoutBadge layout={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
