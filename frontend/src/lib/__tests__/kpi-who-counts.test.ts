import { describe, expect, it } from "vitest";

import {
  candidateJobsBadge,
  countedSince,
  currentPeriodHint,
  groupByDay,
  historyNote,
  isIsoDay,
  isLatestPeriod,
  metricFromSlug,
  moverText,
  periodLabel,
  periodRange,
  rangeLabel,
  shiftPeriod,
  stateFilters,
  stateText,
  summaryParts,
  teamListReconcile,
  warsawToday,
  whoCountsHref,
} from "@/lib/kpi-who-counts";
import type {
  RecruitmentActivityDetailItem,
  RecruitmentActivityDetailResponse,
} from "@/lib/recruitment-activity-api";

const TODAY = "2026-10-17"; // sobota

function item(partial: Partial<RecruitmentActivityDetailItem> = {}): RecruitmentActivityDetailItem {
  return {
    candidate: { id: 1, name: "Anna Przykładowa", href: "/candidates/1" },
    job: { id: 7, title: "Java Developer", client_name: "Bank Przykładowy", href: "/jobs/7?candidate=1" },
    credited_user: { id: 11, name: "Ola Testowa", role: "recruiter" },
    reached_at: "2026-10-15T14:05:00Z",
    moved_by: { id: 21, name: "Marta Testowa", role: "delivery_lead" },
    state: "waiting",
    state_stage: "cv_sent",
    state_since: "2026-10-15T14:05:00Z",
    state_reason: null,
    candidate_jobs: 1,
    ...partial,
  };
}

function response(partial: Partial<RecruitmentActivityDetailResponse> = {}): RecruitmentActivityDetailResponse {
  return {
    generated_at: "2026-10-17T10:00:00Z",
    metric: "recommendation",
    window: "week",
    page: 1,
    page_size: 50,
    total: 23,
    items: [],
    scope: "person",
    subject: { id: 11, name: "Ola Testowa", role: "recruiter" },
    people: 21,
    moved_by_credited: 7,
    states: { waiting: 11, at_client: 6, rejected_by_client: 5, hired: 1 },
    period_total: 23,
    ...partial,
  };
}

