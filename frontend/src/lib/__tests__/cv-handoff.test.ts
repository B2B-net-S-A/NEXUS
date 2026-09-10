/**
 * Sekwencja „Wyślij klientowi" (krok 06 programu „flow w języku C2", PR 6/7).
 *
 * Trzy rzeczy, których nie wolno zgubić: KOLEJNOŚĆ (ruch PIERWSZY — link dla
 * klienta to żywy dostęp do CV z sekretem zwracanym raz, więc nie może powstać
 * dla ruchu, którego serwer odmówi; stawka PO ruchu, bo zapisuje się na
 * najnowszym etapie), to, że porażka ruchu przerywa sekwencję, zanim cokolwiek
 * powstanie, oraz to, że porażka linku albo stawki PO ruchu jest
 * ostrzeżeniem, nie porażką (ruch jest faktem).
 */

import { describe, expect, it, vi } from "vitest";

import {
  CvHandoffError,
  computeMarginPreview,
  describeCvHandoffFailure,
  describeCvHandoffSuccess,
  isDefiniteRefusal,
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
  it("idzie w kolejności: ruch → link → stawka", async () => {
    const order: string[] = [];
    const result = await runCvHandoff(fullPlan, deps(order));
    expect(order).toEqual(["move", "share_link", "client_rate"]);
    expect(result.completed).toEqual(["move", "share_link", "client_rate"]);
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

  it("porażka ruchu NIE tworzy linku ani stawki — żywy link do CV nie może zostać po odmowie serwera", async () => {
    const order: string[] = [];
    const d = deps(order, {
      move: vi.fn(async () => {
        throw new Error("409 weto hiring managera");
      }),
    });
    const error = (await runCvHandoff(fullPlan, d).catch(
      (e) => e,
    )) as CvHandoffError;
    expect(error).toBeInstanceOf(CvHandoffError);
    expect(error.step).toBe("move");
    expect(error.completed).toEqual([]);
    expect(d.createShareLink).not.toHaveBeenCalled();
    expect(d.saveClientRate).not.toHaveBeenCalled();
    expect(order).toEqual([]);
  });

  it("porażka linku PO ruchu nie jest fatalna — ruch został, stawka i tak się zapisuje", async () => {
    const order: string[] = [];
    const d = deps(order, {
      createShareLink: vi.fn(async () => {
        throw new Error("502 bramka");
      }),
    });
    const result = await runCvHandoff(fullPlan, d);
    expect(order).toEqual(["move", "client_rate"]);
    expect(result.completed).toEqual(["move", "client_rate"]);
    expect(result.failedAfterMove).toHaveLength(1);
    expect(result.failedAfterMove[0].step).toBe("share_link");
    expect(result.shareUrlSuffix).toBeNull();
  });

  it("porażka stawki PO ruchu nie jest fatalna — ruch został, stawka raportowana jako niezapisana", async () => {
    const order: string[] = [];
    const d = deps(order, {
      saveClientRate: vi.fn(async () => {
        throw new Error("403 Requires candidate role: ['admin']");
      }),
    });
    const result = await runCvHandoff(fullPlan, d);
    expect(order).toEqual(["move", "share_link"]);
    expect(result.completed).toEqual(["move", "share_link"]);
    expect(result.failedAfterMove).toHaveLength(1);
    expect(result.failedAfterMove[0].step).toBe("client_rate");
  });
});

/** Błąd axios z odpowiedzią serwera (odmowa) albo bez niej (limit czasu). */
function httpError(status: number | null, message = "x"): Error {
  return Object.assign(
    new Error(message),
    status === null ? { code: "ECONNABORTED" } : { response: { status } },
  );
}

describe("describeCvHandoffFailure", () => {
  it("po ODMOWIE serwera (4xx) mówi, że nic się nie zmieniło — także link nie powstał", () => {
    const msg = describeCvHandoffFailure(
      new CvHandoffError("move", [], httpError(409)),
      "weto hiring managera",
    );
    expect(msg).toContain("przeniesienie na „CV Wysłane”");
    expect(msg).toContain("weto hiring managera");
    expect(msg).toContain("Nic nie zostało zmienione");
    expect(msg).toContain("link dla klienta nie powstał");
  });

  it("bez odpowiedzi serwera (limit czasu) NIE twierdzi, że nic się nie zmieniło", () => {
    // Ruch mógł się zatwierdzić przed zerwaniem połączenia — ponowienie
    // „bo nic się nie stało" dopisałoby drugi etap „CV Wysłane".
    const msg = describeCvHandoffFailure(
      new CvHandoffError("move", [], httpError(null, "timeout of 60000ms exceeded")),
      "timeout of 60000ms exceeded",
    );
    expect(msg).not.toContain("Nic nie zostało zmienione");
    expect(msg).toContain("Nie wiadomo, czy się udało");
    expect(msg).toContain("Odśwież kartę kandydata");
    expect(msg).toContain("drugi etap „CV Wysłane”");
    expect(msg).toContain("Link dla klienta nie powstał");
  });

  it.each([500, 502, 504])(
    "błąd serwera %i też jest niejednoznaczny — to nie odmowa",
    (status) => {
      const msg = describeCvHandoffFailure(
        new CvHandoffError("move", [], httpError(status)),
        "Bad Gateway",
      );
      expect(msg).not.toContain("Nic nie zostało zmienione");
      expect(msg).toContain("Nie wiadomo, czy się udało");
    },
  );

  it("odmowę od braku odpowiedzi rozróżnia `isDefiniteRefusal`", () => {
    expect(isDefiniteRefusal(httpError(403))).toBe(true);
    expect(isDefiniteRefusal(httpError(422))).toBe(true);
    expect(isDefiniteRefusal(httpError(503))).toBe(false);
    expect(isDefiniteRefusal(httpError(null))).toBe(false);
    expect(isDefiniteRefusal(new Error("Network Error"))).toBe(false);
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
        completed: ["move", "share_link"],
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

  it("link padnięty PO ruchu jest nazwany wprost, z powodem — nie jako „Bez linku”", () => {
    const msg = describeCvHandoffSuccess(
      {
        completed: ["move"],
        skipped: ["client_rate"],
        failedAfterMove: [{ step: "share_link", reason: new Error("502") }],
        shareUrlSuffix: null,
      },
      (r) => (r instanceof Error ? r.message : ""),
    );
    expect(msg).toContain("Linku dla klienta NIE udało się utworzyć");
    expect(msg).toContain("502");
    expect(msg).not.toContain("Bez linku dla klienta");
  });
});

/**
 * Podgląd marży (makieta kroku 06). Najważniejsza asercja jest NEGATYWNA:
 * marży nie wolno policzyć, gdy stawki są w różnych jednostkach — dzienna
 * przeczytana jako godzinowa daje liczbę poprawną arytmetycznie i całkowicie
 * fałszywą handlowo (ta sama pułapka co `rate_unit` w module zamówień).
 */
describe("computeMarginPreview", () => {
  it("liczy różnicę i udział, gdy jednostka i waluta się zgadzają", () => {
    const m = computeMarginPreview({
      clientRate: "165",
      clientUnit: "hourly",
      candidateRate: 118,
      candidateUnit: "hourly",
    });
    expect(m.value).toBe(47);
    expect(m.label).toContain("47");
    expect(m.label).toContain("PLN/h");
    expect(m.label).toContain("28 %");
    expect(m.reason).toBeNull();
  });

  it("przecinek dziesiętny i string z backendu liczą się tak samo", () => {
    const m = computeMarginPreview({
      clientRate: "165,50",
      clientUnit: "daily",
      candidateRate: "118,50",
      candidateUnit: "daily",
    });
    expect(m.value).toBe(47);
  });

  it("różne jednostki → myślnik z powodem, NIGDY przeliczona liczba", () => {
    const m = computeMarginPreview({
      clientRate: "165",
      clientUnit: "hourly",
      candidateRate: 544,
      candidateUnit: "daily",
    });
    expect(m.value).toBeNull();
    expect(m.label).toBe("—");
    expect(m.reason).toContain("Różne jednostki");
  });

  it("różne waluty → myślnik z powodem (kursu nie zgadujemy)", () => {
    const m = computeMarginPreview({
      clientRate: "165",
      clientUnit: "hourly",
      candidateRate: 118,
      candidateUnit: "hourly",
      candidateCurrency: "EUR",
    });
    expect(m.value).toBeNull();
    expect(m.reason).toContain("Różne waluty");
  });

  it("brak którejkolwiek stawki mówi, CZEGO brakuje", () => {
    expect(
      computeMarginPreview({
        clientRate: "",
        clientUnit: "hourly",
        candidateRate: 118,
        candidateUnit: "hourly",
      }).reason,
    ).toContain("Wpisz stawkę do klienta");
    expect(
      computeMarginPreview({
        clientRate: "165",
        clientUnit: "hourly",
        candidateRate: null,
        candidateUnit: "hourly",
      }).reason,
    ).toContain("stawki oczekiwanej");
  });

  it("marża ujemna jest liczona, nie chowana — stawka poniżej kosztu to fakt", () => {
    const m = computeMarginPreview({
      clientRate: "100",
      clientUnit: "hourly",
      candidateRate: 120,
      candidateUnit: "hourly",
    });
    expect(m.value).toBe(-20);
  });
});
