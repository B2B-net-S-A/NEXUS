import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  cardBadges,
  cardNextStep,
  claimAction,
  formatClientRate,
  hoursLeft,
  knownForwardGap,
  qcChip,
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
    // Screening to ta sama część procesu co Nowi (blokada 12 h).
    expect(claimAction(free, ctx({ column: "screening" }))).toBe("take");
    expect(labels(free, ctx({ column: "screening" }))).toEqual(["Z ogłoszenia", "Wolny"]);
  });

  it("przepięcie niesie rekrutację źródłową", () => {
    const re = item({ entry_source: "reassign", reassign_from_title: "Java · PKO BP" });
    expect(labels(re, ctx())[0]).toBe("Przepięcie · Java · PKO BP");
  });

  it("„Czeka na DL” w QC CV poza Nordeą, u Nordei nie, w Zweryfikowanym nie", () => {
    const v = item({ stage: "interview", days_in_stage: 1, qc: { status: "passed", blocking_failed: 0 } });
    expect(labels(v, ctx({ column: "cv_qc" }))).toEqual(["Czeka na DL · 1 dzień"]);
    // Niesprawdzone QC: DL jeszcze na nic nie czeka.
    const unchecked = item({ stage: "interview", days_in_stage: 1 });
    expect(labels(unchecked, ctx({ column: "cv_qc" }))).toEqual([]);
    expect(labels(v, ctx({ column: "cv_qc", cproEnabled: true }))).toEqual([]);
    expect(labels(v, ctx({ column: "verified" }))).toEqual([]);
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

  it("prepy w Teams: brak prepu i słaby prep jak inne odznaki terminarza, z podpowiedzią", () => {
    const missing = item({
      interview_badge: { kind: "prep_missing", label: "Brak prepu · rozmowa jutro", tone: "urgent" },
    });
    const [badge] = cardBadges(missing, ctx({ column: "client_interview" }));
    expect(badge).toMatchObject({ key: "interview", label: "Brak prepu · rozmowa jutro", tone: "urgent" });
    expect(badge.title).toContain("brakuje prepu");
    const weak = item({
      interview_badge: { kind: "prep_weak", label: "Prep słaby · rozmowa czw 25.09", tone: "wait" },
    });
    expect(cardBadges(weak, ctx({ column: "client_interview" }))[0]).toMatchObject({
      label: "Prep słaby · rozmowa czw 25.09",
      tone: "wait",
    });
  });

  it("pomocnicze: godziny blokady i format stawki", () => {
    expect(hoursLeft("2026-09-23T10:30:00Z", NOW)).toBe("<1 h");
    expect(formatClientRate(item({ client_rate_value: "1200", client_rate_unit: "daily" }))).toBe(
      "do klienta 1200 zł/MD",
    );
    expect(formatClientRate(item({ client_rate_value: null }))).toBeNull();
  });
});