describe("okresy listy", () => {
  it("tydzień zaczyna się w poniedziałek, jak cel „Rekomendacje w tygodniu”", () => {
    expect(periodRange("week", "2026-10-15")).toEqual({ start: "2026-10-12", end: "2026-10-18" });
    expect(periodRange("week", "2026-10-12")).toEqual({ start: "2026-10-12", end: "2026-10-18" });
    expect(periodRange("week", "2026-10-18")).toEqual({ start: "2026-10-12", end: "2026-10-18" });
  });

  it("miesiąc i dzień", () => {
    expect(periodRange("month", "2026-02-10")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(periodRange("day", "2026-10-15")).toEqual({ start: "2026-10-15", end: "2026-10-15" });
  });

  it("strzałki przesuwają o cały okres, także przez koniec miesiąca i roku", () => {
    expect(shiftPeriod("week", "2026-10-15", -1)).toBe("2026-10-05");
    expect(shiftPeriod("month", "2026-01-31", -1)).toBe("2025-12-01");
    expect(shiftPeriod("day", "2026-03-01", -1)).toBe("2026-02-28");
  });

  it("strzałka „dalej” jest martwa w bieżącym okresie", () => {
    expect(isLatestPeriod("week", "2026-10-15", TODAY)).toBe(true);
    expect(isLatestPeriod("week", "2026-10-05", TODAY)).toBe(false);
    expect(isLatestPeriod("day", TODAY, TODAY)).toBe(true);
  });

  it("etykiety okresów", () => {
    expect(periodLabel("week", "2026-10-15", TODAY)).toBe("12–18 paź");
    expect(periodLabel("week", "2026-10-01", TODAY)).toBe("28 wrz – 4 paź");
    expect(periodLabel("week", "2025-10-15", TODAY)).toBe("13–19 paź 2025");
    expect(periodLabel("day", "2026-10-15", TODAY)).toBe("czwartek 15.10");
    expect(periodLabel("month", "2026-10-15", TODAY)).toBe("październik 2026");
    expect(rangeLabel({ start: "2026-10-01", end: "2026-10-31" }, TODAY)).toBe("1–31 paź");
    expect(currentPeriodHint("week", "2026-10-13", TODAY)).toBe("ten tydzień");
    expect(currentPeriodHint("week", "2026-10-05", TODAY)).toBeNull();
  });

  it("odrzuca dzień spoza kalendarza", () => {
    expect(isIsoDay("2026-10-15")).toBe(true);
    expect(isIsoDay("2026-02-30")).toBe(false);
    expect(isIsoDay("15.10.2026")).toBe(false);
    expect(isIsoDay(null)).toBe(false);
  });

  it("„dziś” to kalendarz Warszawy, nie UTC", () => {
    // 23:30 UTC 16.10 to już 17.10 w Warszawie (UTC+2).
    expect(warsawToday(new Date("2026-10-16T23:30:00Z"))).toBe("2026-10-17");
  });
});

describe("adres listy", () => {
  it("link z panelu celów otwiera właściwą zakładkę", () => {
    expect(whoCountsHref("recommendation")).toBe(
      "/insights?tab=moj-miesiac&kto=rekomendacje#kto-sie-liczy",
    );
    expect(metricFromSlug("placementy")).toBe("placement");
    expect(metricFromSlug("cokolwiek")).toBeNull();
  });
});

describe("kolumna „Teraz”", () => {
  it("czeka na klienta od N dni", () => {
    expect(stateText(item(), TODAY)).toEqual({ label: "Czeka na klienta · 2 dni", tone: "neutral" });
    expect(stateText(item({ state_since: "2026-10-16T08:00:00Z" }), TODAY)?.label).toBe(
      "Czeka na klienta · 1 dzień",
    );
    expect(stateText(item({ state_since: "2026-10-17T08:00:00Z" }), TODAY)?.label).toBe(
      "Czeka na klienta · od dziś",
    );
  });

  it("odrzucenie przez klienta z powodem i inne zakończenia", () => {
    expect(
      stateText(item({ state: "rejected_by_client", state_stage: "rejected", state_reason: "Stawka" }), TODAY),
    ).toEqual({ label: "Klient odrzucił · Stawka", tone: "danger" });
    expect(stateText(item({ state: "ended", state_stage: "withdrawn" }), TODAY)?.label).toBe(
      "Rezygnacja kandydata",
    );
    expect(stateText(item({ state: "ended", state_stage: "rejected" }), TODAY)?.label).toBe(
      "Odrzucenie u nas",
    );
  });

  it("u klienta według etapu i zatrudnienie z datą", () => {
    expect(stateText(item({ state: "at_client", state_stage: "client_interview" }), TODAY)?.label).toBe(
      "Rozmowa u klienta",
    );
    expect(stateText(item({ state: "at_client", state_stage: "acceptance" }), TODAY)?.label).toBe(
      "Klient zaakceptował",
    );
    expect(stateText(item({ state: "hired", state_since: "2026-10-16T10:00:00Z" }), TODAY)).toEqual({
      label: "Zatrudnienie 16.10",
      tone: "success",
    });
  });

  it("stary kształt odpowiedzi bez stanu = brak tekstu, nie zgadywanie", () => {
    expect(stateText(item({ state: undefined }), TODAY)).toBeNull();
  });
});

describe("wiersze i podsumowanie", () => {
  it("grupuje po dniu w kalendarzu Warszawy", () => {
    const groups = groupByDay(
      [
        item({ reached_at: "2026-10-17T07:00:00Z" }),
        item({ reached_at: "2026-10-15T21:30:00Z" }), // 23:30 w Warszawie
        item({ reached_at: "2026-10-15T08:00:00Z" }),
        item({ reached_at: "2026-10-14T22:30:00Z" }), // 00:30 15.10 w Warszawie
      ],
      TODAY,
    );
    expect(groups.map((group) => [group.label, group.items.length])).toEqual([
      ["Dziś · sobota 17.10", 1],
      ["Czwartek 15.10", 3],
    ]);
  });

  it("znaczek, gdy ta sama osoba liczy się w kilku rekrutacjach", () => {
    expect(candidateJobsBadge(item({ candidate_jobs: 2 }))).toBe("2 rekrutacje");
    expect(candidateJobsBadge(item({ candidate_jobs: 5 }))).toBe("5 rekrutacji");
    expect(candidateJobsBadge(item())).toBeNull();
  });

  it("kto kliknął: „Ty”, imię z rolą albo kreska", () => {
    expect(moverText({ id: 11, name: "Ola Testowa", role: "recruiter" }, 11)).toBe("Ty");
    expect(moverText({ id: 21, name: "Marta Testowa", role: "delivery_lead" }, 11)).toBe(
      "Marta Testowa (DL)",
    );
    expect(moverText(null, 11)).toBe("—");
  });

  it("podsumowanie własnej listy rekomendacji", () => {
    expect(summaryParts(response(), "recommendation", 11)).toEqual([
      "23 rekomendacje",
      "21 osób",
      "CV wysłane przez Ciebie: 7, pozostałe: 16",
    ]);
  });

  it("lider patrzy na cudzą listę, a weryfikacje nie mają podziału", () => {
    expect(summaryParts(response(), "recommendation", 1)[2]).toBe(
      "CV wysłane przez tę osobę: 7, pozostałe: 16",
    );
    expect(summaryParts(response({ people: 23 }), "verification", 11)).toEqual(["23 weryfikacje"]);
    expect(summaryParts(response({ period_total: 0, total: 0, people: 0 }), "placement", 11)).toEqual([
      "0 placementów",
    ]);
  });

  it("wpisy DynaReportera są w liczbie, ale nie w podziale listy", () => {
    // Wrzesień: 30 rekomendacji, z czego 25 z tygodniowych wpisów DynaReportera,
    // a na liście 5 par z NEXUS-a, 4 osoby (2 wysłane przez tę osobę).
    const september = response({
      period_total: 30,
      history_total: 25,
      total: 5,
      people: 4,
      moved_by_credited: 2,
    });
    expect(summaryParts(september, "recommendation", 11)).toEqual([
      "30 rekomendacji",
      "4 osoby",
      "25 z DynaReportera (do 11.10.2026)",
      "CV wysłane przez Ciebie: 2, pozostałe: 3",
    ]);
    expect(historyNote(september)).toContain("DynaReporterze (25)");
    expect(historyNote(response())).toBeNull();
  });

  it("okres w całości z DynaReportera nie dzieli wyniku na „przez Ciebie / pozostałe”", () => {
    const march = response({
      period_total: 34,
      history_total: 34,
      total: 0,
      people: 0,
      moved_by_credited: 0,
      items: [],
    });
    expect(summaryParts(march, "recommendation", 11)).toEqual([
      "34 rekomendacje",
      "34 z DynaReportera (do 11.10.2026)",
    ]);
  });

  it("filtry stanu w kolejności lejka i tylko z wystąpieniami", () => {
    expect(stateFilters(response()).map((filter) => [filter.label, filter.count])).toEqual([
      ["Czekają na klienta", 11],
      ["U klienta", 6],
      ["Zatrudnienia", 1],
      ["Klient odrzucił", 5],
    ]);
  });
});

describe("teamListReconcile — lista całego zespołu z lejka (25.10.2026)", () => {
  it("lista równa liczbie z lejka: bez dopisków", () => {
    expect(teamListReconcile("placement", 15, 15, 0)).toEqual({ unattributed: null, mismatch: null });
  });

  it("pary bez osoby z zasługą domykają sumę: dopisek, bez zdania o różnicy", () => {
    // Staging 25.10.2026: rekomendacje 447 z zasługą + 1 bez = 448 jak w lejku.
    expect(teamListReconcile("recommendation", 448, 447, 1)).toEqual({
      unattributed: "Do tego 1 rekomendacja bez osoby z zasługą.",
      mismatch: null,
    });
  });

  it("suma inna niż kliknięta liczba: mówi obie i dlaczego", () => {
    // Staging 25.10.2026: weryfikacje 506 + 1 bez zasługi = 507 przy 506 w lejku.
    const result = teamListReconcile("verification", 506, 506, 1);
    expect(result.unattributed).toBe("Do tego 1 weryfikacja bez osoby z zasługą.");
    expect(result.mismatch).toMatch(/^Lejek pokazuje 506, lista 507:/);
  });

  it("odmiana przez liczby i brak klikniętej liczby (kafelek)", () => {
    expect(teamListReconcile("placement", null, 3, 5).unattributed).toBe(
      "Do tego 5 placementów bez osoby z zasługą.",
    );
    expect(teamListReconcile("placement", null, 3, 5).mismatch).toBeNull();
  });
});

describe("countedSince — akceptacje liczone od 12.10.2026", () => {
  it("okres w całości przed 12.10: nie liczono", () => {
    expect(countedSince("acceptance", { start: "2026-09-01", end: "2026-09-30" })).toBe("none");
    expect(countedSince("acceptance", { start: "2026-10-01", end: "2026-10-11" })).toBe("none");
  });

  it("okres przez 12.10: liczone od 12.10", () => {
    expect(countedSince("acceptance", { start: "2026-10-01", end: "2026-10-12" })).toBe("partial");
  });

  it("okres od 12.10 i inne etapy: całe okno", () => {
    expect(countedSince("acceptance", { start: "2026-10-12", end: "2026-10-25" })).toBe("full");
    expect(countedSince("placement", { start: "2026-09-01", end: "2026-09-30" })).toBe("full");
  });
});
