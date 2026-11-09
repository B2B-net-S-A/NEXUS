/**
 * Porcja dnia (07.11.2026), makieta M7: decyzja jednym klawiszem, bez
 * pomijania. „Do screeningu” i „Odrzuć” idą przez `usePipelineMoveCore`
 * (ta sama droga co Tablica); odrzucenie bez maila do kandydata, z powodem
 * dla systemu, przy braku umiejętności — z nazwą umiejętności.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { orderLine, ReviewBatchCard, rejectMissing } from "@/components/v2/review-batch/ReviewBatchCard";
import type { ReviewBatchItem } from "@/lib/api/reviewBatch";

const move = vi.hoisted(() => ({
  send: vi.fn(async () => ({ ok: true as const, data: {} })),
}));

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: move.send, dialogs: null }),
}));
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({
    rejectionReasons: [
      { id: "41", label: "Nie spełnia wymagań technicznych", name: "Nie spełnia wymagań technicznych", applies_to: ["rejected"] },
      { id: "49", label: "Inne", name: "Inne", applies_to: ["rejected"] },
    ],
  }),
}));

const item: ReviewBatchItem = {
  process_id: 7,
  stage_id: 70,
  job_id: 789176,
  job_title: "Senior Fullstack developer",
  candidate_id: 67003,
  name: "Aliaksei",
  city: "Gdańsk",
  years: 8,
  position: null,
  score: 78.16,
  matched_must: ["java", "angular"],
  missing_must: ["spring boot"],
  rate_from_hourly: 115,
  rate_currency: "PLN",
  availability_status: "actively_looking",
  cautions: [],
  budget_hourly: 130,
};

beforeEach(() => {
  move.send.mockClear();
});

describe("ReviewBatchCard", () => {
  it("pokazuje powód dopasowania bez otwierania profilu", () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    expect(screen.getByText("78%")).toBeInTheDocument();
    expect(screen.getByText("✓ java")).toBeInTheDocument();
    expect(screen.getByText("? spring boot")).toBeInTheDocument();
    expect(screen.getByText("Aktywnie szuka")).toBeInTheDocument();
    expect(screen.getByText("od 115 zł/h · budżet 130")).toBeInTheDocument();
    expect(screen.queryByText(/Pomiń/)).not.toBeInTheDocument();
  });

  it("klawisz S przenosi na screening przez wspólny ruch", async () => {
    const onDecided = vi.fn();
    render(<ReviewBatchCard item={item} onDecided={onDecided} />);
    fireEvent.keyDown(window, { key: "s" });
    await vi.waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(move.send).toHaveBeenCalledWith(
      { candidate_id: 67003, job_id: 789176, stage: "screening" },
      { candidateName: "Aliaksei" },
    );
  });

  it("odrzucenie: brak umiejętności wymaga nazwy, idzie bez maila i z powodem dla systemu", async () => {
    const user = userEvent.setup();
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByTestId("review-reject-confirm")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "spring boot" }));
    await user.click(screen.getByTestId("review-reject-confirm"));
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload).toMatchObject({
      stage: "rejected",
      send_rejection_email: false,
      notes: "Brak: spring boot",
      autofill_reason: "missing_skill",
      autofill_learned_from: "profile",
      rejection_reason_id: "41",
    });
  });

  it("„Nie szuka pracy” zapisuje datę, do kiedy", async () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "7" });
    fireEvent.keyDown(window, { key: "Enter" });
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload.autofill_reason).toBe("not_looking");
    expect(String(payload.autofill_not_looking_until)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("rejectMissing", () => {
  it("podaje powód kolejności, a przy samym wyniku milczy", () => {
    expect(orderLine(item)).toBeNull();
    expect(orderLine({ ...item, score: 78, order_active: true, order_in_budget: true })).toBe(
      "Kolejność: 78% + aktywnie szuka + stawka w budżecie",
    );
    const known = { points: 8, client_points: 0, note_points: 8, verified_at_client: 0, last_note_days: 12 };
    expect(orderLine({ ...item, score: 70, known })).toBe("Kolejność: 70% + notatka 12 dni temu");
  });

  it("mówi, czego brakuje", () => {
    expect(rejectMissing(null, "")).toMatch(/Wybierz powód/);
    expect(rejectMissing("missing_skill", " ")).toMatch(/umiejętności/);
    expect(rejectMissing("other", "")).toMatch(/Opisz/);
    expect(rejectMissing("too_junior", "")).toBe("");
  });
});
