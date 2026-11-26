import { describe, expect, it } from "vitest";

import {
  addDaysIso,
  defaultReviewOn,
  holdMoveWarning,
  holdSignalText,
  holdViewOf,
  isHoldExemptMove,
  reviewDistanceText,
  validateHoldForm,
  type JobHold,
} from "@/lib/job-hold";
import { holdChecksAudience } from "@/lib/job-hold-audience";
import { REQUEST_STAGE_CHIPS, REQUEST_STAGE_META, requestStageOf } from "@/lib/request-stage";
import { requestStatusOf } from "@/lib/request-status";
import { STATE_LABEL, VISIBLE_STATES, visibleState } from "@/lib/request-work-state";

const TODAY = "2026-11-26";

const HOLD: JobHold = {
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

describe("stan „Wstrzymana” w lustrze stanów", () => {
  it("on_hold jest widocznym stanem i champion go nie zmienia", () => {
    expect(VISIBLE_STATES).toContain("on_hold");
    expect(STATE_LABEL.on_hold).toBe("Wstrzymana");
    expect(visibleState("on_hold", null)).toBe("on_hold");
    expect(visibleState("on_hold", "2026-11-20T09:00:00Z")).toBe("on_hold");
  });

  it("lista zna etap i status on_hold, a pigułka filtra stoi na końcu", () => {
    expect(requestStageOf("on_hold")).toBe("on_hold");
    expect(requestStatusOf("on_hold")).toBe("on_hold");
    expect(REQUEST_STAGE_META.on_hold.tone).toBe("hold");
    expect(REQUEST_STAGE_CHIPS.at(-1)).toBe("on_hold");
  });
});

describe("validateHoldForm", () => {
  it("wymaga powodu po przycięciu", () => {
    expect(validateHoldForm({ reason: "   ", reviewOn: null }, TODAY).reason).toBeTruthy();
    expect(validateHoldForm({ reason: "x".repeat(501), reviewOn: null }, TODAY).reason).toMatch(/500/);
    expect(validateHoldForm({ reason: "Zmiana zakresu", reviewOn: null }, TODAY)).toEqual({});
  });

  it("termin od dziś do 120 dni albo pusty", () => {
    expect(validateHoldForm({ reason: "a", reviewOn: "2026-11-25" }, TODAY).reviewOn).toMatch(/przeszłości/);
    expect(validateHoldForm({ reason: "a", reviewOn: TODAY }, TODAY)).toEqual({});
    expect(validateHoldForm({ reason: "a", reviewOn: addDaysIso(TODAY, 120) }, TODAY)).toEqual({});
    expect(validateHoldForm({ reason: "a", reviewOn: addDaysIso(TODAY, 121) }, TODAY).reviewOn).toMatch(/120/);
    expect(validateHoldForm({ reason: "a", reviewOn: "" }, TODAY)).toEqual({});
  });

  it("domyślny termin to dziś + 14 dni, także przez koniec miesiąca", () => {
    expect(defaultReviewOn(TODAY)).toBe("2026-12-10");
    expect(addDaysIso("2026-12-25", 14)).toBe("2027-01-08");
    expect(reviewDistanceText(TODAY, "2026-12-10")).toBe("+2 tyg.");
    expect(reviewDistanceText(TODAY, "2026-11-27")).toBe("jutro");
    expect(reviewDistanceText(TODAY, "2026-11-20")).toBeNull();
  });
});

describe("ostrzeżenie przy ruchu karty", () => {
  it("odrzucenie i rezygnacja nie pytają, ruch naprzód pyta", () => {
    expect(isHoldExemptMove({ stage: "rejected" })).toBe(true);
    expect(isHoldExemptMove({ stage: "withdrawn" })).toBe(true);
    expect(isHoldExemptMove({ stage: "new", rejection_reason_id: 4 })).toBe(true);
    expect(isHoldExemptMove({ stage: "screening" })).toBe(false);
    expect(isHoldExemptMove({ stage: "hired" })).toBe(false);
  });

  it("treść mówi kogo, dokąd, od kiedy, kto, powód i termin", () => {
    const view = holdViewOf(HOLD)!;
    const { title, description } = holdMoveWarning(view, {
      candidateName: "Celina Wzorcowa",
      targetLabel: "Screening",
    });
    expect(title).toBe("Ta rekrutacja jest wstrzymana");
    expect(description).toContain("Celina W. do „Screening”");
    expect(description).toContain("26.11");
    expect(description).toContain("Gosia D.");
    expect(description).toContain("„Klient wstrzymał budżet”");
    expect(description).toContain("DL sprawdzi z klientem 08.12.");
    expect(holdMoveWarning(view, { count: 3 }).description).toContain("3 osoby");
  });

  it("widok wstrzymania: GET wygrywa z polami rekrutacji", () => {
    expect(holdViewOf({ ...HOLD, state: "searching" }, { work_state: "on_hold" })).toBeNull();
    expect(holdViewOf(null, { work_state: "on_hold", hold_reason: "Powód" })?.reason).toBe("Powód");
    expect(holdViewOf(undefined, { work_state: "searching" })).toBeNull();
  });
});

describe("panel „Czy te rekrutacje nadal trwają?”", () => {
  it("zgłoszenie rekrutera mówi, kto pyta", () => {
    expect(
      holdSignalText({ kind: "report", at: "2026-11-26T09:53:00", by_name: "Anna Przykładowa", text: "Stoi?" }),
    ).toBe("Anna P. pyta (26.11): „Stoi?”");
    expect(holdSignalText({ kind: "dl_silent", at: null, text: "Twój ostatni ruch 09.06" })).toBe(
      "Twój ostatni ruch 09.06",
    );
  });

  it("DL widzi swoje, HoR i admin wszystkie, rekruter nic", () => {
    expect(holdChecksAudience({ role: "delivery_lead" } as never)).toEqual({ enabled: true, all: false });
    expect(holdChecksAudience({ role: "head_of_recruitment" } as never)).toEqual({ enabled: true, all: true });
    expect(holdChecksAudience({ role: "recruiter" } as never)).toEqual({ enabled: false, all: false });
    expect(holdChecksAudience(null)).toEqual({ enabled: false, all: false });
  });
});
