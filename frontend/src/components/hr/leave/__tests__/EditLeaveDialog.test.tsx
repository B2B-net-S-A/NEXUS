import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    patch: (...a: unknown[]) => patch(...a),
  },
}));

import type { LeaveRequestRow } from "@/lib/api/hr-leave";

import { EditLeaveDialog } from "../EditLeaveDialog";

const ROW: LeaveRequestRow = {
  id: "r1",
  user_id: 11,
  user_name: "Anna Przykładowa",
  leave_type: "vacation",
  leave_type_label: "Urlop wypoczynkowy",
  status: "approved",
  start_date: "2026-11-02",
  end_date: "2026-11-06",
  half_day: null,
  days_total: "5.0",
  paid_days: "5.0",
  unpaid_days: "0.0",
  note: null,
  substitute_user_id: 21,
  substitute_name: "Jan Zastępca",
  forward_mail_consent: true,
  oof_internal_message: null,
  oof_external_message: null,
  decided_by_name: null,
  decided_at: null,
  decision_note: null,
  source: "outlook_oof",
  created_at: null,
  can_cancel: false,
  employment_type: "uop",
};

function renderDialog(row: LeaveRequestRow | null, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EditLeaveDialog request={row} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  // Podpowiedzi zastępców nie mają obecnego zastępcy — okno i tak go pokazuje.
  get.mockResolvedValue({ data: { items: [] } });
});

describe("EditLeaveDialog", () => {
  it("renders nothing without a request", () => {
    renderDialog(null);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sends only the changed dates and closes with the saved row", async () => {
    patch.mockResolvedValue({ data: { ...ROW, end_date: "2026-11-04", days_total: "3.0" } });
    const onClose = renderDialog(ROW);
    const save = await screen.findByRole("button", { name: "Zapisz zmiany" });
    expect(save).toBeDisabled(); // bez zmian nie ma czego zapisać
    expect(screen.getByText(/przekierowanie poczty — reguła przejdzie/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Do"), { target: { value: "2026-11-04" } });
    await userEvent.click(save);
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/hr/leave/approvals/r1", {
        end_date: "2026-11-04",
      }),
    );
    await waitFor(() =>
      expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ days_total: "3.0" })),
    );
  });

  it("shows the server refusal instead of closing", async () => {
    patch.mockRejectedValue({
      response: { status: 409, data: { detail: "Ta osoba ma już zatwierdzony wniosek na 09.11.2026 — wnioski nie mogą się nakładać." } },
    });
    const onClose = renderDialog(ROW);
    fireEvent.change(await screen.findByLabelText("Do"), { target: { value: "2026-11-09" } });
    await userEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wnioski nie mogą się nakładać");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("speaks of a report (no type choice) for B2B", async () => {
    renderDialog({ ...ROW, employment_type: "b2b", is_report: true });
    expect(await screen.findByText("Zmień zgłoszenie")).toBeInTheDocument();
    expect(screen.queryByLabelText("Rodzaj")).not.toBeInTheDocument();
    expect(screen.getByText("Kto przejmie bieżące sprawy")).toBeInTheDocument();
  });
});
