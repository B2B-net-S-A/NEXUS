import { AxiosError, AxiosHeaders } from "axios";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { extractErrorMsg } from "@/lib/api";
import {
  PIPELINE_VERSION_CONFLICT_MESSAGE,
  expectedStateVersionOf,
  invalidateAfterPipelineVersionConflict,
  isPipelineVersionConflict,
} from "@/lib/pipeline-version-conflict";

function axiosError(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, null, {
    status,
    statusText: "",
    headers,
    config: { headers },
    data,
  });
}

const CONFLICT_BODY = {
  detail: {
    code: "PIPELINE_VERSION_CONFLICT",
    entity: "process",
    message:
      "Etap tego kandydata został w międzyczasie zmieniony przez inną osobę. Odśwież widok i zdecyduj ponownie.",
    current_state_version: 7,
  },
};

describe("expectedStateVersionOf", () => {
  it("zwraca liczbę z karty, także 0 (brak procesu)", () => {
    expect(expectedStateVersionOf({ process_state_version: 4 })).toBe(4);
    expect(expectedStateVersionOf({ process_state_version: 0 })).toBe(0);
  });

  it("karta bez wersji NIE zgaduje 0 — pole zostaje pominięte", () => {
    expect(expectedStateVersionOf({})).toBeUndefined();
    expect(expectedStateVersionOf({ process_state_version: null })).toBeUndefined();
    expect(expectedStateVersionOf(null)).toBeUndefined();
    expect(expectedStateVersionOf({ process_state_version: -1 })).toBeUndefined();
  });
});

describe("isPipelineVersionConflict", () => {
  it("rozpoznaje 409 z kodem PIPELINE_VERSION_CONFLICT", () => {
    expect(isPipelineVersionConflict(axiosError(409, CONFLICT_BODY))).toBe(true);
    // Obiekt w kształcie błędu axios (np. z mocka) też przechodzi.
    expect(
      isPipelineVersionConflict({ response: { status: 409, data: CONFLICT_BODY } }),
    ).toBe(true);
  });

  it("inne 409 (np. weto HM, karta Pending) to NIE konflikt wersji", () => {
    expect(
      isPipelineVersionConflict(axiosError(409, { detail: "Hiring manager odrzucił" })),
    ).toBe(false);
    expect(
      isPipelineVersionConflict(
        axiosError(409, { detail: { code: "PRIORITY_WORK_LOCKED", message: "x" } }),
      ),
    ).toBe(false);
    expect(isPipelineVersionConflict(axiosError(422, CONFLICT_BODY))).toBe(false);
    expect(isPipelineVersionConflict(new Error("Network Error"))).toBe(false);
  });
});

describe("extractErrorMsg dla konfliktu wersji", () => {
  it("renderuje `detail.message`, gdy `detail` jest obiektem", () => {
    expect(extractErrorMsg(axiosError(409, CONFLICT_BODY))).toBe(
      CONFLICT_BODY.detail.message,
    );
  });
});

describe("invalidateAfterPipelineVersionConflict", () => {
  it("unieważnia OBA klucze tablicy i historię etapów doku", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    invalidateAfterPipelineVersionConflict(qc, 10, 42);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["kanban", "10"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["kanban", 10] });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["candidate-stage-history", 42, 10],
    });
  });

  it("komunikat mówi po polsku, co się stało", () => {
    expect(PIPELINE_VERSION_CONFLICT_MESSAGE).toBe(
      "Kandydat został w międzyczasie przesunięty przez kogoś innego — odświeżyłem kartę.",
    );
  });
});
