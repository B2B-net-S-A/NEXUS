import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobHoldPopoverSection } from "@/components/v2/jobs/hold/JobHoldPopoverSection";
import { holdViewOf, type JobHold } from "@/lib/job-hold";

const BASE: JobHold = {
  job_id: 7,
  state: "searching",
  reason: null,
  review_on: null,
  since: "2026-10-20T08:00:00",
  by_id: 61,
  by_name: "Gosia Delivery",
  can_manage: false,
  recipients: [],
  my_open_report: null,
};

function renderSection(hold: JobHold, canReport = true) {
  const handlers = {
    onHold: vi.fn(),
    onResume: vi.fn(),
    onEdit: vi.fn(),
    onReport: vi.fn(async () => true),
  };
  render(<JobHoldPopoverSection hold={hold} view={holdViewOf(hold)} canReport={canReport} {...handlers} />);
  return handlers;
}

describe("JobHoldPopoverSection", () => {
  it("DL przy „Szukamy”: „Wstrzymaj rekrutację…”", () => {
    const h = renderSection({ ...BASE, can_manage: true });
    expect(screen.getByText("Szukamy kandydatów")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("job-hold-popover-hold"));
    expect(h.onHold).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Słyszysz, że klient wstrzymał?")).not.toBeInTheDocument();
  });

  it("DL przy wstrzymanej: „Wznów” i „Zmień powód lub termin…”", () => {
    const h = renderSection({ ...BASE, can_manage: true, state: "on_hold", reason: "Zmiana zakresu" });
    expect(screen.getByText("Wstrzymana przez klienta")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("job-hold-popover-resume"));
    fireEvent.click(screen.getByRole("button", { name: "Zmień powód lub termin…" }));
    expect(h.onResume).toHaveBeenCalledTimes(1);
    expect(h.onEdit).toHaveBeenCalledTimes(1);
  });

  it("rekruter zgłasza DL-owi z notatką", async () => {
    const h = renderSection(BASE);
    fireEvent.change(screen.getByLabelText("Słyszysz, że klient wstrzymał?"), {
      target: { value: "Projekt stoi do stycznia" },
    });
    fireEvent.click(screen.getByTestId("job-hold-report"));
    await waitFor(() => expect(h.onReport).toHaveBeenCalledWith("Projekt stoi do stycznia"));
  });

  it("po zgłoszeniu: data zamiast pola; bez prawa zapisu — sam stan", () => {
    renderSection({ ...BASE, my_open_report: { at: "2026-11-26T09:53:00", note: "" } });
    expect(screen.getByTestId("job-hold-reported")).toHaveTextContent("Zgłoszono DL-owi 26.11");
    expect(screen.queryByTestId("job-hold-report")).not.toBeInTheDocument();
  });

  it("czytelnik bez zapisu nie ma pola zgłoszenia", () => {
    renderSection(BASE, false);
    expect(screen.queryByTestId("job-hold-report")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-hold-popover-hold")).not.toBeInTheDocument();
  });
});
