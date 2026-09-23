import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  cardBadges,
  claimAction,
  formatClientRate,
  hoursLeft,
  type CardBadgeContext,
} from "@/lib/board-card-badges";

const NOW = new Date("2026-09-23T10:00:00Z");

function item(extra: Partial<KanbanItem> = {}): KanbanItem {
  return { id: 1, candidate_id: 11, stage: "new", ...extra } as KanbanItem;
}

function ctx(extra: Partial<CardBadgeContext> = {}): CardBadgeContext {
  return { column: "new", cproEnabled: false, viewerId: 7, now: NOW, ...extra };
}

const labels = (i: KanbanItem, c: CardBadgeContext) => cardBadges(i, c).map((b) => b.label);

describe("odznaki karty — Pipeline v4", () => {
  it("osoba dodana ręcznie: „Dodałeś sam” i „Twój · 9 h” dla trzymającego blokadę", () => {
    const own = item({
      entry_source: "added_manual",
      claim_user_id: 7,
      claim_user_name: "Marta Nowak",
      claim_until: "2026-09-23T19:30:00Z",
      added_to_job_by_name: "Marta Nowak",
    });
    expect(labels(own, ctx())).toEqual(["Dodałeś sam", "Twój · 9 h"]);
    expect(claimAction(own, ctx())).toBeNull();
  });

  it("cudza blokada: imię i czas; „Przejmij” tylko gdy serwer pozwala (DL)", () => {
    const other = item({
      entry_source: "added_manual",
      claim_user_id: 3,
      claim_user_name: "Anna Kowal",
      claim_until: "2026-09-23T13:10:00Z",
      added_to_job_by_name: "Anna Kowal",
    });
    expect(labels(other, ctx())).toEqual(["Dodał(a): Anna", "Anna · 3 h"]);
    expect(claimAction(other, ctx())).toBeNull();
    expect(claimAction({ ...other, can_take: true }, ctx())).toBe("takeover");
  });

  it("wolna osoba z ogłoszenia: „Wolny” i „Biorę”", () => {
    const free = item({ entry_source: "application", can_take: true });
    expect(labels(free, ctx())).toEqual(["Z ogłoszenia", "Wolny"]);
    expect(claimAction(free, ctx())).toBe("take");
    // Poza „Nowymi” nikt niczego nie bierze.
    expect(claimAction(free, ctx({ column: "verified" }))).toBeNull();
  });

  it("przepięcie niesie rekrutację źródłową", () => {
    const re = item({ entry_source: "reassign", reassign_from_title: "Java · PKO BP" });
    expect(labels(re, ctx())[0]).toBe("Przepięcie · Java · PKO BP");
  });

  it("„Czeka na DL” w Zweryfikowanym poza Nordeą, u Nordei nie", () => {
    const v = item({ stage: "verified", days_in_stage: 1 });
    expect(labels(v, ctx({ column: "verified" }))).toEqual(["Czeka na DL · 1 dzień"]);
    expect(labels(v, ctx({ column: "verified", cproEnabled: true }))).toEqual([]);
  });

  it("stawka do klienta i cisza klienta w „CV wysłane”", () => {
    const sent = item({
      stage: "cv_sent",
      client_rate_value: "165.00",
      client_rate_unit: "hourly",
      client_rate_currency: "PLN",
      days_in_stage: 5,
    });
    expect(labels(sent, ctx({ column: "cv_sent" }))).toEqual([
      "do klienta 165 zł/h",
      "5 dni bez odpowiedzi",
    ]);
  });

  it("terminarz rozmowy i zamówienie po zatrudnieniu", () => {
    const iv = item({
      interview_badge: { kind: "call_due", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
    });
    expect(cardBadges(iv, ctx({ column: "client_interview" }))).toEqual([
      { key: "interview", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
    ]);
    expect(labels(item({ order_status: "missing" }), ctx({ column: "hired" }))).toEqual([
      "Brak zamówienia",
    ]);
    expect(labels(item({ order_status: "complete" }), ctx({ column: "hired" }))).toEqual([
      "Zamówienie ✓",
    ]);
  });

  it("pomocnicze: godziny blokady i format stawki", () => {
    expect(hoursLeft("2026-09-23T10:30:00Z", NOW)).toBe("<1 h");
    expect(formatClientRate(item({ client_rate_value: "1200", client_rate_unit: "daily" }))).toBe(
      "do klienta 1200 zł/MD",
    );
    expect(formatClientRate(item({ client_rate_value: null }))).toBeNull();
  });
});
