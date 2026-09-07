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
import type { OrderMailDocument, OrderMailSyncStatus } from "@/lib/api/orderMail";

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

function syncStatus(over: Partial<OrderMailSyncStatus> = {}): OrderMailSyncStatus {
  return {
    enabled: true, interval_minutes: 60, autoapply_enabled: false, running: false, started_at: "2031-03-03T08:00:00Z",
    interrupted: false, can_trigger: true,
    last_completed: {
      reason: "manual", started_at: "2031-03-03T08:00:00Z", finished_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      status: "ok", error: null, messages: 3, new_messages: 2, attachments: 2, auto_applied: 1, needs_review: 1,
      unrecognized: 0, duplicates: 0, skipped_existing: 1, ignored_no_pdf: 0, ignored_sender: 0, failed: 0, errors: [],
    },
    ...over,
  };
}

const mailbox = { status: syncStatus(), statusError: false, checking: false, checkError: null, onCheckNow: vi.fn() };

const base = {
  mailbox,
  outcome: "needs_review" as const, onOutcomeChange: vi.fn(), total: 1, selectedId: 1,
  onSelect: vi.fn(), onApply: vi.fn(), onDismiss: vi.fn(), onRetry: vi.fn(), busy: false, applyError: null,
};

describe("OrderMailQueueView", () => {
  it("refreshes the existing plan only with write rights and a saved PDF", () => {
    const onRefreshPlan = vi.fn();
    const { rerender } = render(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} state="ready" items={[doc({ can_apply: true, has_file: true })]} />);
    fireEvent.click(screen.getByRole("button", { name: "Przelicz plan" }));
    expect(onRefreshPlan).toHaveBeenCalledWith(1);
    rerender(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} busy state="ready" items={[doc({ can_apply: true, has_file: true })]} />);
    expect(screen.getByRole("button", { name: "Przelicz plan" })).toBeDisabled();
    rerender(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} state="ready" items={[doc({ can_apply: false, has_file: true })]} />);
    expect(screen.queryByRole("button", { name: "Przelicz plan" })).toBeNull();
  });

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

  it("mailbox panel shows the last check and the button asks for a new one", () => {
    const onCheckNow = vi.fn();
    render(<OrderMailQueueView {...base} mailbox={{ ...mailbox, onCheckNow }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("co 60 min");
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("5 min temu (ręcznie)");
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent(
      "2 nowe wiadomości · 1 zapisane automatycznie · 1 do weryfikacji",
    );
    fireEvent.click(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ }));
    expect(onCheckNow).toHaveBeenCalledTimes(1);
  });

  it("button is absent without rights and busy while the mailbox is being checked", () => {
    const { rerender } = render(
      <OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ can_trigger: false }) }} state="ready" items={[doc()]} />,
    );
    expect(screen.queryByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeNull();
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, checking: true }} state="ready" items={[doc()]} />);
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("Sprawdzam skrzynkę");
    // Bieg planowy trwający po stronie serwera blokuje przycisk tak samo jak własny klik.
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ running: true }) }} state="ready" items={[doc()]} />);
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
  });

  it("interrupted previous run, failed run and disabled ingest are said out loud", () => {
    const { rerender } = render(
      <OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ interrupted: true }) }} state="ready" items={[doc()]} />,
    );
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent("przerwane");
    rerender(
      <OrderMailQueueView
        {...base}
        mailbox={{ ...mailbox, status: syncStatus({ last_completed: { ...syncStatus().last_completed!, status: "error", error: "Graph 401" } }) }}
        state="ready"
        items={[doc()]}
      />,
    );
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent("nie powiodło się: Graph 401");
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ enabled: false }) }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("wyłączone");
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: null, statusError: true }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("Nie udało się pobrać stanu skrzynki");
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
