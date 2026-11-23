import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";

describe("QcStatusBadge — trzy stany QC (R1, 07.11.2026)", () => {
  it("zdane bez „sprawdź ręcznie” = „QC: sprawdzone”", () => {
    render(<QcStatusBadge row={{ qc_status: "passed", qc_blocking_failed: 0 }} />);
    expect(screen.getByText("QC: sprawdzone")).toBeInTheDocument();
  });

  it("QC-11: pokazuje gotowy stan z serwera, z tonem i dymkiem", () => {
    render(
      <QcStatusBadge
        row={{
          qc_status: "passed",
          qc_blocking_failed: 0,
          qc_state: { kind: "verify_roles", n: 2, items: ["Kafka", "AWS"], text: "QC: wskaż stanowisko · 2", tone: "wait", who: null, hint: "Nikt nie sprawdził opisu w rolach: Kafka, AWS." },
        }}
      />,
    );
    expect(screen.getByText("QC: wskaż stanowisko · 2")).toHaveAttribute("title", "Nikt nie sprawdził opisu w rolach: Kafka, AWS.");
  });

  it("do poprawy z liczbą; brak statusu = nic", () => {
    const { container, rerender } = render(<QcStatusBadge row={{ qc_status: "failed", qc_blocking_failed: 2 }} />);
    expect(screen.getByText("QC: 2 do poprawy")).toBeInTheDocument();
    rerender(<QcStatusBadge row={{ qc_status: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("klient z formularzem CV: stan formularza zamiast wyniku QC CV firmowego (23.11.2026)", () => {
    const { rerender } = render(
      <QcStatusBadge row={{ qc_status: "failed", qc_blocking_failed: 1, client_form: { template: true, missing: 3 } }} />,
    );
    expect(screen.getByTestId("client-form-status-badge")).toHaveTextContent("Formularz: 3 do uzupełnienia");
    expect(screen.queryByText(/QC:/)).toBeNull();
    rerender(<QcStatusBadge row={{ qc_status: null, client_form: { template: true, missing: 0 } }} />);
    expect(screen.getByText("Formularz gotowy")).toBeInTheDocument();
    rerender(<QcStatusBadge row={{ qc_status: "passed", client_form: { template: false, missing: null } }} />);
    expect(screen.getByText("Formularz: brak wzoru")).toBeInTheDocument();
  });
});
