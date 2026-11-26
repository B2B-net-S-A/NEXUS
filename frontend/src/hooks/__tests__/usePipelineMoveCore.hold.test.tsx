/**
 * Rekrutacja „Wstrzymana” (26.11.2026): ruch karty naprzód spoza Tablicy
 * pyta „Przesuń mimo to” / „Nie przesuwaj” PRZED żądaniem; odrzucenie
 * i rezygnacja idą bez pytania. Ostrzega, nie blokuje.
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const move = vi.fn();
const get = vi.fn();
const post = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast: vi.fn(), showSuccess: vi.fn(), showError }),
}));

import {
  HOLD_DECLINED_MESSAGE,
  usePipelineMoveCore,
  type MoveSendOutcome,
  type PipelineMoveCore,
} from "@/hooks/usePipelineMoveCore";
import type { PipelineMovePayload } from "@/lib/pipeline-move-core";

const HOLD = {
  job_id: 7,
  state: "on_hold",
  reason: "Klient wstrzymał budżet",
  review_on: "2026-12-08",
  since: "2026-11-26T09:00:00",
  by_id: 61,
  by_name: "Gosia Delivery",
  can_manage: false,
  recipients: [],
  my_open_report: null,
};

function Harness({ onReady }: { onReady: (core: PipelineMoveCore) => void }) {
  const core = usePipelineMoveCore({ jobId: 7 });
  onReady(core);
  return <>{core.dialogs}</>;
}

function setup() {
  let core!: PipelineMoveCore;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness onReady={(c) => (core = c)} />
    </QueryClientProvider>,
  );
  return (payload: PipelineMovePayload, candidateName = "Celina Wzorcowa"): Promise<MoveSendOutcome> =>
    core.send(payload, { candidateName });
}

beforeEach(() => {
  move.mockReset();
  get.mockReset();
  post.mockReset();
  showError.mockReset();
  move.mockResolvedValue({ data: { id: 1 } });
});

describe("usePipelineMoveCore — rekrutacja wstrzymana", () => {
  it("„Nie przesuwaj” = bez żądania i bez komunikatu błędu", async () => {
    get.mockResolvedValue({ data: HOLD });
    const send = setup();
    let outcome: MoveSendOutcome | undefined;
    void send({ candidate_id: 3, job_id: 7, stage: "screening" }).then((o) => (outcome = o));

    expect(await screen.findByText("Ta rekrutacja jest wstrzymana")).toBeInTheDocument();
    expect(screen.getByText(/Przesuwasz kartę: Celina W\. → „Screening”/)).toBeInTheDocument();
    expect(screen.getByText(/„Klient wstrzymał budżet”/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nie przesuwaj" }));

    await waitFor(() => expect(outcome).toBeDefined());
    expect(outcome).toEqual({ ok: false, refusal: { kind: "hold_declined", message: HOLD_DECLINED_MESSAGE } });
    expect(move).not.toHaveBeenCalled();
    expect(showError).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledWith("/api/jobs/7/hold");
  });

  it("„Przesuń mimo to” wysyła ten sam ruch", async () => {
    get.mockResolvedValue({ data: HOLD });
    const send = setup();
    const pending = send({ candidate_id: 3, job_id: 7, stage: "verified" });
    fireEvent.click(await screen.findByRole("button", { name: "Przesuń mimo to" }));
    await expect(pending).resolves.toMatchObject({ ok: true });
    expect(move).toHaveBeenCalledWith({ candidate_id: 3, job_id: 7, stage: "verified" });
  });

  it("odrzucenie nie pyta i nie czyta stanu wstrzymania", async () => {
    get.mockResolvedValue({ data: HOLD });
    const send = setup();
    await expect(
      send({ candidate_id: 3, job_id: 7, stage: "rejected", rejection_reason_id: 4 }),
    ).resolves.toMatchObject({ ok: true });
    expect(screen.queryByText("Ta rekrutacja jest wstrzymana")).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });

  it("rekrutacja niewstrzymana — bez pytania", async () => {
    get.mockResolvedValue({ data: { ...HOLD, state: "searching" } });
    const send = setup();
    await expect(send({ candidate_id: 3, job_id: 7, stage: "screening" })).resolves.toMatchObject({
      ok: true,
    });
    expect(screen.queryByText("Ta rekrutacja jest wstrzymana")).not.toBeInTheDocument();
  });

  it("stan nieczytelny (trasa nie odpowiada) — ruch idzie bez pytania", async () => {
    get.mockRejectedValue(new Error("404"));
    const send = setup();
    await expect(send({ candidate_id: 3, job_id: 7, stage: "screening" })).resolves.toMatchObject({
      ok: true,
    });
    expect(move).toHaveBeenCalledTimes(1);
  });
});
