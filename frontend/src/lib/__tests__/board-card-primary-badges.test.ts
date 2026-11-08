import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  cardBadges,
  cardPrimaryBadges,
  closedRejectBy,
  dlWaitingStatus,
  waitingWorkdaysText,
  type CardBadgeContext,
  type CardBadgeTone,
} from "@/lib/board-card-badges";

const NOW = new Date("2026-11-08T12:00:00Z");

function item(over: Partial<KanbanItem>): KanbanItem {
  return { id: 1, candidate_id: 1, ...over } as KanbanItem;
}

const QC_CTX: CardBadgeContext = {
  column: "cv_qc",
  cproEnabled: false,
  viewerId: 7,
  now: NOW,
  viewerOwnsDlReview: true,
};

describe("U5: jedna liczba dni na karcie", () => {
  it("„Czeka na Ciebie” nie niesie własnej liczby dni kalendarzowych", () => {
    const badges = cardBadges(
      item({
        moved_at: "2026-11-03T09:00:00Z",
        qc: { status: "passed", ok_at: "2026-11-06T09:00:00Z", blocking_failed: 0 } as KanbanItem["qc"],
        waiting_workdays: 0,
      }),
      QC_CTX,
    );
    const review = badges.find((b) => b.key === "dl_review");
    expect(review?.label).toBe("Czeka na Ciebie");
  });

  it("okno „Przesuń dalej” podaje liczbę z serwera, nie z kalendarza", () => {
    const ready = item({
      moved_at: "2026-11-03T09:00:00Z",
      qc: { status: "passed", ok_at: "2026-11-02T09:00:00Z", blocking_failed: 0 } as KanbanItem["qc"],
      waiting_workdays: 3,
    });
    expect(dlWaitingStatus(ready).text).toBe("Czeka u Delivery Leada od 3 dni rob.");
    expect(dlWaitingStatus({ ...ready, waiting_workdays: 0 }).text).toBe("Czeka u Delivery Leada od dziś.");
  });

  it("„44 dni bez odpowiedzi” nie stoi obok liczby z wiersza ruchu", () => {
    const badges = cardBadges(
      item({ days_in_stage: 44, client_silent_workdays: 31, moved_at: "2026-09-25T09:00:00Z" }),
      { ...QC_CTX, column: "cv_sent" }
    );
    const silence = badges.find((b) => b.key === "client_silence");
    expect(silence?.label).toBe("Klient milczy");
    expect(silence?.title).toContain("31 dni rob.");
    expect(silence?.title).toContain("na etapie od 25.09");
  });

  it("„Klient milczy” idzie za serwerem, nie za dniami kalendarza", () => {
    const silence = (over: Partial<KanbanItem>, column: "cv_sent" | "client_interview" | "verified") =>
      cardBadges(item(over), { ...QC_CTX, column }).some((b) => b.key === "client_silence");
    expect(silence({ days_in_stage: 44, client_silent_workdays: null }, "cv_sent")).toBe(false);
    expect(silence({ client_silent_workdays: 6 }, "cv_sent")).toBe(true);
    expect(silence({ client_silent_workdays: 6 }, "client_interview")).toBe(true);
    expect(silence({ client_silent_workdays: 6 }, "verified")).toBe(false);
  });

  it("brak odpowiedzi klienta liczy się w „Zamkniętych” jako „przez klienta”", () => {
    expect(closedRejectBy("client_silent")).toBe("client");
    expect(closedRejectBy("client")).toBe("client");
    expect(closedRejectBy("delivery_lead")).toBe("delivery_lead");
    expect(closedRejectBy(null)).toBe("recruiter");
  });

  it("zapis liczby: „czeka N dni rob.”", () => {
    expect(waitingWorkdaysText(1)).toBe("czeka 1 dzień rob.");
    expect(waitingWorkdaysText(5)).toBe("czeka 5 dni rob.");
  });
});

describe("U1: dwie plakietki i „+N”", () => {
  const ctx: CardBadgeContext = { ...QC_CTX, column: "new", viewerOwnsDlReview: false };
  const b = (key: string, tone: CardBadgeTone = "neutral") => ({
    key,
    label: key,
    tone,
  });
  const keys = (list: { key: string }[]) => list.map((x) => x.key);

  it("blokery przed ruchem z terminem, ruch przed ostrzeżeniem, ostrzeżenie przed stanem", () => {
    const { primary, more } = cardPrimaryBadges(item({}), null, [
      b("stage_prep", "info"),
      b("over_budget", "wait"),
      b("followup", "urgent"),
      b("off_limits", "wait"),
      b("hm_veto", "urgent"),
    ]);
    expect(keys(primary)).toEqual(["hm_veto", "off_limits"]);
    expect(keys(more)).toEqual(["followup", "over_budget", "stage_prep"]);
  });

  it("czarna lista jest blokerem, zwykłe ostrzeżenie o konflikcie już nie", () => {
    const { primary } = cardPrimaryBadges(item({}), null, [
      b("warning_client_nda", "wait"),
      b("warning_blacklisted", "urgent"),
      b("booked_call", "own"),
    ]);
    expect(keys(primary)).toEqual(["warning_blacklisted", "booked_call"]);
  });

  it("„QC: N do poprawy” to ruch, zdane QC to stan, a treść nie ginie", () => {
    const blocking = cardPrimaryBadges(item({}), null, [b("over_budget", "wait"), b("critical_gap", "wait"), b("qc", "urgent")]);
    expect(keys(blocking.primary)).toEqual(["qc", "over_budget"]);
    const passed = cardPrimaryBadges(item({}), null, [b("over_budget", "wait"), b("critical_gap", "wait"), b("qc", "ok")]);
    expect(keys(passed.primary)).toEqual(["over_budget", "critical_gap"]);
    expect(keys(passed.more)).toEqual(["qc"]);
  });

  it("fakty z audytu idą tylko do dymku, także gdy jest miejsce", () => {
    const { primary, more } = cardPrimaryBadges(item({}), null, [
      b("autofill_due", "wait"),
      b("new_in_base", "info"),
      b("other_jobs", "info"),
      b("known_0", "info"),
      b("fresh_slot", "info"),
      b("rating"),
    ]);
    expect(primary).toEqual([]);
    expect(more).toHaveLength(6);
  });

  it("„Czeka na Ciebie” mówi wiersz ruchu: ani plakietki, ani „+N”", () => {
    const { primary, more } = cardPrimaryBadges(
      item({ qc: { status: "passed", ok_at: "2026-11-06T09:00:00Z", blocking_failed: 0 } as KanbanItem["qc"] }),
      QC_CTX,
    );
    expect(keys([...primary, ...more])).not.toContain("dl_review");
  });

  it("karta z „Nowych”: plakietki z `cardBadges` też przechodzą przez priorytet", () => {
    const { primary, more } = cardPrimaryBadges(
      item({
        stage: "new",
        entry_source: "system",
        entry_autofill: {
          score: 81,
          matched_must: [],
          missing_must: [],
          rate_known: true,
          decision_due: true,
          waiting_days: 3,
          cautions: [{ key: "budget", label: "+18% budżetu", title: "ponad budżet" }],
        } as unknown as KanbanItem["entry_autofill"],
      }),
      ctx,
    );
    expect(keys(primary)).toEqual(["autofill_caution_budget", "source"]);
    expect(more.map((x) => x.key)).toEqual(expect.arrayContaining(["autofill_due", "claim"]));
  });
});
