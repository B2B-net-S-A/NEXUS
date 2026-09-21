import { describe, expect, it, vi } from "vitest";

import {
  BULK_CV_CANCELLED_REASON,
  BULK_CV_MOVE_UNKNOWN_REASON,
  BULK_CV_MOVED_WITHOUT_LINK_REASON,
  BULK_CV_NO_BRANDED_REASON,
  runBulkCvHandoff,
  type BulkCvHandoffDeps,
  type BulkCvHandoffPerson,
} from "@/lib/bulk-cv-handoff";
import { CvHandoffError, type CvHandoffResult } from "@/lib/cv-handoff";
import { PIPELINE_VERSION_CONFLICT_MESSAGE } from "@/lib/pipeline-version-conflict";

const person = (id: number, fullName: string): BulkCvHandoffPerson => ({
  candidateId: id,
  fullName,
  sourceStageId: id * 100,
  clientRate: null,
});

const ANNA = person(1, "Anna Nowak");
const JAN = person(2, "Jan Kowalski");

const linked = (suffix: string): CvHandoffResult => ({
  completed: ["move", "share_link"],
  skipped: ["client_rate"],
  failedAfterMove: [],
  shareUrlSuffix: suffix,
});

const httpError = (status: number, detail: unknown = "odmowa") => ({
  response: { status, data: { detail } },
});
const ELIGIBILITY = httpError(409, { code: "ELIGIBILITY_WARNING", reason: "Weto HM" });
const CONFLICT = httpError(409, { code: "PIPELINE_VERSION_CONFLICT" });

function makeDeps(over: Partial<BulkCvHandoffDeps> = {}): BulkCvHandoffDeps {
  return {
    expiresInDays: 14,
    getBrandedStatus: vi.fn(async () => "finalized"),
    handoff: vi.fn(async (p: BulkCvHandoffPerson) => linked(`/cv/s/${p.candidateId}`)),
    askEligibility: vi.fn(async () => true),
    isEligibilityWarning: (e) => e === ELIGIBILITY,
    isVersionConflict: (e) => e === CONFLICT,
    describeError: (e) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (typeof detail === "string") return detail;
      return e instanceof Error ? e.message : "";
    },
    ...over,
  };
}

