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

describe("usePipelineMoveCore — pozostałe odmowy", () => {
  it("„Anuluj” w ostrzeżeniu kończy ruch odmową bez ponowienia i odświeża tablicę", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "Kandydat ma NDA." }));
    const { send, invalidate } = setup();
    const pending = send();
    fireEvent.click(await screen.findByRole("button", { name: "Anuluj" }));
    await expect(pending).resolves.toMatchObject({ ok: false, refusal: { kind: "eligibility" } });
    expect(move).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 7] });
  });

  it("ostrzeżenie przy ruchu już potwierdzonym nie otwiera okna drugi raz — sam komunikat", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "ELIGIBILITY_WARNING", reason: "Kandydat ma NDA." }));
    const { send } = setup();
    await expect(send({ ...PAYLOAD, acknowledge_eligibility: true })).resolves.toMatchObject({
      ok: false,
      refusal: { kind: "eligibility" },
    });
    expect(screen.queryByRole("button", { name: "Przenieś mimo to" })).toBeNull();
    expect(showError).toHaveBeenCalledWith("Kandydat ma NDA.");
    expect(move).toHaveBeenCalledTimes(1);
  });

  it("bramka „Zweryfikowany”: komunikat i wołający otwiera arkusz z brakami", async () => {
    move.mockRejectedValueOnce(
      refusal(409, { code: "VERIFIED_REQUIREMENTS_MISSING", missing: ["candidate_rate"], message: "Brak stawki" }),
    );
    const onVerifiedMissing = vi.fn();
    const onCvQcFailed = vi.fn();
    const { send } = setup();
    await expect(send(PAYLOAD, { onVerifiedMissing, onCvQcFailed })).resolves.toMatchObject({
      ok: false,
      refusal: { kind: "verified_missing" },
    });
    expect(showError).toHaveBeenCalledWith("Brak stawki");
    expect(onVerifiedMissing).toHaveBeenCalledTimes(1);
    expect(onCvQcFailed).not.toHaveBeenCalled();
  });

  it("konflikt wersji: komunikat i odświeżenie tablicy, ale bez ponowienia ruchu", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "PIPELINE_VERSION_CONFLICT" }));
    const { send, invalidate } = setup();
    await expect(send()).resolves.toMatchObject({ ok: false, refusal: { kind: "version_conflict" } });
    expect(move).toHaveBeenCalledTimes(1);
    expect(showError).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "7"] });
    // Konflikt odświeża tylko tablicę i historię etapów — nie follow-up ani kolejkę.
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["board-tasks"] });
  });

  it("nieznany błąd bez `rethrowOther`: komunikat wołającego, bez wyjątku", async () => {
    move.mockRejectedValueOnce(refusal(500, null));
    const { send } = setup();
    await expect(send(PAYLOAD, { fallbackMessage: "Nie udało się wysłać CV." })).resolves.toEqual({
      ok: false,
      refusal: { kind: "other", message: "Nie udało się wysłać CV." },
    });
    expect(showError).toHaveBeenCalledWith("Nie udało się wysłać CV.");
  });

  it("`rethrowOther` nie dotyczy znanych odmów — bramka wraca wynikiem, nie wyjątkiem", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "CV_QC_FAILED", stage_id: 2 }));
    const { send } = setup();
    await expect(send(PAYLOAD, { rethrowOther: true })).resolves.toMatchObject({
      ok: false,
      refusal: { kind: "cv_qc_failed", message: "CV nie przeszło QC." },
    });
  });

  const twinDetail = {
    code: "TWIN_SCREENING_REQUIRED",
    message: "Osoba idzie też do bliźniaka.",
    twins: [{ job_id: 21, reference_number: "R-21", title: "Analityk testowy" }],
    skip_reasons: { other_profile: "Inny profil" },
  };

  it("bliźniak: pominięcie z powodem ponawia TEN SAM ruch z `twin_skips`", async () => {
    move.mockRejectedValueOnce(refusal(409, twinDetail)).mockResolvedValueOnce({ data: { id: 14 } });
    const { send } = setup();
    const pending = send({ ...PAYLOAD, twin_skips: { "20": "duplicate" } });
    const submit = await screen.findByTestId("twin-skip-submit");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Powód pominięcia — Analityk testowy"), {
      target: { value: "other_profile" },
    });
    fireEvent.click(submit);
    await expect(pending).resolves.toMatchObject({ ok: true, data: { id: 14 } });
    expect(move.mock.calls[1][0]).toEqual({
      ...PAYLOAD,
      twin_skips: { "20": "duplicate", "21": "other_profile" },
    });
  });

  it("bliźniak: „Zamknij” kończy ruch odmową bez ponowienia", async () => {
    move.mockRejectedValueOnce(refusal(409, twinDetail));
    const { send, invalidate } = setup();
    const pending = send();
    await screen.findByTestId("twin-skip-dialog");
    // Okno ma dwa „Zamknij” (krzyżyk i przycisk w stopce) — oba to ta sama decyzja.
    fireEvent.click(screen.getAllByRole("button", { name: "Zamknij" }).at(-1)!);
    await expect(pending).resolves.toMatchObject({ ok: false, refusal: { kind: "twin_required" } });
    expect(move).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 7] });
    await waitFor(() => expect(screen.queryByTestId("twin-skip-dialog")).toBeNull());
  });

  it("debrief bez rozmowy w kalendarzu: okno dostaje `eventId = null` i domyślne imię", async () => {
    move.mockRejectedValueOnce(refusal(409, { code: "DEBRIEF_REQUIRED" })).mockResolvedValueOnce({ data: {} });
    const { send } = setup();
    const pending = send();
    fireEvent.click(await screen.findByRole("button", { name: /zapisz debrief/ }));
    await expect(pending).resolves.toEqual({ ok: true, data: {} });
  });
});

describe("usePipelineMoveCore — mail odrzucenia po ruchu", () => {
  it("zaplanowany mail daje „Cofnij wysyłkę”, które anuluje właściwy mail", async () => {
    move.mockResolvedValueOnce({ data: { id: 15, scheduled_rejection_email_id: 88 } });
    post.mockResolvedValueOnce({});
    const { send } = setup();
    await send({ ...PAYLOAD, stage: "rejected", send_rejection_email: true });
    expect(showActionToast).toHaveBeenCalledWith(
      "Email odrzucenia zostanie wysłany za 15 minut.",
      expect.objectContaining({ actionLabel: "Cofnij wysyłkę" }),
    );
    await showActionToast.mock.calls[0][1].onAction();
    expect(post).toHaveBeenCalledWith("/api/rejection-emails/88/cancel");
    expect(showSuccess).toHaveBeenCalledWith("Anulowano wysyłkę emaila.");
  });

  it("odpowiedź bez treści to nadal udany ruch z pustym wynikiem", async () => {
    move.mockResolvedValueOnce({ data: undefined });
    const { send } = setup();
    await expect(send()).resolves.toEqual({ ok: true, data: {} });
    expect(showActionToast).not.toHaveBeenCalled();
  });
});