describe("Rekrutacja v5: chip QC, znany brak i „kto ma ruch”", () => {
  it("chip QC mówi wynik ostatniej kontroli; brak pola = „nie sprawdzone”", () => {
    expect(qcChip(item({})).label).toBe("QC nie sprawdzone");
    expect(qcChip(item({ qc: { status: "passed", blocking_failed: 0 } })).label).toBe("QC ✓");
    expect(qcChip(item({ qc: { status: "failed", blocking_failed: 3 } }))).toMatchObject({
      label: "QC: 3 do poprawy",
      tone: "urgent",
    });
    expect(qcChip(item({ qc: { status: "overridden", blocking_failed: 2 } })).label).toBe(
      "QC przepuszczone",
    );
  });

  it("strzałka jest szara tylko przy brakach, które karta zna", () => {
    expect(knownForwardGap(item({ screening_done: false }), "screening")).toBe("Brak arkusza screeningu");
    expect(knownForwardGap(item({ screening_done: true }), "screening")).toBeNull();
    // Brak pola (starszy serwer) to nie brak arkusza.
    expect(knownForwardGap(item({}), "screening")).toBeNull();
    expect(knownForwardGap(item({ qc: { status: "failed", blocking_failed: 2 } }), "cv_qc")).toBe(
      "QC: 2 do poprawy",
    );
    expect(knownForwardGap(item({ qc: { status: "unchecked", blocking_failed: 0 } }), "cv_qc")).toBeNull();
  });

  it("w QC CV ruch ma rekruter (poprawki), DL (poza Nordeą) albo osoba od Cpro", () => {
    const action = { label: "Popraw CV / wyślij", owner: "recruiter", kind: "cv" };
    const failed = item({ qc: { status: "failed", blocking_failed: 1 } });
    expect(cardNextStep(action, failed, { column: "cv_qc", cproEnabled: false })).toMatchObject({
      who: "Twój ruch",
      mine: true,
    });
    const passed = item({ qc: { status: "passed", blocking_failed: 0 } });
    expect(cardNextStep(action, passed, { column: "cv_qc", cproEnabled: false })?.who).toBe("DL");
    // Niesprawdzone QC = ruch rekrutera, nie DL.
    expect(cardNextStep(action, item({}), { column: "cv_qc", cproEnabled: false })).toMatchObject({
      who: "Twój ruch",
      label: "Sprawdź QC CV",
    });
    expect(
      cardNextStep(action, item({}), { column: "cv_qc", cproEnabled: true, stageBadge: "cpro" })?.who,
    ).toBe("Osoba od Cpro");
    expect(cardNextStep(action, passed, { column: "cv_qc", cproEnabled: true })?.label).toBe(
      "Przekaż do Cpro",
    );
    // Poza QC — lustro `nextActionFor`: klient to nie „Twój ruch”.
    expect(
      cardNextStep({ label: "Feedback klienta", owner: "client", kind: "client" }, item({}), {
        column: "cv_sent",
        cproEnabled: false,
      }),
    ).toEqual({ who: "Klient", mine: false, label: "Feedback klienta" });
    expect(
      cardNextStep({ label: "", owner: "none", kind: "none" }, item({}), { column: "closed", cproEnabled: false }),
    ).toBeNull();
  });

  it("„Twój ruch” tylko na własnej (albo niczyjej) karcie — cudza mówi imię rekrutera", () => {
    const action = { label: "Przygotuj CV do QC", owner: "recruiter", kind: "cv" };
    const mine = item({ recruiter_id: 7, recruiter_name: "Klaudia Urban" });
    expect(cardNextStep(action, mine, { column: "verified", cproEnabled: false, viewerId: 7 })).toEqual({
      who: "Twój ruch",
      mine: true,
      label: "Przygotuj CV do QC",
    });
    expect(cardNextStep(action, mine, { column: "verified", cproEnabled: false, viewerId: 9 })).toEqual({
      who: "Klaudia",
      mine: false,
      label: "Przygotuj CV do QC",
    });
    // Karta bez rekrutera — nikt jej nie „ma”, ruch jest po stronie patrzącego.
    expect(cardNextStep(action, item({}), { column: "verified", cproEnabled: false, viewerId: 9 })?.who).toBe(
      "Twój ruch",
    );
    // Nowi: aktywna blokada „Biorę” wygrywa z rekruterem karty.
    const claimed = item({ recruiter_id: 9, claim_user_id: 3, claim_user_name: "Ola Nowak" });
    expect(
      cardNextStep({ label: "Umów screening", owner: "review", kind: "screening" }, claimed, {
        column: "new",
        cproEnabled: false,
        viewerId: 9,
      })?.who,
    ).toBe("Ola");
    // Kandydat i Delivery to role, nie imiona.
    expect(
      cardNextStep({ label: "Reakcja kandydata na ofertę", owner: "candidate", kind: "offer" }, mine, {
        column: "contract",
        cproEnabled: false,
        viewerId: 7,
      })?.who,
    ).toBe("Kandydat");
    expect(
      cardNextStep({ label: "Przekaż do Delivery", owner: "delivery", kind: "contract" }, mine, {
        column: "hired",
        cproEnabled: false,
        viewerId: 7,
      })?.who,
    ).toBe("Delivery");
  });
});

describe("odznaka follow-upu (0372) — klient milczy, kto dzwoni do kandydata", () => {
  const badge = {
    caller_id: 3,
    caller_name: "Anna Kowalczyk",
    due_on: "2026-09-21",
    state: "overdue" as const,
    overdue_days: 2,
    process_count: 3,
  };

  it("zaległy telefon innej osoby: imię i liczba dni, czerwona odznaka", () => {
    const badges = cardBadges(item({ followup: badge }), ctx({ column: "cv_sent" }));
    const f = badges.find((b) => b.key === "followup");
    expect(f?.label).toBe("Follow-up: Anna K. · zaległy 2 dni");
    expect(f?.tone).toBe("urgent");
    expect(f?.title).toContain("w 3 procesach");
  });

  it("gdy dzwoni patrzący — „Ty”; termin za kilka dni nie zaśmieca karty", () => {
    const mine = item({ followup: { ...badge, caller_id: 7, state: "today", overdue_days: 0 } });
    expect(labels(mine, ctx({ column: "client_interview" }))).toContain("Follow-up: Ty · dziś");
    const later = item({ followup: { ...badge, state: "scheduled", overdue_days: 0 } });
    expect(cardBadges(later, ctx({ column: "cv_sent" })).some((b) => b.key === "followup")).toBe(
      false,
    );
  });

  it("poza kolumnami czekania na klienta odznaki nie ma", () => {
    expect(
      cardBadges(item({ followup: badge }), ctx({ column: "contract" })).some(
        (b) => b.key === "followup",
      ),
    ).toBe(false);
  });
});
