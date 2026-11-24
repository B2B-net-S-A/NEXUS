import { describe, expect, it } from "vitest";

import type { NoticeDetail } from "@/lib/api/back-office";

import { REJECT_LABELS, dayLabel, noticeActions } from "../notice-model";

function detail(overrides: Partial<NoticeDetail> = {}): NoticeDetail {
  return {
    id: 7,
    case_id: 70,
    kind: "consultant_notice",
    label: "Wypowiedzenie",
    status: "pending",
    delivered_on: "2026-10-31",
    proposed_last_day: "2026-11-30",
    alternative_last_day: "2026-12-31",
    client_end_date: null,
    contract_number: "1234/2026",
    cpro_number: null,
    agreement: false,
    period_source: "default",
    client_reason: null,
    cpro_event: null,
    evidence: ["załącznik z wypowiedzeniem"],
    reasons: [{ key: "contract_number", label: "numer umowy z maila" }],
    message: null,
    sender_known: false,
    can_remember_sender: true,
    contract: {
      id: 29,
      person: "Jan Testowy",
      client: "Klient Testowy",
      client_id: 5,
      status: "active",
      contract_type: "b2b",
      start_date: "2026-07-01",
      end_date: null,
      terminated_at: null,
      agreement_termination_mode: null,
      exit_case_id: null,
    },
    alternatives: [],
    order: { id: 11, title: "286380", client_id: 5, status: "active", start_date: "2026-10-08", end_date: "2027-01-31" },
    dates: [],
    thread: [],
    decision: null,
    decided_at: null,
    ...overrides,
  };
}

describe("noticeActions", () => {
  it("consultant notice calls the termination route with the chosen last day", () => {
    const [action] = noticeActions(detail(), "2026-12-31");
    expect(action.choice).toBe("confirm");
    expect(action.request?.url).toBe("/api/contracts/29/terminate");
    expect(action.request?.body).toMatchObject({
      termination_reason: "consultant_resigned",
      terminated_at: "2026-12-31",
      agreement_termination: { mode: "notice", party: "consultant", signed_on: "2026-10-31", last_day: "2026-12-31" },
    });
    expect(action.effects.join(" ")).toContain("286380");
  });

  it("agreement uses mutual agreement and no B2B block for other contract types", () => {
    const base = detail({ agreement: true });
    const [b2b] = noticeActions(base, "2026-12-31");
    expect(b2b.request?.body).toMatchObject({ termination_reason: "mutual_agreement" });
    const [other] = noticeActions(
      { ...base, contract: { ...base.contract!, contract_type: "mandate" } },
      "2026-12-31",
    );
    expect(other.request?.body).not.toHaveProperty("agreement_termination");
  });

  it("no action without contract or date", () => {
    expect(noticeActions(detail({ contract: null }), "2026-11-30")).toEqual([]);
    expect(noticeActions(detail(), null)).toEqual([]);
  });

  it("client termination proposes shortening the order line, keep is the alternative", () => {
    const actions = noticeActions(
      detail({ kind: "client_termination", client_end_date: "2026-12-18", proposed_last_day: "2026-12-18" }),
      null,
    );
    expect(actions.map((a) => a.choice)).toEqual(["shorten_order", "keep_order"]);
    expect(actions[0].request).toEqual({
      method: "patch",
      url: "/api/clients/5/orders/11",
      body: { end_date: "2026-12-18" },
    });
    expect(actions[1].request).toBeNull();
  });

  it("CPro end tells that confirming opens the exit case on the chosen day", () => {
    const actions = noticeActions(
      detail({ kind: "client_termination", cpro_event: "not_extended", client_end_date: null }),
      null,
    );
    // „Will not be extended” bez daty: koniec to obecny koniec linii zamówienia.
    expect(actions.map((a) => a.choice)).toEqual(["keep_order"]);
    expect(actions[0].effects.join(" ")).toContain("Sprawa wyjścia z ostatnim dniem 31.01.2027");
    const shorten = noticeActions(
      detail({ kind: "client_termination", cpro_event: "terminated", client_end_date: "2026-12-18" }),
      null,
    )[0];
    expect(shorten.effects.join(" ")).toContain("Sprawa wyjścia z ostatnim dniem 18.12.2026");
    const plain = noticeActions(detail({ kind: "client_termination", client_end_date: "2026-12-18" }), null);
    expect(plain[0].effects.join(" ")).not.toContain("Sprawa wyjścia");
  });

  it("date change equal to the order end only offers keep", () => {
    const actions = noticeActions(detail({ kind: "date_change" }), "2027-01-31");
    expect(actions.map((a) => a.choice)).toEqual(["keep_order"]);
    expect(actions[0].primary).toBe(true);
  });

  it("withdrawal calls the notice withdrawal route", () => {
    const [action] = noticeActions(detail({ kind: "withdrawal" }), null);
    expect(action.request?.url).toBe("/api/contracts/29/notice-withdrawal");
    expect(action.request?.body).toMatchObject({ end_date: null });
  });
});

describe("labels", () => {
  it("formats days and rejection labels", () => {
    expect(dayLabel("2026-11-30")).toBe("30.11.2026");
    expect(dayLabel(null)).toBe("—");
    expect(REJECT_LABELS.withdrawal).toBe("To nie wycofanie");
  });
});

describe("already recorded notice", () => {
  it("does not call the termination route twice", () => {
    const base = detail();
    const [action] = noticeActions(
      { ...base, contract: { ...base.contract!, status: "ending", terminated_at: "2026-12-31", end_date: "2026-12-31" } },
      "2026-12-31",
    );
    expect(action.request).toBeNull();
    expect(action.applied).toMatchObject({ already_recorded: true, last_day: "2026-12-31" });
  });
});
