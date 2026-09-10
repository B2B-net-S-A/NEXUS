import { forgetCvGenerationRequest } from "../cv-generation-request";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { reviewBeforeFinalize, type CvReviewState } from "../cv-approval-request";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); vi.useFakeTimers(); sessionStorage.clear(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const payload = {content_html: "<p>Claim</p>", expected_revision: 2};
const state = (status: CvReviewState["status"]): CvReviewState => ({review_id: 7, status, error_code: null});

it("waits for verified content before finalization", async () => {
  const transport = {start: vi.fn().mockResolvedValue(state("queued")), get: vi.fn().mockResolvedValue(state("verified")), finalize: vi.fn().mockResolvedValue("approved")};
  const pending = reviewBeforeFinalize("/review/ready", payload, transport);
  await vi.waitFor(() => expect(transport.start).toHaveBeenCalled());
  expect(transport.finalize).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  await expect(pending).resolves.toBe("approved");
  expect(transport.get).toHaveBeenCalledWith(7);
  expect(transport.finalize).toHaveBeenCalledTimes(1);
});

it("preserves the attempt key when polling fails and reconnects without starting a second attempt", async () => {
  const transport = {start: vi.fn().mockResolvedValueOnce(state("running")).mockResolvedValue(state("verified")), get: vi.fn().mockRejectedValue(new Error("offline")), finalize: vi.fn().mockResolvedValue("approved")};
  const pending = expect(reviewBeforeFinalize("/review/reconnect", payload, transport)).rejects.toThrow("offline");
  await vi.waitFor(() => expect(transport.start).toHaveBeenCalled());
  await vi.advanceTimersByTimeAsync(1000);
  await pending;
  expect(transport.finalize).not.toHaveBeenCalled();
  await reviewBeforeFinalize("/review/reconnect", payload, transport);
  expect(transport.start.mock.calls[1][0]).toBe(transport.start.mock.calls[0][0]);
});

it.each(["rejected", "failed", "interrupted", "cancelled", "stale"] as const)("never finalizes or automatically retries %s", async status => {
  const transport = {start: vi.fn().mockResolvedValue(state(status)), get: vi.fn(), finalize: vi.fn()};
  await expect(reviewBeforeFinalize(`/review/${status}`, payload, transport)).rejects.toThrow();
  expect(transport.start).toHaveBeenCalledTimes(1);
  expect(transport.finalize).not.toHaveBeenCalled();
  await expect(reviewBeforeFinalize(`/review/${status}`, payload, transport)).rejects.toThrow();
  expect(transport.start.mock.calls[1][0]).not.toBe(transport.start.mock.calls[0][0]);
});

it("leaving the editor prevents automatic approval when a late review response arrives", async () => {
  const controller = new AbortController();
  let respond!: (value: CvReviewState) => void;
  const transport = {start: vi.fn(() => new Promise<CvReviewState>(resolve => { respond = resolve; })), get: vi.fn(), finalize: vi.fn()};
  const pending = expect(reviewBeforeFinalize("/review/leave", payload, transport, controller.signal)).rejects.toThrow("Przerwano");
  await vi.waitFor(() => expect(transport.start).toHaveBeenCalled());
  controller.abort();
  respond(state("verified"));
  await pending;
  expect(transport.finalize).not.toHaveBeenCalled();
});


it("clears the pending attempt only after acknowledged cancellation", async () => {
  const transport = {start: vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(state("verified")), get: vi.fn(), finalize: vi.fn().mockResolvedValue("approved")};
  await expect(reviewBeforeFinalize("/review/cancel-ack", payload, transport)).rejects.toThrow("offline");
  const original = transport.start.mock.calls[0][0];
  await forgetCvGenerationRequest("/review/cancel-ack", payload);
  await reviewBeforeFinalize("/review/cancel-ack", payload, transport);
  expect(transport.start.mock.calls[1][0]).not.toBe(original);
});
