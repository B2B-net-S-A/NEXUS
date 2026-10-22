/** Pomocniki listy „Opieka · Ten tydzień” — powód, tydzień, „Ostatnio”, toast przekazania. */
import { describe, expect, it } from "vitest";

import { handoffToast } from "@/components/care/week/FrontOfficeSection";
import {
  daysBetween,
  feedbackDueText,
  frontOfficeText,
  reasonPill,
  shiftIso,
  shortNames,
  signalPills,
  visibleCards,
  weekColumns,
  weekProgress,
  weekRangeLabel,
} from "@/components/care/week/week-format";
import type { WeekContact, WeekReason } from "@/lib/api/care";

function reason(overrides: Partial<WeekReason>): WeekReason {
  return {
    kind: "day_30",
    label: "Dzień 30",
    due_on: "2026-10-14",
    overdue: false,
    plan_item_id: 1,
    from_conversation_on: null,
    ...overrides,
  };
}

function row(overrides: Partial<WeekContact>): WeekContact {
  return {
    contract_id: 1,
    candidate_id: 2,
    candidate_name: "Ewa Przykładowa",
    client_id: 3,
    client_name: "Firma Testowa",
    job_title: null,
    start_date: null,
    end_date: null,
    owner: null,
    reasons: [reason({})],
    due_on: "2026-10-14",
    overdue: false,
    overdue_days: 0,
    plan_item_id: 1,
    manager: null,
    last_conversation: null,
    signals: [],
    front_office: { reasons: [], handed_off_on: null },
    ...overrides,
  };
}

describe("tydzień", () => {
  it("przesuwa daty bez strefy i podpisuje tydzień pracy", () => {
    expect(shiftIso("2026-10-19", 7)).toBe("2026-10-26");
    expect(shiftIso("2026-11-02", -7)).toBe("2026-10-26");
    expect(weekRangeLabel("2026-10-19", "2026-10-23")).toBe("19–23.10");
    expect(weekRangeLabel("2026-10-26", "2026-10-30")).toBe("26–30.10");
    expect(weekRangeLabel("2026-11-30", "2026-12-04")).toBe("30.11–04.12");
    expect(daysBetween("2026-10-11", "2026-10-14")).toBe(3);
  });
});

describe("powód kontaktu", () => {
  const today = "2026-10-14";

  it("pigułka: zaległy z liczbą dni, umówiony niebieski, data tylko poza kolumną dnia", () => {
    expect(reasonPill(reason({ due_on: "2026-10-11", overdue: true }), today)).toEqual({
      text: "3 dni po · dzień 30",
      tone: "danger",
    });
    expect(reasonPill(reason({ due_on: "2026-10-13", overdue: true }), today).text).toBe(
      "1 dzień po · dzień 30",
    );
    const followUp = reason({
      kind: "follow_up",
      label: "Umówiony kontakt",
      due_on: "2026-10-16",
      plan_item_id: null,
      from_conversation_on: "2026-10-01",
    });
    expect(reasonPill(followUp, today)).toEqual({
      text: "umówiony kontakt z 01.10",
      tone: "info",
    });
    expect(reasonPill(followUp, today, true).text).toBe("16.10 · umówiony kontakt z 01.10");
    expect(reasonPill(reason({ due_on: today }), today, true).text).toBe("dziś · dzień 30");
    expect(
      reasonPill(reason({ kind: "pre_end", label: "Przed końcem zamówienia", due_on: "2026-10-15" }), today),
    ).toEqual({ text: "30 dni przed końcem zamówienia", tone: "neutral" });
  });

  it("sygnały: kolejka przepięć i front office bez powtórzeń", () => {
    expect(
      signalPills(
        row({
          signals: ["project_end", "attrition_risk"],
          front_office: { reasons: ["project_end", "wants_change"], handed_off_on: null },
        }),
      ),
    ).toEqual(["kończy projekt", "ryzyko odejścia", "chce zmiany projektu"]);
    expect(signalPills(row({}))).toEqual([]);
  });

  it("termin opinii: czeka od (minął albo dziś) albo „do”", () => {
    expect(feedbackDueText("2026-10-10", today)).toEqual({ text: "czeka od 10.10", overdue: true });
    expect(feedbackDueText(today, today)).toEqual({ text: "czeka od 14.10", overdue: false });
    expect(feedbackDueText("2026-10-16", today)).toEqual({ text: "do 16.10", overdue: false });
  });

  it("front office i skrócone nazwiska w prośbie o opinię", () => {
    expect(frontOfficeText(["project_end", "wants_change"])).toBe(
      "kończy projekt · chce zmiany projektu",
    );
    expect(shortNames(["Jan Kowalski-Przykładowy", "Ewa Lis", null])).toBe(
      "Jan K., Ewa L., konsultant",
    );
  });
});

