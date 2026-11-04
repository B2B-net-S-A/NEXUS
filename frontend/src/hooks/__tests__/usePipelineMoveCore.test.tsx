/**
 * Rdzeń ruchu dla ekranów spoza Tablicy (PR 4 ścieżki kandydata): każda
 * odmowa serwera ma tę samą obsługę, niezależnie od ekranu, który wysłał ruch.
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const move = vi.fn();
const post = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const showActionToast = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: (...a: unknown[]) => post(...a) },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast, showSuccess, showError }),
}));
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: (p: { eventId: number; onSaved: () => void; onOpenChange: (o: boolean) => void }) => (
    <div>
      <button type="button" onClick={p.onSaved}>
        zapisz debrief {p.eventId}
      </button>
      <button type="button" onClick={() => p.onOpenChange(false)}>
        zamknij debrief
      </button>
    </div>
  ),
}));

import {
  usePipelineMoveCore,
  type MoveSendHandlers,
  type MoveSendOutcome,
  type PipelineMoveCore,
} from "@/hooks/usePipelineMoveCore";
import { classifyMoveError, type PipelineMovePayload } from "@/lib/pipeline-move-core";

const refusal = (status: number, detail: unknown) =>
  Object.assign(new Error("refused"), { response: { status, data: { detail } } });

const PAYLOAD: PipelineMovePayload = { candidate_id: 3, job_id: 7, stage: "verified" };

function Harness({ onReady }: { onReady: (core: PipelineMoveCore) => void }) {
  const core = usePipelineMoveCore({ jobId: 7 });
  onReady(core);
  return <>{core.dialogs}</>;
}

function setup() {
  let core!: PipelineMoveCore;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness onReady={(c) => (core = c)} />
    </QueryClientProvider>,
  );
  const send = (payload = PAYLOAD, handlers?: MoveSendHandlers): Promise<MoveSendOutcome> =>
    core.send(payload, handlers);
  return { send, invalidate };
}

beforeEach(() => {
  move.mockReset();
  post.mockReset();
  showError.mockReset();
  showSuccess.mockReset();
  showActionToast.mockReset();
});

describe("classifyMoveError", () => {
  it("rozpoznaje każdą odmowę ruchu po kodzie serwera", () => {
    expect(classifyMoveError(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "NDA" })).kind).toBe(
      "eligibility",
    );
    expect(classifyMoveError(refusal(409, { code: "DEBRIEF_REQUIRED", event_id: 5 }))).toMatchObject({
      kind: "debrief_required",
      eventId: 5,
    });
    expect(
      classifyMoveError(
        refusal(409, { code: "VERIFIED_REQUIREMENTS_MISSING", missing: ["candidate_rate"], message: "Brak stawki" }),
      ).kind,
    ).toBe("verified_missing");
    expect(
      classifyMoveError(refusal(409, { code: "CV_QC_FAILED", stage_id: 9, message: "Popraw CV" })),
    ).toMatchObject({ kind: "cv_qc_failed", failure: { stageId: 9 } });
    expect(classifyMoveError(refusal(409, { code: "PIPELINE_VERSION_CONFLICT" })).kind).toBe(
      "version_conflict",
    );
  });

  it("bez powodu od serwera daje zdanie wołającego, nie surowy błąd HTTP", () => {
    expect(classifyMoveError(refusal(500, null), "Nie udało się zapisać.")).toEqual({
      kind: "other",
      message: "Nie udało się zapisać.",
    });
  });
});

describe("usePipelineMoveCore", () => {
  it("udany ruch odświeża oba klucze tablicy", async () => {
    move.mockResolvedValue({ data: { id: 11 } });
    const { send, invalidate } = setup();
    await expect(send()).resolves.toEqual({ ok: true, data: { id: 11 } });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "7"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 7] });
    // Panel osoby: follow-up „Klient milczy”, kolejka i wymagania ruchu
    // (produkcja 05.10.2026 — blok follow-upu został po ruchu na „Umowę”).
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["candidate-followup"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["board-tasks"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["move-requirements"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["candidate-stage-history", 3, 7] });
  });

  it("ostrzeżenie → „Przenieś mimo to” → TEN SAM ruch z potwierdzeniem", async () => {
    move
      .mockRejectedValueOnce(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "Kandydat ma NDA." }))
      .mockResolvedValueOnce({ data: { id: 12 } });
    const { send } = setup();
    const pending = send();
    fireEvent.click(await screen.findByRole("button", { name: "Przenieś mimo to" }));
    await expect(pending).resolves.toMatchObject({ ok: true });
    expect(move.mock.calls[1][0]).toEqual({ ...PAYLOAD, acknowledge_eligibility: true });
  });

  it("brak debriefu → okno rozmowy, po zapisie TEN SAM ruch", async () => {
    move
      .mockRejectedValueOnce(refusal(409, { code: "DEBRIEF_REQUIRED", event_id: 44 }))
      .mockResolvedValueOnce({ data: { id: 13 } });
    const { send } = setup();
    const pending = send(PAYLOAD, { candidateName: "Jan Kowalski" });
    fireEvent.click(await screen.findByRole("button", { name: "zapisz debrief 44" }));
    await expect(pending).resolves.toMatchObject({ ok: true });
    expect(move).toHaveBeenCalledTimes(2);
  });

  it("zamknięte okno debriefu kończy ruch odmową, bez ponowienia", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "DEBRIEF_REQUIRED", event_id: 44 }));
    const { send } = setup();
    const pending = send();
    fireEvent.click(await screen.findByRole("button", { name: "zamknij debrief" }));
    await expect(pending).resolves.toMatchObject({ ok: false, refusal: { kind: "debrief_required" } });
    expect(move).toHaveBeenCalledTimes(1);
  });

  it("QC CV: komunikat serwera i wołający otwiera QC wskazanego etapu", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "CV_QC_FAILED", stage_id: 9, message: "Popraw 2 rzeczy." }));
    const onCvQcFailed = vi.fn();
    const { send } = setup();
    await send(PAYLOAD, { onCvQcFailed });
    expect(showError).toHaveBeenCalledWith("Popraw 2 rzeczy.");
    expect(onCvQcFailed).toHaveBeenCalledWith(expect.objectContaining({ stageId: 9 }));
  });

  it("tryb cichy nie pokazuje komunikatu ani okna — wołający decyduje sam", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "NDA" }));
    const { send } = setup();
    await expect(send(PAYLOAD, { silent: true })).resolves.toMatchObject({
      ok: false,
      refusal: { kind: "eligibility" },
    });
    expect(showError).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Przenieś mimo to" })).toBeNull();
  });

  it("nieudane ponowienie po „Przenieś mimo to” kończy obietnicę błędem (nie wisi)", async () => {
    const timeout = new Error("timeout of 60000ms exceeded");
    move
      .mockRejectedValueOnce(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "NDA" }))
      .mockRejectedValueOnce(timeout);
    const { send } = setup();
    const pending = send(PAYLOAD, { rethrowOther: true });
    fireEvent.click(await screen.findByRole("button", { name: "Przenieś mimo to" }));
    await expect(pending).rejects.toBe(timeout);
  });

  it("`rethrowOther` oddaje nieznany błąd wołającemu (np. limit czasu)", async () => {
    const timeout = new Error("timeout of 60000ms exceeded");
    move.mockRejectedValueOnce(timeout);
    const { send } = setup();
    await expect(send(PAYLOAD, { rethrowOther: true })).rejects.toBe(timeout);
    await waitFor(() => expect(showError).not.toHaveBeenCalled());
  });
});
