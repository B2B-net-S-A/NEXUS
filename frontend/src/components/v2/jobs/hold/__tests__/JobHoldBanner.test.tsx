import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobHoldBanner } from "@/components/v2/jobs/hold/JobHoldBanner";
import type { HoldView } from "@/lib/job-hold";

const VIEW: HoldView = {
  reason: "Klient wstrzymał projekt do decyzji budżetowej",
  since: "2026-11-26T09:00:00",
  byName: "Gosia Delivery",
  reviewOn: "2026-12-08",
};

describe("JobHoldBanner", () => {
  it("mówi wszystkim od kiedy, kto, powód, zakaz i termin", () => {
    render(<JobHoldBanner view={VIEW} variant="read" />);
    const banner = screen.getByTestId("job-hold-banner");
    expect(banner).toHaveTextContent("Rekrutacja wstrzymana przez klienta · od 26.11 · ustawił(a) Gosia D.");
    expect(banner).toHaveTextContent("„Klient wstrzymał projekt do decyzji budżetowej”");
    expect(banner).toHaveTextContent("Nie proponuj kandydatom tego projektu i nie umawiaj weryfikacji.");
    expect(banner).toHaveTextContent("DL sprawdzi z klientem 08.12.");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("DL: „Wznów rekrutację” i „Zmień termin”", () => {
    const onResume = vi.fn();
    const onChangeTerm = vi.fn();
    render(<JobHoldBanner view={VIEW} variant="manage" onResume={onResume} onChangeTerm={onChangeTerm} />);
    fireEvent.click(screen.getByRole("button", { name: "Wznów rekrutację" }));
    fireEvent.click(screen.getByRole("button", { name: "Zmień termin" }));
    expect(onResume).toHaveBeenCalledTimes(1);
    expect(onChangeTerm).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("job-hold-ask-dl")).not.toBeInTheDocument();
  });

  it("rekruter: „Zapytaj DL”, a po zgłoszeniu kiedy zapytał", () => {
    const onAskDl = vi.fn();
    const { rerender } = render(<JobHoldBanner view={VIEW} variant="recruiter" onAskDl={onAskDl} />);
    fireEvent.click(screen.getByTestId("job-hold-ask-dl"));
    expect(onAskDl).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Wznów rekrutację" })).not.toBeInTheDocument();

    rerender(
      <JobHoldBanner view={VIEW} variant="recruiter" onAskDl={onAskDl} reportedAt="2026-11-26T09:53:00" />,
    );
    expect(screen.queryByTestId("job-hold-ask-dl")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-hold-asked")).toHaveTextContent("Zapytano DL 26.11");
  });

  it("bez powodu i terminu zostaje sam zakaz", () => {
    render(<JobHoldBanner view={{ reason: null, since: null, byName: null, reviewOn: null }} variant="read" />);
    expect(screen.getByTestId("job-hold-banner")).toHaveTextContent(
      "Rekrutacja wstrzymana przez klientaNie proponuj kandydatom",
    );
  });
});
