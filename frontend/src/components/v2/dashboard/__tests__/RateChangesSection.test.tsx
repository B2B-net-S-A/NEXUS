import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RateChangesSection, RateChangesWaitingSection } from "@/components/v2/dashboard/RateChangesSection";
import type { RateChangeTaskRow } from "@/lib/rate-change";

const ROW: RateChangeTaskRow = {
  change_id: 1,
  reason: "decide",
  status: "requested",
  candidate_id: 5,
  candidate_name: "Bartek Testowy",
  job_id: 9,
  job_title: "Java Developer",
  client_name: "Klient A",
  previous_label: "110 zł/h",
  requested_label: "130 zł/h",
  agreed_label: null,
  negotiator_name: null,
  negotiation_due: null,
  since: new Date().toISOString(),
  waiting_on: "Delivery Lead",
};

describe("RateChangesSection", () => {
  it("pokazuje sprawę z linkiem do panelu osoby i tym, co zrobić", () => {
    render(<RateChangesSection rows={[ROW]} />);
    expect(screen.getByRole("link", { name: "Bartek Testowy" })).toHaveAttribute(
      "href",
      "/jobs/9?candidate=5",
    );
    expect(screen.getByTestId("rate-changes-mine")).toHaveTextContent(
      "110 zł/h → 130 zł/h · Zdecyduj o stawce do klienta",
    );
  });

  it("„U innych” mówi, na kogo czeka; pusta lista nic nie rysuje", () => {
    const { container, rerender } = render(<RateChangesWaitingSection rows={[]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RateChangesWaitingSection rows={[{ ...ROW, reason: "waiting" }]} />);
    expect(screen.getByTestId("rate-changes-others")).toHaveTextContent("czeka na: Delivery Lead");
  });
});
