import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { CardPreContract } from "@/lib/api/preContracts";
import { cardBadges, knownForwardGap, type CardBadgeContext } from "@/lib/board-card-badges";
import {
  PRE_CONTRACT_STOP_GAP,
  canSetPreContractStop,
  cardStopsBefore,
  nextColumn,
  stopOriginText,
} from "@/lib/pre-contract-stop";

// 0761 (23.11.2026): „Zatrzymaj do podpisu przedwstępnej” — kolumnę blokady
// liczy serwer (`stop_column`), karta pokazuje ją od następnego kroku.

const NOW = new Date("2026-11-23T10:00:00Z");

const pc = (extra: Partial<CardPreContract> = {}): CardPreContract => ({
  id: 2,
  state: "requested",
  label: "Przedwstępna przed wysłaniem CV — nie wystawiona",
  tone: "missing",
  detail: "Prośba — nie wystawiona",
  stop_column: "cv_sent",
  stop_origin: "job",
  ...extra,
});

function item(pre_contract: CardPreContract | null): KanbanItem {
  return { id: 1, candidate_id: 11665, stage: "interview", pre_contract } as KanbanItem;
}

function ctx(column: CardBadgeContext["column"]): CardBadgeContext {
  return { column, cproEnabled: false, viewerId: 14, now: NOW };
}

describe("blokada od kolumny z serwera", () => {
  it("staje dopiero przed kolumną etapu", () => {
    expect(cardStopsBefore(pc(), nextColumn("verified"))).toBe(false); // → QC CV wolne
    expect(cardStopsBefore(pc(), nextColumn("cv_qc"))).toBe(true); // → CV wysłane stoi
    expect(cardStopsBefore(pc(), "client_interview")).toBe(true);
    expect(cardStopsBefore(pc({ stop_column: null }), "cv_sent")).toBe(false);
    expect(cardStopsBefore(null, "cv_sent")).toBe(false);
  });

  it("karta na QC CV ma czerwone „Stop” i kłódkę na strzałce", () => {
    const [badge] = cardBadges(item(pc()), ctx("cv_qc")).filter((b) => b.key === "pre_contract");
    expect(badge.label).toBe("Stop · Przedwstępna przed wysłaniem CV — nie wystawiona");
    expect(badge.tone).toBe("urgent");
    expect(badge.title).toContain("ustawienie rekrutacji");
    expect(knownForwardGap(item(pc()), "cv_qc")).toBe(PRE_CONTRACT_STOP_GAP);
    // Blokada obowiązuje też Delivery Leada (bez bramek pól).
    expect(knownForwardGap(item(pc()), "cv_qc", { skipsFillGates: true })).toBe(PRE_CONTRACT_STOP_GAP);
  });

  it("karta na Zweryfikowanym ma zwykłą plakietkę i wolną strzałkę", () => {
    const [badge] = cardBadges(item(pc()), ctx("verified")).filter((b) => b.key === "pre_contract");
    expect(badge.label).toBe("Przedwstępna przed wysłaniem CV — nie wystawiona");
    expect(badge.tone).not.toBe("urgent");
    expect(knownForwardGap(item(pc()), "verified", { skipsFillGates: true })).toBeNull();
  });
});

describe("napis źródła blokady", () => {
  it("mówi, skąd blokada i kto ją ustawił", () => {
    expect(stopOriginText({ origin: "job", set_by_name: "Olaf M.", set_at: "2026-11-23T10:00" })).toBe(
      "ustawienie rekrutacji — Olaf M., 23.11",
    );
    expect(stopOriginText({ origin: "person", set_by_name: null, set_at: null })).toBe("przy tej osobie");
  });
});

describe("kto ustawia blokadę (podpowiedź roli; serwer zawęża DL-a do klientów)", () => {
  it("DL, Head of Recruitment i admin tak, rekruter nie", () => {
    const who = (role: string) => canSetPreContractStop({ role, roles: [role] } as never);
    expect(who("delivery_lead")).toBe(true);
    expect(who("head_of_recruitment")).toBe(true);
    expect(who("admin")).toBe(true);
    expect(who("recruiter")).toBe(false);
    expect(canSetPreContractStop(null)).toBe(false);
  });
});
