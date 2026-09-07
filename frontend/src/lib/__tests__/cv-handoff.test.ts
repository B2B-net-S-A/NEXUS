/**
 * Sekwencja „Wyślij klientowi" (krok 06 programu „flow w języku C2", PR 6/7).
 *
 * Trzy rzeczy, których nie wolno zgubić: KOLEJNOŚĆ (link przed ruchem, bo
 * ruch tworzy nowy `CandidateStage` bez sfinalizowanego CV; stawka PO ruchu,
 * bo zapisuje się na najnowszym etapie), to, że porażka PRZED ruchem przerywa
 * sekwencję i mówi, co zdążyło się wykonać, oraz to, że porażka stawki PO
 * ruchu jest ostrzeżeniem, nie porażką (ruch jest faktem).
 */

import { describe, expect, it, vi } from "vitest";

import {
  CvHandoffError,
  describeCvHandoffFailure,
  describeCvHandoffSuccess,
  runCvHandoff,
  type CvHandoffPlan,
} from "@/lib/cv-handoff";

function deps(order: string[], overrides: Partial<Record<string, unknown>> = {}) {
  return {
    saveClientRate:
      (overrides.saveClientRate as never) ??
      vi.fn(async () => {
        order.push("client_rate");
      }),
    createShareLink:
      (overrides.createShareLink as never) ??
      vi.fn(async () => {
        order.push("share_link");
        return { shareUrlSuffix: "abc123" };
      }),
    move:
      (overrides.move as never) ??
      vi.fn(async () => {
        order.push("move");
      }),
  };
}

const fullPlan: CvHandoffPlan = {
  clientRate: { value: 25000, unit: "monthly", currency: "PLN" },
  shareLink: { expiresInDays: 14 },
};

describe("runCvHandoff", () => {
  it("idzie w kolejności: link → ruch → stawka", async () => {
    const order: string[] = [];
    const result = await runCvHandoff(fullPlan, deps(order));
    expect(order).toEqual(["share_link", "move", "client_rate"]);
    expect(result.completed).toEqual(["share_link", "move", "client_rate"]);
    expect(result.failedAfterMove).toEqual([]);
    expect(result.shareUrlSuffix).toBe("abc123");
  });

  it("pominięcie kroku jest DECYZJĄ w planie, a nie ciszą", async () => {
    const order: string[] = [];
    const result = await runCvHandoff(
      { clientRate: null, shareLink: null },
      deps(order),
    );
    expect(order).toEqual(["move"]);
    expect(result.skipped).toEqual(["share_link", "client_rate"]);
    expect(result.completed).toEqual(["move"]);
  });

  it("porażka linku zatrzymuje sekwencję PRZED ruchem — nic nie zostało zmienione", async () => {
    const order: string[] = [];
    const d = deps(order, {
      createShareLink: vi.fn(async () => {
        throw new Error("409");
      }),
    });
    const error = await runCvHandoff(fullPlan, d).catch((e) => e);
    expect(error).toBeInstanceOf(CvHandoffError);
    expect((error as CvHandoffError).step).toBe("share_link");
    expect((error as CvHandoffError).completed).toEqual([]);
    expect(d.move).not.toHaveBeenCalled();
    expect(d.saveClientRate).not.toHaveBeenCalled();
  });

  it("porażka ruchu niesie utworzony link (sekret jest zwracany RAZ) i nie zapisuje stawki", async () => {
    const order: string[] = [];
    const d = deps(order, {
      move: vi.fn(async () => {
        throw new Error("409 weto hiring managera");
      }),
    });
    const error = (await runCvHandoff(fullPlan, d).catch(
      (e) => e,
    )) as CvHandoffError;
    expect(error.step).toBe("move");
    expect(error.completed).toEqual(["share_link"]);
    expect(error.shareUrlSuffix).toBe("abc123");
    expect(d.saveClientRate).not.toHaveBeenCalled();
  });

  it("porażka stawki PO ruchu nie jest fatalna — ruch został, stawka raportowana jako niezapisana", async () => {
    const order: string[] = [];
    const d = deps(order, {
      saveClientRate: vi.fn(async () => {
        throw new Error("403 Requires candidate role: ['admin']");
      }),
    });
    const result = await runCvHandoff(fullPlan, d);
    expect(order).toEqual(["share_link", "move"]);
    expect(result.completed).toEqual(["share_link", "move"]);
    expect(result.failedAfterMove).toHaveLength(1);
    expect(result.failedAfterMove[0].step).toBe("client_rate");
  });
});

describe("describeCvHandoffFailure", () => {
  it("mówi, że nic się nie zmieniło, gdy padł pierwszy krok", () => {
    const msg = describeCvHandoffFailure(
      new CvHandoffError("share_link", [], new Error("x")),
      "brak sfinalizowanego CV",
    );
    expect(msg).toContain("brak sfinalizowanego CV");
    expect(msg).toContain("Nic nie zostało zmienione");
  });

  it("po padniętym ruchu ostrzega, że link JUŻ ISTNIEJE i jak nie zrobić drugiego", () => {
    const msg = describeCvHandoffFailure(
      new CvHandoffError("move", ["share_link"], new Error("x"), "abc123"),
      "weto hiring managera",
    );
    expect(msg).toContain("przeniesienie na „CV Wysłane”");
    expect(msg).toContain("utworzenie linku dla klienta");
    expect(msg).toContain("JUŻ ISTNIEJE");
    expect(msg).toContain("odznacz „Utwórz link”");
  });
});

describe("describeCvHandoffSuccess", () => {
  it("nazywa kroki świadomie pominięte bez sugerowania, że stawki brakuje", () => {
    const msg = describeCvHandoffSuccess({
      completed: ["move"],
      skipped: ["share_link", "client_rate"],
      failedAfterMove: [],
      shareUrlSuffix: null,
    });
    expect(msg).toContain("Stawka do klienta bez zmian");
    expect(msg).toContain("Bez linku dla klienta");
  });

  it("stawka padnięta PO ruchu jest nazwana wprost, z powodem i następnym krokiem", () => {
    const msg = describeCvHandoffSuccess(
      {
        completed: ["share_link", "move"],
        skipped: [],
        failedAfterMove: [{ step: "client_rate", reason: new Error("403") }],
        shareUrlSuffix: "abc123",
      },
      (r) => (r instanceof Error ? r.message : ""),
    );
    expect(msg).toContain("Kandydat przeniesiony");
    expect(msg).toContain("NIE udało się zapisać");
    expect(msg).toContain("403");
    expect(msg).toContain("uzupełnij ją z profilu kandydata");
    expect(msg).toContain("Link dla klienta utworzony");
  });
});
