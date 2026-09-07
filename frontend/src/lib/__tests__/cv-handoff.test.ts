/**
 * Sekwencja „Wyślij klientowi" (krok 06 programu „flow w języku C2", PR 6/7).
 *
 * Dwie rzeczy, których nie wolno zgubić: KOLEJNOŚĆ (link musi powstać przed
 * ruchem, bo ruch tworzy nowy `CandidateStage` bez sfinalizowanego CV) i to,
 * że porażka jednego kroku PRZERYWA sekwencję i mówi, co zdążyło się wykonać.
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
  it("idzie w kolejności: stawka → link → ruch", async () => {
    const order: string[] = [];
    const result = await runCvHandoff(fullPlan, deps(order));
    expect(order).toEqual(["client_rate", "share_link", "move"]);
    expect(result.completed).toEqual(["client_rate", "share_link", "move"]);
    expect(result.shareUrlSuffix).toBe("abc123");
  });

  it("pominięcie kroku jest DECYZJĄ w planie, a nie ciszą", async () => {
    const order: string[] = [];
    const result = await runCvHandoff(
      { clientRate: null, shareLink: null },
      deps(order),
    );
    expect(order).toEqual(["move"]);
    expect(result.skipped).toEqual(["client_rate", "share_link"]);
    expect(result.completed).toEqual(["move"]);
  });

  it("porażka stawki zatrzymuje sekwencję PRZED linkiem i ruchem", async () => {
    const order: string[] = [];
    const d = deps(order, {
      saveClientRate: vi.fn(async () => {
        throw new Error("422");
      }),
    });
    await expect(runCvHandoff(fullPlan, d)).rejects.toBeInstanceOf(
      CvHandoffError,
    );
    expect(order).toEqual([]);
    expect(d.createShareLink).not.toHaveBeenCalled();
    expect(d.move).not.toHaveBeenCalled();
  });

  it("porażka linku zatrzymuje sekwencję PRZED ruchem i pamięta zapisaną stawkę", async () => {
    const order: string[] = [];
    const d = deps(order, {
      createShareLink: vi.fn(async () => {
        throw new Error("409");
      }),
    });
    const error = await runCvHandoff(fullPlan, d).catch((e) => e);
    expect(error).toBeInstanceOf(CvHandoffError);
    expect((error as CvHandoffError).step).toBe("share_link");
    expect((error as CvHandoffError).completed).toEqual(["client_rate"]);
    expect(d.move).not.toHaveBeenCalled();
  });

  it("porażka ruchu niesie oba wcześniejsze kroki jako wykonane", async () => {
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
    expect(error.completed).toEqual(["client_rate", "share_link"]);
  });
});

describe("describeCvHandoffFailure", () => {
  it("mówi, że nic się nie zmieniło, gdy padł pierwszy krok", () => {
    const msg = describeCvHandoffFailure(
      new CvHandoffError("client_rate", [], new Error("x")),
      "stawka poza zakresem",
    );
    expect(msg).toContain("stawka poza zakresem");
    expect(msg).toContain("Nic nie zostało zmienione");
  });

  it("wylicza kroki, które ZOSTAŁY wykonane, i ostrzega przed powtórzeniem", () => {
    const msg = describeCvHandoffFailure(
      new CvHandoffError("move", ["client_rate", "share_link"], new Error("x")),
      "weto hiring managera",
    );
    expect(msg).toContain("zapis stawki do klienta");
    expect(msg).toContain("utworzenie linku dla klienta");
    expect(msg).toContain("powtórzenie akcji je powtórzy");
  });
});

describe("describeCvHandoffSuccess", () => {
  it("nazywa też kroki świadomie pominięte", () => {
    const msg = describeCvHandoffSuccess({
      completed: ["move"],
      skipped: ["client_rate", "share_link"],
      shareUrlSuffix: null,
    });
    expect(msg).toContain("Bez stawki do klienta");
    expect(msg).toContain("Bez linku dla klienta");
  });
});
