/**
 * Audyt 48 h (13.10.2026): Tablica liczyła „Czeka na Ciebie” inaczej niż pas
 * „Do wysłania do klienta” — wliczała karty z importu Traffita i karty
 * zamkniętej rekrutacji. Serwer mówi to polem karty `dl_send_counts`
 * (lustro `dl_send_queue.counts_for_reviewer`).
 */
import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  MY_MOVE_LABEL,
  cardBadges,
  cardNextStep,
  countsForDlReview,
  dlSendQueue,
  isReadyForDlSend,
  type CardBadgeContext,
} from "@/lib/board-card-badges";

const NOW = new Date("2026-09-23T10:00:00Z");
const action = { label: "Popraw CV / wyślij", owner: "recruiter", kind: "cv" };

function item(extra: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 1,
    candidate_id: 11,
    stage: "interview",
    days_in_stage: 1,
    qc: { status: "passed", blocking_failed: 0 },
    ...extra,
  } as KanbanItem;
}

function ctx(extra: Partial<CardBadgeContext> = {}): CardBadgeContext {
  return { column: "cv_qc", cproEnabled: false, viewerId: 7, now: NOW, viewerOwnsDlReview: true, ...extra };
}

describe("„Czeka na Ciebie” na Tablicy jak pas „Do wysłania”", () => {
  const excluded = item({ dl_send_counts: false });

  it("karta poza kolejką DL-a (import Traffita, zamknięta rekrutacja) nie czeka na Ciebie", () => {
    expect(countsForDlReview(excluded, "cv_qc", false)).toBe(false);
    expect(cardBadges(excluded, ctx()).map((b) => b.key)).not.toContain("dl_review");
    expect(cardBadges(excluded, ctx({ viewerOwnsDlReview: false })).map((b) => b.key)).not.toContain("dl_review");
    expect(cardNextStep(action, excluded, ctx())).toMatchObject({ who: "DL", mine: false });
    expect(dlSendQueue([excluded], () => false, NOW)).toEqual([]);
    // Przegląd dalej da się otworzyć — karta jest gotowa, tylko się nie liczy.
    expect(isReadyForDlSend(excluded, "cv_qc", false)).toBe(true);
  });

  it("karta w kolejce i starszy serwer bez pola — jak dotąd", () => {
    for (const counted of [item({ dl_send_counts: true }), item()]) {
      expect(countsForDlReview(counted, "cv_qc", false)).toBe(true);
      expect(cardBadges(counted, ctx()).map((b) => b.label)).toEqual(["Czeka na Ciebie · 1 dzień"]);
      expect(cardNextStep(action, counted, ctx())).toMatchObject({ who: MY_MOVE_LABEL, mine: true });
      expect(dlSendQueue([counted], () => false, NOW)).toHaveLength(1);
    }
    // Nie gotowa (QC do poprawy) — dalej poza kolejką.
    expect(countsForDlReview(item({ qc: { status: "failed", blocking_failed: 1 } }), "cv_qc", false)).toBe(false);
  });
});
