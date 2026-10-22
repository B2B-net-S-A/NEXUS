/**
 * Karta konsultanta: cztery liczby (z kręgiem D11 dla opinii), „Sprawy · N
 * otwarte” i filtry „Historii”.
 */
import { describe, expect, it } from "vitest";

import type { CardCase, TimelineEvent } from "@/lib/api/care";

import {
  cardSubtitle,
  caseMeta,
  caseStatusPill,
  caseWhen,
  casesHeading,
  closedCasesLine,
  daysAheadText,
  daysAgoText,
  eventDetailSeparator,
  historyCounts,
  historyEvents,
  lastContactKpi,
  managerFeedbackKpi,
  orderEndKpi,
  satisfactionKpi,
  teamText,
} from "../card-format";

const event = (kind: TimelineEvent["kind"], on: string, future = false): TimelineEvent => ({
  kind,
  on,
  title: kind,
  detail: null,
  link: null,
  future,
});

const kase = (id: number, status: string): CardCase => ({
  id,
  title: `Sprawa ${id}`,
  area: "administration",
  area_label: "Administracja",
  status,
  status_label: status,
  due_on: null,
  follow_up_on: null,
  assignee_name: null,
  source: "manual",
  content_hidden: false,
});

describe("card-format", () => {
  it("dni temu i do przodu", () => {
    expect(daysAgoText(0)).toBe("dziś");
    expect(daysAgoText(1)).toBe("wczoraj");
    expect(daysAgoText(12)).toBe("12 dni temu");
    expect(daysAheadText(34)).toBe("za 34 dni");
    expect(daysAheadText(1)).toBe("jutro");
    expect(daysAheadText(-1)).toBe("minął wczoraj");
    expect(daysAheadText(-4)).toBe("minął 4 dni temu");
  });

  it("ostatni kontakt: data, „20 dni temu · rytm co 2 tyg.”; zadowolenie „było 5 / 5”", () => {
    expect(lastContactKpi(null)).toMatchObject({ value: "brak rozmów", tone: "warning", note: null });
    expect(lastContactKpi({ on: "2026-10-01", days_ago: 20 }, { level: "biweekly", until_on: null }, "2026-10-21")).toMatchObject({
      value: "01.10",
      note: "20 dni temu · rytm co 2 tyg.",
    });
    expect(
      lastContactKpi({ on: "2025-12-30", days_ago: 295 }, { level: "monthly", until_on: "2026-11-30" }, "2026-10-21"),
    ).toMatchObject({ value: "30.12.2025", note: "295 dni temu · rytm co miesiąc do 30.11", tone: "warning" });
    expect(satisfactionKpi({ value: 4, previous: 5 })).toMatchObject({ value: "4 / 5", note: "było 5 / 5", tone: "good" });
    expect(satisfactionKpi({ value: 3, previous: 3 })).toMatchObject({ note: "bez zmian", tone: "warning" });
    expect(satisfactionKpi({ value: 5, previous: null }).note).toBeNull();
    expect(satisfactionKpi(null).value).toBe("—");
  });

  it("opinia menedżera: spoza D11 nie widać nic; „4,0” i „przedłużenie: tak”", () => {
    const hidden = managerFeedbackKpi({ avg: 2.5, extension: "no", on: "2026-10-01" }, false);
    expect(hidden.value).toBe("—");
    expect(hidden.note).not.toMatch(/2,5/);
    expect(managerFeedbackKpi({ avg: 4, extension: "yes", on: "2026-07-08" }, true)).toMatchObject({
      value: "4,0",
      note: "przedłużenie: tak",
      tone: "good",
    });
    expect(managerFeedbackKpi({ avg: 3.7, extension: null, on: "2026-10-01" }, true)).toMatchObject({
      value: "3,7",
      note: "z 01.10.2026",
      tone: "warning",
    });
    expect(managerFeedbackKpi(null, true).value).toBe("brak opinii");
  });

  it("koniec zamówienia: data i „za 32 dni”; ≤ 30 dni czerwony, ≤ 60 żółty", () => {
    expect(orderEndKpi({ on: "2026-11-22", days: 32 }, "2026-10-21")).toMatchObject({
      value: "22.11",
      note: "za 32 dni",
      tone: "warning",
    });
    expect(orderEndKpi({ on: "2027-01-10", days: 81 }, "2026-10-21").value).toBe("10.01.2027");
    expect(orderEndKpi({ on: "2026-11-20", days: 29 }).tone).toBe("danger");
    expect(orderEndKpi({ on: "2026-12-10", days: 49 }).tone).toBe("warning");
    expect(orderEndKpi({ on: "2027-03-01", days: 130 }).tone).toBe("neutral");
    expect(orderEndKpi(null).value).toBe("bez daty");
  });

  it("podtytuł: rola · klient · forma od startu · opiekun", () => {
    expect(
      cardSubtitle({
        role: "Java Developer",
        client_name: "Bank Przykładowy",
        form: "b2b",
        start_on: "2025-12-25",
        owner: { user_id: 1, name: "Natalia O.", source: "contract" },
      }),
    ).toBe("Java Developer · Bank Przykładowy · B2B od 25.12.2025 · opiekun Natalia O.");
    expect(
      cardSubtitle({ role: null, client_name: "Bank", form: null, start_on: null, owner: { user_id: null, name: null, source: null } }),
    ).toBe("Bank · bez opiekuna");
  });

  it("zespół: liczba osób z zewnątrz i dostawcami", () => {
    expect(teamText("9", 4, ["Dostawca A", "Dostawca B"])).toBe("zespół 9 osób (4 z zewnątrz: Dostawca A, Dostawca B)");
    expect(teamText("9", null, [])).toBe("zespół 9 osób");
    expect(teamText(null, null, ["Dostawca A"])).toBe("dostawcy: Dostawca A");
    expect(teamText(null, null, [])).toBeNull();
  });

  it("wiersz sprawy: obszar, źródło, prowadzący, ukryta treść; status i termin", () => {
    const negotiation: CardCase = {
      ...kase(5, "in_progress"),
      area: "negotiation",
      area_label: "Negocjacje",
      assignee_name: "Natalia O.",
      content_hidden: true,
      due_on: "2026-10-27",
    };
    expect(caseMeta(negotiation)).toBe("Negocjacje · ręcznie · prowadzi Natalia O. · treść tylko w Sprawach");
    expect(caseStatusPill(negotiation)).toEqual({ label: "W toku", tone: "warning" });
    expect(caseWhen(negotiation)).toBe("do 27.10");
    // Osoba ukryta tytułem zastępczym — nic o osobie, nie „bez osoby”.
    expect(caseMeta({ ...kase(6, "new"), assignee_hidden: true, content_hidden: true })).toBe(
      "Administracja · ręcznie · treść tylko w Sprawach",
    );
    expect(caseMeta({ ...kase(7, "new"), source: "mail" })).toBe("Administracja · z maila · bez osoby");
    const waiting = { ...kase(8, "waiting"), due_on: "2026-10-30", follow_up_on: "2026-10-26" };
    expect(caseStatusPill(waiting).label).toBe("Czeka");
    expect(caseWhen(waiting)).toBe("odezwać się 26.10");
    expect(caseWhen(kase(9, "new"))).toBeNull();
  });

  it("zamknięte sprawy jedną linią z datą i checklistą", () => {
    expect(closedCasesLine([kase(1, "new")])).toBeNull();
    expect(
      closedCasesLine([
        { ...kase(2, "closed"), title: "Wejście konsultanta", closed_on: "2026-09-18", checklist_done: 4, checklist_total: 4 },
        { ...kase(3, "done"), title: "Laptop" },
      ]),
    ).toBe("Zamknięte: Wejście konsultanta · 18.09 · 4/4; Laptop");
  });

  it("nagłówek spraw liczy tylko otwarte", () => {
    expect(casesHeading([])).toBe("Sprawy");
    expect(casesHeading([kase(1, "new"), kase(2, "waiting"), kase(3, "closed")])).toBe("Sprawy · 2 otwarte");
    expect(casesHeading([kase(1, "in_progress")])).toBe("Sprawy · 1 otwarta");
  });

  it("filtry historii: przeszłe od najnowszych, przyszłe na górze — we „Wszystko” i w swoim filtrze", () => {
    const events = [
      event("start", "2026-01-05"),
      event("conversation", "2026-10-01"),
      event("case_opened", "2026-10-03"),
      event("feedback", "2026-09-20"),
      event("owner", "2026-08-01"),
      event("plan", "2026-11-01", true),
      event("tech_card", "2026-10-01"),
    ];
    expect(historyEvents(events, "all").past.map((e) => e.kind)).toEqual([
      "case_opened",
      "conversation",
      "tech_card",
      "feedback",
      "owner",
      "start",
    ]);
    expect(historyEvents(events, "all").ahead).toHaveLength(1);
    expect(historyEvents(events, "talks").past.map((e) => e.kind)).toEqual(["conversation", "tech_card"]);
    // Plan rozmowy stoi też w „Rozmowach” (makieta P2), nie w „Sprawach”.
    expect(historyEvents(events, "talks").ahead.map((e) => e.kind)).toEqual(["plan"]);
    expect(historyEvents(events, "cases").ahead).toEqual([]);
    expect(
      historyEvents([event("order_end", "2026-12-01", true), event("plan", "2026-10-24", true)], "all").ahead.map(
        (e) => e.kind,
      ),
    ).toEqual(["plan", "order_end"]);
    expect(eventDetailSeparator("„Chciałby projekt z większym zespołem.”")).toBe(" — ");
    expect(eventDetailSeparator("za 2 dni")).toBe(" · ");
    expect(historyEvents(events, "cases").past.map((e) => e.kind)).toEqual(["case_opened"]);
    expect(historyEvents(events, "contract").past.map((e) => e.kind)).toEqual(["start"]);
    expect(historyCounts(events)).toEqual({ all: 6, talks: 2, cases: 1, feedback: 1, contract: 1 });
  });
});