describe("runBulkCvHandoff", () => {
  it("dwie osoby → dwa linki, w kolejności wejścia i po kolei (sekwencyjnie)", async () => {
    const order: string[] = [];
    const deps = makeDeps({
      getBrandedStatus: vi.fn(async (stageId: number) => {
        order.push(`status:${stageId}`);
        return "finalized";
      }),
      handoff: vi.fn(async (p: BulkCvHandoffPerson) => {
        order.push(`handoff:${p.candidateId}`);
        return linked(`/cv/s/${p.candidateId}`);
      }),
      onProgress: vi.fn(),
    });
    const outcomes = await runBulkCvHandoff([ANNA, JAN], deps);
    expect(outcomes).toEqual([
      { kind: "linked", candidateId: 1, fullName: "Anna Nowak", sourceStageId: 100, suffix: "/cv/s/1", expiresInDays: 14, rateFailed: null },
      { kind: "linked", candidateId: 2, fullName: "Jan Kowalski", sourceStageId: 200, suffix: "/cv/s/2", expiresInDays: 14, rateFailed: null },
    ]);
    // Status CV sprawdzany na etapie SPRZED ruchu; osoba 2 startuje po osobie 1.
    expect(order).toEqual(["status:100", "handoff:1", "status:200", "handoff:2"]);
    expect(deps.handoff).toHaveBeenNthCalledWith(1, ANNA, false, { createLink: true });
    expect(deps.onProgress).toHaveBeenNthCalledWith(2, 1, 2, JAN);
  });

  it("odmowa ruchu (4xx) → move_refused z powodem, bez ponowienia; następna osoba idzie dalej", async () => {
    const handoff = vi.fn(async (p: BulkCvHandoffPerson) => {
      if (p.candidateId === 1) throw new CvHandoffError("move", [], httpError(422, "Brak stawki"));
      return linked("/cv/s/2");
    });
    const outcomes = await runBulkCvHandoff([ANNA, JAN], makeDeps({ handoff }));
    expect(outcomes[0]).toMatchObject({ kind: "move_refused", candidateId: 1, reason: "Brak stawki" });
    expect(outcomes[0]).not.toHaveProperty("suffix");
    expect(outcomes[1]).toMatchObject({ kind: "linked", candidateId: 2 });
    expect(handoff).toHaveBeenCalledTimes(2);
  });

  it("konflikt wersji → move_refused z komunikatem konfliktu, bez ponowienia", async () => {
    const handoff = vi.fn(async () => {
      throw new CvHandoffError("move", [], CONFLICT);
    });
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff }));
    expect(outcome).toMatchObject({
      kind: "move_refused",
      reason: PIPELINE_VERSION_CONFLICT_MESSAGE,
      // Wołający odświeża po tym historię etapów TEJ osoby (jak pojedynczy przepływ).
      versionConflict: true,
    });
    expect(handoff).toHaveBeenCalledTimes(1);
  });

  it("link padł PO ruchu → moved_no_link z etapem sprzed ruchu i powodem", async () => {
    const handoff = vi.fn(async (): Promise<CvHandoffResult> => ({
      completed: ["move"],
      skipped: [],
      failedAfterMove: [
        { step: "share_link", reason: new Error("CV nie jest sfinalizowane") },
        { step: "client_rate", reason: httpError(403, "Brak uprawnień") },
      ],
      shareUrlSuffix: null,
    }));
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff }));
    expect(outcome).toEqual({
      kind: "moved_no_link",
      candidateId: 1,
      fullName: "Anna Nowak",
      sourceStageId: 100,
      reason: "CV nie jest sfinalizowane",
      expiresInDays: 14,
      rateFailed: "Brak uprawnień",
    });
  });

  it("stawka padła po ruchu, link jest → linked z rateFailed", async () => {
    const handoff = vi.fn(async (): Promise<CvHandoffResult> => ({
      completed: ["move", "share_link"],
      skipped: [],
      failedAfterMove: [{ step: "client_rate", reason: httpError(403, "Brak uprawnień") }],
      shareUrlSuffix: "/cv/s/1",
    }));
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff }));
    expect(outcome).toMatchObject({ kind: "linked", suffix: "/cv/s/1", rateFailed: "Brak uprawnień" });
  });

  it.each([
    ["brak odpowiedzi", new Error("Network Error")],
    ["5xx", httpError(502, "Bad gateway")],
  ])("nieznany wynik ruchu (%s) → move_unknown, handoff wołany RAZ", async (_label, reason) => {
    const handoff = vi.fn(async () => {
      throw new CvHandoffError("move", [], reason);
    });
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff }));
    expect(outcome).toMatchObject({ kind: "move_unknown", reason: BULK_CV_MOVE_UNKNOWN_REASON });
    expect(handoff).toHaveBeenCalledTimes(1);
  });

  it("ostrzeżenie + „Przenieś mimo to” → drugi handoff z potwierdzeniem, dokładnie raz", async () => {
    const handoff = vi.fn(async (_p: BulkCvHandoffPerson, ack: boolean) => {
      if (!ack) throw new CvHandoffError("move", [], ELIGIBILITY);
      return linked("/cv/s/1");
    });
    const askEligibility = vi.fn(async () => true);
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff, askEligibility }));
    expect(askEligibility).toHaveBeenCalledWith(ANNA, ELIGIBILITY);
    expect(handoff.mock.calls.map((c) => c[1])).toEqual([false, true]);
    expect(outcome).toMatchObject({ kind: "linked", suffix: "/cv/s/1" });
  });

  it("ostrzeżenie potwierdzone, ale ponowiony ruch ma nieznany wynik → move_unknown, bez trzeciej próby i drugiego pytania", async () => {
    const handoff = vi.fn(async (_p: BulkCvHandoffPerson, ack: boolean) => {
      throw new CvHandoffError("move", [], ack ? new Error("timeout") : ELIGIBILITY);
    });
    const askEligibility = vi.fn(async () => true);
    const [outcome] = await runBulkCvHandoff([ANNA], makeDeps({ handoff, askEligibility }));
    expect(outcome.kind).toBe("move_unknown");
    expect(handoff).toHaveBeenCalledTimes(2);
    expect(askEligibility).toHaveBeenCalledTimes(1);
  });

  it("ostrzeżenie + „Anuluj” → cancelled, bez drugiego handoffu", async () => {
    const handoff = vi.fn(async () => {
      throw new CvHandoffError("move", [], ELIGIBILITY);
    });
    const [outcome] = await runBulkCvHandoff(
      [ANNA],
      makeDeps({ handoff, askEligibility: vi.fn(async () => false) }),
    );
    expect(outcome).toMatchObject({ kind: "cancelled", reason: BULK_CV_CANCELLED_REASON });
    expect(handoff).toHaveBeenCalledTimes(1);
  });

  it("brak sfinalizowanego CV firmowego → skipped, handoff NIGDY nie wołany (osoba nie jest przenoszona)", async () => {
    const handoff = vi.fn(async () => linked("/x"));
    const [outcome] = await runBulkCvHandoff(
      [ANNA],
      makeDeps({ handoff, getBrandedStatus: vi.fn(async () => "draft") }),
    );
    expect(outcome).toMatchObject({ kind: "skipped", reason: BULK_CV_NO_BRANDED_REASON });
    expect(handoff).not.toHaveBeenCalled();
  });

  it("„przenieś bez linku”: brak sfinalizowanego CV → ruch z planem BEZ linku, wynik moved_without_link", async () => {
    const handoff = vi.fn(async (): Promise<CvHandoffResult> => ({
      completed: ["move"], skipped: ["share_link", "client_rate"], failedAfterMove: [], shareUrlSuffix: null,
    }));
    const outcomes = await runBulkCvHandoff(
      [ANNA, JAN],
      makeDeps({
        handoff,
        moveWithoutBrandedCv: true,
        getBrandedStatus: vi.fn(async (stageId: number) => (stageId === 100 ? "draft" : "finalized")),
      }),
    );
    expect(handoff).toHaveBeenNthCalledWith(1, ANNA, false, { createLink: false });
    expect(handoff).toHaveBeenNthCalledWith(2, JAN, false, { createLink: true });
    expect(outcomes[0]).toEqual({
      kind: "moved_without_link", candidateId: 1, fullName: "Anna Nowak", sourceStageId: 100,
      reason: BULK_CV_MOVED_WITHOUT_LINK_REASON, rateFailed: null,
    });
    // Osoba ZE sfinalizowanym CV, której link nie wrócił, to nadal porażka do ponowienia.
    expect(outcomes[1]).toMatchObject({ kind: "moved_no_link", candidateId: 2 });
  });

  it("„przenieś bez linku” nie obejmuje osoby, której CV nie dało się SPRAWDZIĆ", async () => {
    const handoff = vi.fn(async () => linked("/x"));
    const [outcome] = await runBulkCvHandoff(
      [ANNA],
      makeDeps({
        handoff,
        moveWithoutBrandedCv: true,
        getBrandedStatus: vi.fn(async () => {
          throw httpError(500, "Błąd serwera");
        }),
      }),
    );
    expect(outcome.kind).toBe("skipped");
    expect(handoff).not.toHaveBeenCalled();
  });

  it("nie udało się sprawdzić CV firmowego → skipped z powodem, handoff nie wołany", async () => {
    const handoff = vi.fn(async () => linked("/x"));
    const [outcome] = await runBulkCvHandoff(
      [ANNA],
      makeDeps({
        handoff,
        getBrandedStatus: vi.fn(async () => {
          throw httpError(500, "Błąd serwera");
        }),
      }),
    );
    expect(outcome).toMatchObject({
      kind: "skipped",
      reason: "nie udało się sprawdzić CV firmowego: Błąd serwera",
    });
    expect(handoff).not.toHaveBeenCalled();
  });

  it("linki wyłączone: nie sprawdza CV firmowego, nie tworzy linku, tylko oznacza „CV Wysłane”", async () => {
    const getBrandedStatus = vi.fn(async () => "none");
    const handoff = vi.fn(async () => ({ shareUrlSuffix: null, failedAfterMove: [] }));
    const [outcome] = await runBulkCvHandoff(
      [ANNA],
      makeDeps({ linksDisabled: true, getBrandedStatus, handoff: handoff as never }),
    );
    expect(getBrandedStatus).not.toHaveBeenCalled();
    expect(handoff).toHaveBeenCalledWith(ANNA, false, { createLink: false });
    expect(outcome).toMatchObject({
      kind: "moved_without_link",
      reason: "oznaczono „CV Wysłane”",
    });
  });
});
