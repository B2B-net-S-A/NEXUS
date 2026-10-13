import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AvailabilityPill } from "@/components/ds/AvailabilityPill";
import { availabilityStatusLabel } from "@/lib/candidate-availability-label";

describe("AvailabilityPill — „czy szuka pracy” zamiast plakietki „Aktywny” (D4, 13.10.2026)", () => {
  it("names the three known states", () => {
    expect(availabilityStatusLabel("actively_looking")).toBe("Szuka aktywnie");
    expect(availabilityStatusLabel("open_to_offers")).toBe("Otwarty na oferty");
    expect(availabilityStatusLabel("not_looking")).toBe("Nie szuka");
  });

  it("renders nothing when the status is unknown or missing — no pill means „nie ustalono”", () => {
    const { container, rerender } = render(<AvailabilityPill status="unknown" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AvailabilityPill status={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AvailabilityPill status="cos_nowego" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the label with the status as a data attribute in both appearances", () => {
    const { rerender } = render(<AvailabilityPill status="actively_looking" />);
    expect(screen.getByText("Szuka aktywnie").closest("[data-availability-status]")).toHaveAttribute(
      "data-availability-status",
      "actively_looking",
    );
    rerender(<AvailabilityPill status="open_to_offers" appearance="text" />);
    expect(screen.getByText("Otwarty na oferty")).toBeInTheDocument();
  });
});
