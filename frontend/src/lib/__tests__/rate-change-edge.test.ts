import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}));

import {
  activeProcessesQueryKey,
  notifyLine,
  openCaseLine,
  openRateChange,
  rateArrowLine,
  rateChangeBadgeText,
  rateChangesApi,
  rateChangesQueryKey,
  rateChangeStatusLabel,
  rateTaskLine,
  suggestedClientRate,
  toHourly,
  useRateChanges,
  type RateChange,
  type RateChangeBadge,
  type RateChangeStatus,
  type RateChangesView,
  type RateValue,
} from "@/lib/rate-change";

const rv = (hourly: number | string | null, label = `${hourly} zł/h`): RateValue => ({
  amount: hourly ?? 0,
  unit: "hourly",
  currency: "PLN",
  hourly,
  label,
});

function change(overrides: Partial<RateChange> = {}): RateChange {
  return {
    id: 1,
    status: "requested",
    requires_decision: false,
    board_column: null,
    previous: null,
    requested: rv(130),
    agreed: null,
    source: "manual",
    source_label: "",
    reason: "conversation",
    reason_label: "",
    note: null,
    negotiable: null,
    created_at: "2026-12-31T10:00:00Z",
    created_by_name: null,
    negotiator_id: null,
    negotiator_name: null,
    negotiation_target_hourly: null,
    negotiation_due: null,
    outcome: null,
    outcome_note: null,
    decision: null,
    decided_at: null,
    decided_by_name: null,
    ...overrides,
  };
}

function view(changes: RateChange[]): RateChangesView {
  return {
    candidate_id: 1,
    job_id: 2,
    current: null,
    board_column: null,
    notifies: true,
    cv_at_client: false,
    client_rate: null,
    changes,
  };
}

const BADGE: RateChangeBadge = {
  id: 1,
  status: "requested",
  requires_decision: false,
  previous_hourly: null,
  requested_hourly: null,
  requested_label: "",
  agreed_hourly: null,
  negotiator_name: null,
  negotiation_due: null,
  created_at: null,
};

beforeEach(() => {
  get.mockReset().mockImplementation(async (url: string, config?: unknown) => ({
    data: { url, config },
  }));
  post.mockReset().mockImplementation(async (url: string, body?: unknown) => ({
    data: { url, body },
  }));
});

describe("rateChangesApi — adresy i parametry", () => {
  it("get i activeProcesses wysyłają id w parametrach", async () => {
    expect(await rateChangesApi.get(3, 4)).toEqual({
      url: "/api/rate-changes",
      config: { params: { candidate_id: 3, job_id: 4 } },
    });
    expect(await rateChangesApi.activeProcesses(3)).toEqual({
      url: "/api/rate-changes/active-processes",
      config: { params: { candidate_id: 3 } },
    });
  });

  it("create, negocjacja, wynik i decyzja idą POST-em na swoje adresy", async () => {
    const input = { candidate_id: 1, job_id: 2, amount: "120", unit: "hourly" as const, reason: "email" as const };
    expect(await rateChangesApi.create(input)).toEqual({ url: "/api/rate-changes", body: input });
    expect(await rateChangesApi.negotiate(7, { negotiator_id: 5 })).toMatchObject({
      url: "/api/rate-changes/7/negotiation",
    });
    expect(await rateChangesApi.outcome(7, { outcome: "kept" })).toMatchObject({
      url: "/api/rate-changes/7/outcome",
    });
    expect(
      await rateChangesApi.decide(7, { decision: "raise_client", client_rate: { amount: "150" } }),
    ).toEqual({
      url: "/api/rate-changes/7/decision",
      body: { decision: "raise_client", client_rate: { amount: "150" } },
    });
  });

  it("klucze zapytań", () => {
    expect(activeProcessesQueryKey(9)).toEqual(["rate-changes", "active-processes", 9]);
    expect(rateChangesQueryKey(9, 10)).toEqual(["rate-changes", 9, 10]);
  });
});