describe("plan dni", () => {
  const week = { from: "2026-10-19", to: "2026-10-23", today: "2026-10-21", is_current: true };

  it("zaległe w pierwszej kolumnie, reszta w dniu terminu, dziś wyróżnione", () => {
    const late = row({ contract_id: 1, due_on: "2026-10-20", overdue: true });
    const older = row({ contract_id: 2, due_on: "2026-10-02", overdue: true });
    const today = row({ contract_id: 3, due_on: "2026-10-21" });
    const friday = row({ contract_id: 4, due_on: "2026-10-23" });
    const stray = row({ contract_id: 5, due_on: "2026-10-27" });
    const columns = weekColumns([late, older, today, friday, stray], week);
    expect(columns.map((c) => c.label)).toEqual(["Zaległe", "pn 19", "wt 20", "śr 21", "cz 22", "pt 23"]);
    // Najdłużej po terminie na górze (limit kolumny, 20.10.2026).
    expect(columns[0].items.map((r) => r.contract_id)).toEqual([2, 1]);
    // Wtorek minął — zaległy z wtorku stoi w „Zaległe”, nie we wtorku.
    expect(columns[2]).toMatchObject({ isPast: true, items: [] });
    expect(columns[3]).toMatchObject({ isToday: true, isPast: false });
    expect(columns[3].items.map((r) => r.contract_id)).toEqual([3]);
    // Termin po piątku (serwer go nie zwraca) nie znika — stoi w piątku.
    expect(columns[5].items.map((r) => r.contract_id)).toEqual([4, 5]);
  });

  it("kolumna pokazuje 8 najdłużej zaległych, reszta pod „Pokaż wszystkie”", () => {
    // Prod 20.10.2026: 482 zaległe w jednej kolumnie.
    const many = Array.from({ length: 482 }, (_, i) =>
      row({ contract_id: 10_000 + i, due_on: shiftIso("2026-10-18", -(i % 90)), overdue: true }),
    );
    const [before] = weekColumns(many, week);
    expect(before.items).toHaveLength(482);
    const dues = before.items.map((r) => r.due_on);
    expect(dues).toEqual([...dues].sort());
    const { shown, hidden } = visibleCards(before.items, false);
    expect(shown).toHaveLength(8);
    expect(hidden).toBe(474);
    expect(shown).toEqual(before.items.slice(0, 8));
    expect(shown[0].due_on).toBe(shiftIso("2026-10-18", -89));
    expect(visibleCards(before.items, true)).toEqual({ shown: before.items, hidden: 0 });
  });

  it("do 8 kart bez przycisku; wybrana karta spoza limitu rozwija kolumnę", () => {
    const few = [1, 2, 3].map((id) => row({ contract_id: id }));
    expect(visibleCards(few, false)).toEqual({ shown: few, hidden: 0 });
    const ten = Array.from({ length: 10 }, (_, i) => row({ contract_id: i + 1 }));
    expect(visibleCards(ten, false, 3).hidden).toBe(2);
    expect(visibleCards(ten, false, 10)).toEqual({ shown: ten, hidden: 0 });
  });

  it("tydzień z przyszłości bez zaległych zaczyna się od „Wcześniej”", () => {
    const next = { from: "2026-10-26", to: "2026-10-30", today: "2026-10-21", is_current: false };
    const thursday = row({ contract_id: 7, due_on: "2026-10-22" });
    const columns = weekColumns([thursday], next);
    expect(columns[0].label).toBe("Wcześniej");
    expect(columns[0].items).toHaveLength(1);
    expect(columns.some((c) => c.isToday)).toBe(false);
    expect(weekColumns([row({ due_on: "2026-10-20", overdue: true })], next)[0].label).toBe("Zaległe");
  });

  it("pasek: zapisane z zaplanowanych, bez dzielenia przez zero", () => {
    const counts = { contacts: 3, done: 1, overdue: 1, feedback: 0, front_office: 0 };
    expect(weekProgress(counts)).toEqual({ done: 1, total: 4, percent: 25 });
    expect(weekProgress({ ...counts, contacts: 0, done: undefined })).toEqual({
      done: 0,
      total: 0,
      percent: 0,
    });
  });
});

describe("panel i przekazanie", () => {

  it("toast mówi, kto naprawdę dostał powiadomienie", () => {
    const base = {
      contract_id: 1,
      handed_off_on: "2026-10-14",
      reasons: ["project_end" as const],
      job_ids: [],
      recipients: [{ id: 7, name: "Anna DL" }],
      redeploy_item_id: 3,
    };
    expect(handoffToast({ ...base, notified: [{ id: 7, name: "Anna DL" }] })).toEqual({
      text: "Przekazano do front office. Powiadomieni: Anna DL.",
      tone: "success",
    });
    expect(handoffToast({ ...base, notified: [] }).tone).toBe("info");
  });
});
