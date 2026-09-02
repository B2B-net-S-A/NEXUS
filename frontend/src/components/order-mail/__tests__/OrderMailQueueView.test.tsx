/**
 * Kolejka zamówień z maila — warstwa prezentacyjna.
 *
 * Trzy reguły pod testem: awaria renderuje się jako awaria (nie pustka),
 * powody z bramki są treścią ekranu, a „Zastosuj" jest wyłączone dla roli bez
 * prawa zapisu (`can_apply=false`) — przycisk widoczny, nie klikalny, z tytułem
 * wyjaśniającym dlaczego.
 */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrderMailQueueView } from "@/components/order-mail/OrderMailQueue";
import type { OrderMailDocument } from "@/lib/api/orderMail";

function doc(over: Partial<OrderMailDocument> = {}): OrderMailDocument {
  return {
    id: 1, received_at: "2031-03-03T08:00:00Z", sender_email: "x@bank.example", subject: "Zamówienie",
    attachment_name: "z.pdf", outcome: "needs_review", client_id: 1, client_name: "Bank A",
    identification_method: "registry_id", identification_reason: null, client_policy: "PKO BP",
    gate_verdict: "review", gate_reasons: ["„Jan Kowalski”: Dopasowanie z literówką — potwierdź osobę"],
    document_meta: null,
    extraction: { title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Jan Kowalski", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, uncertain: false, uncertain_reason: null }] },
    proposal: { client_id: 1, order_number: "7/2031", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Jan Kowalski", action: "new", candidate_id: 1, contract_id: 2, target_order_id: null, title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, reasons: [] }] },
    applied_order_id: null, applied_at: null, reviewed_at: null, error: null, can_apply: true, has_file: true,
    ...over,
  };
}

const base = {
  outcome: "needs_review" as const, onOutcomeChange: vi.fn(), total: 1, selectedId: 1,
  onSelect: vi.fn(), onApply: vi.fn(), onDismiss: vi.fn(), onRetry: vi.fn(), busy: false, applyError: null,
};

describe("OrderMailQueueView", () => {
  it("renders gate reasons and redacted money as dashes", () => {
    render(<OrderMailQueueView {...base} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("gate-reasons")).toHaveTextContent("Dopasowanie z literówką");
    expect(screen.getByTestId("order-mail-detail")).toHaveTextContent("—");
    expect(screen.getByText("Nowe zamówienie")).toBeInTheDocument();
  });

  it("apply is disabled without rights and calls back with rights", () => {
    const onApply = vi.fn();
    const { rerender } = render(<OrderMailQueueView {...base} onApply={onApply} state="ready" items={[doc({ can_apply: false })]} />);
    const btn = screen.getByRole("button", { name: /Zastosuj/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringContaining("Delivery Leada"));
    rerender(<OrderMailQueueView {...base} onApply={onApply} state="ready" items={[doc({ can_apply: true })]} />);
    fireEvent.click(screen.getByRole("button", { name: /Zastosuj/ }));
    expect(onApply).toHaveBeenCalledWith(1);
  });

  it("error is an error, empty is empty, loading is loading", () => {
    const { rerender } = render(<OrderMailQueueView {...base} state="error" items={[]} total={0} />);
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    rerender(<OrderMailQueueView {...base} state="ready" items={[]} total={0} />);
    expect(screen.getByText("Nic do pokazania")).toBeInTheDocument();
    rerender(<OrderMailQueueView {...base} state="loading" items={[]} total={0} />);
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
  });
});