describe("useRateChanges", () => {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
      children,
    );

  it("bez kandydata albo rekrutacji nie pyta serwera", () => {
    const { result } = renderHook(() => useRateChanges(null, 2), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    renderHook(() => useRateChanges(1, null), { wrapper });
    expect(get).not.toHaveBeenCalled();
  });

  it("z parą pobiera widok", async () => {
    const { result } = renderHook(() => useRateChanges(1, 2), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith("/api/rate-changes", {
      params: { candidate_id: 1, job_id: 2 },
    });
  });
});

describe("openRateChange", () => {
  it("brak widoku i same zamknięte sprawy: null", () => {
    expect(openRateChange(null)).toBeNull();
    expect(openRateChange(undefined)).toBeNull();
    expect(openRateChange(view([change({ status: "closed" }), change({ status: "noted" })]))).toBeNull();
  });
  it("pierwsza otwarta (najnowsza)", () => {
    const agreed = change({ id: 2, status: "agreed" });
    expect(openRateChange(view([change({ status: "superseded" }), agreed, change({ id: 3 })]))).toBe(agreed);
  });
});

describe("openCaseLine", () => {
  it("zgłoszona bez poprzedniej stawki", () => {
    expect(openCaseLine(change())).toBe("Kandydat chce 130 zł/h · zgłoszona");
  });
  it("CV u klienta: czeka na decyzję DL", () => {
    expect(openCaseLine(change({ requires_decision: true, previous: rv(110) }))).toBe(
      "Kandydat chce 130 zł/h (było 110 zł/h) · CV jest u klienta — czeka na decyzję DL",
    );
  });
  it("negocjacja z osobą i terminem na granicy roku", () => {
    expect(
      openCaseLine(
        change({ status: "negotiating", negotiator_name: "Anna Przykładowa", negotiation_due: "2026-12-31" }),
      ),
    ).toBe("Kandydat chce 130 zł/h · w negocjacji — rozmawia Anna Przykładowa do 31.12");
  });
  it("negocjacja bez osoby i terminu", () => {
    expect(openCaseLine(change({ status: "negotiating" }))).toBe("Kandydat chce 130 zł/h · w negocjacji");
  });
  it("ustalona z kwotą i bez (znak zapytania)", () => {
    expect(openCaseLine(change({ status: "agreed", agreed: rv(120) }))).toBe(
      "Kandydat chce 130 zł/h · ustalona 120 zł/h · decyzja o stawce do klienta należy do DL",
    );
    expect(openCaseLine(change({ status: "agreed" }))).toContain("ustalona ? ·");
  });
});

describe("suggestedClientRate", () => {
  const client = rv(200);
  it("brak stawki klienta, poprzedniej albo nowej: pusto", () => {
    expect(suggestedClientRate(null, change({ previous: rv(100) }))).toBe("");
    expect(suggestedClientRate(undefined, change({ previous: rv(100) }))).toBe("");
    expect(suggestedClientRate(rv(null), change({ previous: rv(100) }))).toBe("");
    expect(suggestedClientRate(client, change())).toBe("");
    expect(suggestedClientRate(client, change({ previous: rv(100), requested: rv(null) }))).toBe("");
  });
  it("obecna + różnica; ustalona wygrywa z żądaną; kwoty tekstowe", () => {
    expect(suggestedClientRate(client, change({ previous: rv(100), requested: rv(130) }))).toBe("230");
    expect(
      suggestedClientRate(client, change({ previous: rv(100), requested: rv(130), agreed: rv(115) })),
    ).toBe("215");
    expect(suggestedClientRate(rv("200.10"), change({ previous: rv("100.05"), requested: rv("110.10") }))).toBe(
      "210.15",
    );
  });
  it("wynik zero albo ujemny: pusto (spadek większy niż stawka klienta)", () => {
    expect(suggestedClientRate(rv(50), change({ previous: rv(100), requested: rv(50) }))).toBe("");
    expect(suggestedClientRate(rv(50), change({ previous: rv(100), requested: rv(10) }))).toBe("");
  });
});

describe("rateTaskLine", () => {
  const row = {
    change_id: 1,
    reason: "decide" as const,
    status: "requested" as RateChangeStatus,
    candidate_id: 1,
    candidate_name: "Jan Testowy",
    job_id: 1,
    job_title: "Tester",
    client_name: null,
    previous_label: null,
    requested_label: "130 zł/h",
    agreed_label: null,
    negotiator_name: null,
    negotiation_due: null,
    since: "2026-12-31",
    waiting_on: null,
  };
  it("sama żądana, z poprzednią i z ustaloną", () => {
    expect(rateTaskLine(row)).toBe("130 zł/h");
    expect(rateTaskLine({ ...row, previous_label: "110 zł/h", agreed_label: "120 zł/h" })).toBe(
      "110 zł/h → 130 zł/h · ustalona 120 zł/h",
    );
  });
});

describe("rateChangeStatusLabel", () => {
  it("wszystkie statusy i nieznany kod", () => {
    expect(rateChangeStatusLabel("noted")).toBe("zmieniona");
    expect(rateChangeStatusLabel("closed")).toBe("zamknięta");
    expect(rateChangeStatusLabel("superseded")).toBe("zastąpiona");
    expect(rateChangeStatusLabel("inny" as RateChangeStatus)).toBe("inny");
  });
});

describe("plakietka i strzałka — brzegi", () => {
  it("negocjacja bez osoby i terminu; termin w złym formacie zostaje", () => {
    expect(rateChangeBadgeText({ ...BADGE, status: "negotiating" })).toBe("w negocjacji");
    expect(rateChangeBadgeText({ ...BADGE, status: "negotiating", negotiation_due: "jutro" })).toBe(
      "w negocjacji do jutro",
    );
  });
  it("ustalona bez kwoty albo z nieliczbową kwotą: znak zapytania", () => {
    expect(rateChangeBadgeText({ ...BADGE, status: "agreed" })).toBe("ustalona ? zł/h · decyzja DL");
    expect(
      rateChangeBadgeText({ ...BADGE, status: "agreed", agreed_hourly: "abc" as unknown as number }),
    ).toBe("ustalona ? zł/h · decyzja DL");
  });
  it("bez poprzedniej stawki: bez strzałki i bez podwójnej spacji; spadek i równość = ↓", () => {
    expect(rateChangeBadgeText(BADGE)).toBe("stawka czeka na DL");
    expect(rateChangeBadgeText({ ...BADGE, previous_hourly: 120, requested_hourly: 100 })).toBe(
      "stawka ↓ czeka na DL",
    );
    expect(rateChangeBadgeText({ ...BADGE, previous_hourly: 100, requested_hourly: 100 })).toBe(
      "stawka ↓ czeka na DL",
    );
  });
  it("strzałka: brak którejś stawki = null; grosze do dwóch miejsc", () => {
    expect(rateArrowLine({ ...BADGE, previous_hourly: 100 })).toBeNull();
    expect(rateArrowLine({ ...BADGE, requested_hourly: 100 })).toBeNull();
    expect(rateArrowLine({ ...BADGE, previous_hourly: 0, requested_hourly: 112.505 })).toMatch(
      /^0 → 112,5[01] zł\/h$/,
    );
  });
});

describe("notifyLine i toHourly — brzegi", () => {
  it("brak widoku: pusto", () => {
    expect(notifyLine(null, { rising: true, reason: "email" })).toBe("");
    expect(notifyLine(undefined, { rising: true, reason: "email" })).toBe("");
  });
  it("CV u klienta, ale spadek albo literówka: bez zadania dla DL", () => {
    const v = { notifies: true, cv_at_client: true };
    expect(notifyLine(v, { rising: false, reason: "email" })).not.toContain("renegocjować");
    expect(notifyLine(v, { rising: true, reason: "typo" })).not.toContain("renegocjować");
    expect(notifyLine(v, { rising: null, reason: "other" })).toContain("renegocjować");
  });
  it("toHourly: zero, ujemna, tekst, przecinek, MD i miesiąc", () => {
    expect(toHourly("0", "hourly")).toBeNull();
    expect(toHourly("-10", "daily")).toBeNull();
    expect(toHourly("abc", "monthly")).toBeNull();
    expect(toHourly("", "hourly")).toBeNull();
    expect(toHourly("120,50", "hourly")).toBe(120.5);
    expect(toHourly("800", "daily")).toBe(100);
    expect(toHourly("16800", "monthly")).toBe(100);
  });
});
